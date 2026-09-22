"""add auto-update fields and remaining unique constraints

Revision ID: 5d6e7f8a01b2
Revises: 4c5d6e7f8a01
Create Date: 2026-09-22 00:00:00.000000

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d6e7f8a01b2"
down_revision: Union[str, Sequence[str], None] = "4c5d6e7f8a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add the columns and constraints required by the auto-update feature.

    The new columns on ``repositories`` carry ``server_default``s so a row inserted
    without them (e.g. the rebuild path that lists every field explicitly) still
    lands in a usable state.

    Two unique constraints land here because both gates the incremental path
    depends on:

    * ``uq_dependency_edge`` -- ``resolve_dependencies`` only ever INSERTs, so a
      whole-repo re-resolve without a prior delete silently duplicates every edge
      and inflates fan-in. The constraint fails a regression the first time it
      tries, instead of corrupting metrics invisibly.
    * ``uq_embedding_source`` -- the embedder writes per-source-type ``source_id``
      (symbol id, file id, commit hash, PR id, or a per-section uuid5 for README).
      Today the only enforcement is application code; the constraint makes the
      contract stand alone.

    Idempotency: every DDL statement here is a no-op when it has already been
    applied. The migration is safe to re-run against a database left half-upgraded
    by an interrupted run -- a property the test infra relies on when an xdist
    worker migrates the shared database twice in quick succession.
    """
    bind = op.get_bind()

    # --- repositories columns -------------------------------------------------
    #
    # ``ADD COLUMN IF NOT EXISTS`` lets a re-run pick up where an interrupted
    # run left off. The server defaults carry the same defaults the model's
    # ``server_default`` arguments declare.
    #
    # Raw ``ALTER TABLE`` rather than ``op.add_column`` because the latter
    # raises on a column that already exists, with no parameter for the
    # idempotent form. The plain DDL is checked at the database.
    add_column_statements = [
        (
            "ALTER TABLE repositories "
            "ADD COLUMN IF NOT EXISTS auto_update_enabled BOOLEAN DEFAULT false NOT NULL"
        ),
        (
            "ALTER TABLE repositories "
            "ADD COLUMN IF NOT EXISTS auto_update_interval_hours INTEGER DEFAULT 6 NOT NULL"
        ),
        ("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS next_sync_at TIMESTAMP WITH TIME ZONE"),
        (
            "ALTER TABLE repositories "
            "ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP WITH TIME ZONE"
        ),
        (
            "ALTER TABLE repositories "
            "ADD COLUMN IF NOT EXISTS sync_status VARCHAR(32) DEFAULT 'idle' NOT NULL"
        ),
        (
            "ALTER TABLE repositories "
            "ADD COLUMN IF NOT EXISTS sync_lease_expires_at TIMESTAMP WITH TIME ZONE"
        ),
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_generation UUID",
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_sync_error TEXT",
        (
            "ALTER TABLE repositories "
            "ADD COLUMN IF NOT EXISTS consecutive_sync_failures INTEGER DEFAULT 0 NOT NULL"
        ),
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_sync_summary JSONB",
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS analysis_commit_sha VARCHAR(40)",
    ]
    for stmt in add_column_statements:
        bind.execute(sa.text(stmt))

    # --- partial due-index -----------------------------------------------------
    #
    # ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction, and this
    # migration wraps everything else in one. Pattern follows the ingestion
    # indexes migration: an ``autocommit_block`` lets a single CONCURRENT build
    # commit independently. If the build is interrupted mid-way the index lands
    # INVALID -- recover with ``DROP INDEX CONCURRENTLY IF EXISTS`` and rerun.
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_repositories_next_sync_due "
            "ON repositories (next_sync_at) "
            "WHERE auto_update_enabled"
        )
    )

    # --- uq_dependency_edge ----------------------------------------------------
    #
    # The full pipeline never did, because ``DELETE FROM files`` cascaded every
    # edge away before each new run. An incremental path that re-resolves the
    # whole repo against a *partial* set of changed files would. Collapse any
    # existing duplicates to one row per (source, target, dep_type) tuple,
    # keeping the lowest ctid (the row Postgres inserted first).
    bind.execute(
        sa.text(
            """
            DELETE FROM dependencies
            WHERE ctid NOT IN (
                SELECT min(ctid)
                FROM dependencies
                GROUP BY source_symbol_id, target_symbol_id
            )
            """
        )
    )
    # ``IF NOT EXISTS`` on the constraint keeps the migration idempotent against
    # a database that was partially upgraded by an interrupted run -- the
    # columns and index above may already be present, in which case the
    # constraint is the missing piece.
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_dependency_edge'
                ) THEN
                    ALTER TABLE dependencies
                    ADD CONSTRAINT uq_dependency_edge
                    UNIQUE (source_symbol_id, target_symbol_id);
                END IF;
            END $$;
            """
        )
    )

    # --- uq_embedding_source ---------------------------------------------------
    #
    # README chunks used to share ``source_id = repository_id`` (one row per
    # repo, regardless of how many ``##`` sections the README had). The embedder
    # now writes per-section uuid5 ids; legacy rows need to be distinct before
    # the constraint can land. There is no section index in the stored row, so
    # the backfill re-derives a unique id from the row's primary key -- stable
    # across reruns, and meaningless for retrieval (search is by vector
    # similarity, not by source_id).
    #
    # Computed in Python rather than SQL because Postgres has no built-in
    # uuid5: it is a Python stdlib function. Pulled in batches of a few hundred
    # so a large embeddings table does not block on a single round trip.
    # The namespace is fixed here rather than imported from ``embedder`` so the
    # backfill is a one-shot data fix, not a coupling between alembic and the
    # application. The next full re-ingest rewrites these rows with the
    # embedder's per-section ids.
    backfill_ns = uuid.UUID("5c4d6e7f-8a01-4c5d-6e7f-8a014c5d6e7f")

    duplicate_ids = (
        bind.execute(
            sa.text(
                """
            SELECT id
            FROM embeddings
            WHERE source_type = 'document'
              AND source_id = repository_id
            """
            )
        )
        .scalars()
        .all()
    )

    for embedding_id in duplicate_ids:
        new_source_id = uuid.uuid5(backfill_ns, str(embedding_id))
        bind.execute(
            sa.text("UPDATE embeddings SET source_id = :new_id WHERE id = :id"),
            {"new_id": new_source_id, "id": embedding_id},
        )

    # Collapse any remaining duplicates down to one row per
    # (repository_id, source_type, source_id). The pre-constraint embedder
    # inserted unconditionally and had no delete-before-generate, so a second
    # ingest over the same repository -- a Celery retry, which re-runs the whole
    # task body, or a re-ingest that did not route through the row-deleting
    # path -- left a second copy of every commit and PR embedding. Duplicates
    # share a ``chunk_text`` by construction (the text is derived from the
    # source row, not from when it was embedded), so keeping the first-inserted
    # row loses nothing.
    #
    # This has to run *after* the document backfill above, not before: a
    # multi-section README is several rows sharing ``source_id =
    # repository_id``, so deduplicating first would collapse it to a single
    # chunk and discard real content rather than a copy of it.
    bind.execute(
        sa.text(
            """
            DELETE FROM embeddings
            WHERE ctid NOT IN (
                SELECT min(ctid)
                FROM embeddings
                GROUP BY repository_id, source_type, source_id
            )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_embedding_source'
                ) THEN
                    ALTER TABLE embeddings
                    ADD CONSTRAINT uq_embedding_source
                    UNIQUE (repository_id, source_type, source_id);
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    """Reverse every change in reverse order."""
    op.drop_constraint("uq_embedding_source", "embeddings", type_="unique")
    op.drop_constraint("uq_dependency_edge", "dependencies", type_="unique")

    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_repositories_next_sync_due",
            postgresql_concurrently=True,
        )

    op.drop_column("repositories", "analysis_commit_sha")
    op.drop_column("repositories", "last_sync_summary")
    op.drop_column("repositories", "consecutive_sync_failures")
    op.drop_column("repositories", "last_sync_error")
    op.drop_column("repositories", "sync_generation")
    op.drop_column("repositories", "sync_lease_expires_at")
    op.drop_column("repositories", "sync_status")
    op.drop_column("repositories", "last_synced_at")
    op.drop_column("repositories", "next_sync_at")
    op.drop_column("repositories", "auto_update_interval_hours")
    op.drop_column("repositories", "auto_update_enabled")

    # No data restoration for the backfilled document source_ids -- the original
    # value was identical across rows in the same repo and is now lost. A full
    # re-ingest rebuilds them.
