"""add ingestion indexes

Revision ID: 4b8d6e2a97f1
Revises: a1b2c3d4e5f6
Create Date: 2026-09-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b8d6e2a97f1"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Indexes needed to keep ingestion affordable as repositories grow.
#
# ``CREATE INDEX CONCURRENTLY`` cannot run inside the transaction Alembic wraps every
# upgrade in (``env.py`` opens one with ``begin_transaction()``), so each index is
# created in its own ``autocommit_block``. The blocks must each commit independently
# because CONCURRENTLY builds are not transactional: a crash mid-build leaves the
# index ``INVALID`` and unusable. Recover with::
#
#     DROP INDEX CONCURRENTLY IF EXISTS <name>;
#
# then re-run the migration. Keep this in mind if the migration is interrupted.
#
# Choosing CONCURRENTLY over the default is not optional here. ``scanner.py`` deletes
# every file row on each ingest (and on each of up to three retries), and Postgres
# implements ``ON DELETE CASCADE`` as a per-row ``DELETE FROM ... WHERE file_id = $1``
# -- a sequential scan per row without the matching index. Re-ingestion of a large
# repo would be O(files * symbols * dependencies) full scans without these.

_INDEXES: list[tuple[str, str, list[str]]] = [
    # parse stage: bulk-delete all files for a repository, then bulk-insert new ones.
    # ``scanner.py`` filters files by repository_id on every parse, so an index on the
    # column turns that into an index scan.
    ("ix_files_repository_id", "files", ["repository_id"]),
    # ownership map: orders rows by path. Without an index this is a sort over the
    # whole table; with one, it is a matching index scan.
    ("ix_files_path", "files", ["path"]),
    # resolve_dependencies / compute_fan_metrics: ``dependencies`` joins on both
    # ``source_symbol_id`` and ``target_symbol_id``, and both sides carry a CASCADE
    # delete triggered by every ``ast_symbols`` row removal. Without indexes each
    # cascade becomes a sequential scan.
    ("ix_ast_symbols_file_id", "ast_symbols", ["file_id"]),
    # embedder: filters to embeddable kinds per repository. A composite index keeps
    # that filter cheap when a repo has thousands of import rows that the embedder
    # does not want.
    ("ix_ast_symbols_file_id_kind", "ast_symbols", ["file_id", "kind"]),
    ("ix_dependencies_source_symbol_id", "dependencies", ["source_symbol_id"]),
    ("ix_dependencies_target_symbol_id", "dependencies", ["target_symbol_id"]),
    # embedder / RAG retrieval: every retrieval filters by repository_id first.
    ("ix_embeddings_repository_id", "embeddings", ["repository_id"]),
]


def upgrade() -> None:
    """Create the indexes, one per autocommit block."""
    for name, table, columns in _INDEXES:
        with op.get_context().autocommit_block():
            op.create_index(name, table, columns, postgresql_concurrently=True)


def downgrade() -> None:
    """Drop the indexes, one per autocommit block."""
    for name, _table, _columns in reversed(_INDEXES):
        with op.get_context().autocommit_block():
            op.drop_index(name, postgresql_concurrently=True)
