"""add lexical search, trigram indexes and file_cochange

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must stay identical to ``SEARCH_TSV_EXPRESSION`` on the Embedding model and to
# ``split_identifiers`` in Python; a test runs the column and the Python
# function on the same inputs. Copied rather than imported so the migration
# keeps describing the schema it created even after the model moves on.
_SEARCH_TSV_EXPRESSION = (
    "to_tsvector('simple'::regconfig, "
    "regexp_replace("
    "regexp_replace("
    r"regexp_replace(chunk_text, '([A-Z]+)([A-Z][a-z])', '\1 \2', 'g'), "
    r"'([a-z0-9])([A-Z])', '\1 \2', 'g'), "
    "'[_./:-]+', ' ', 'g') "
    "|| ' ' || chunk_text)"
)

_SEARCHABLE_KINDS = "kind IN ('function', 'class', 'method')"


def upgrade() -> None:
    """Add the storage the keyword, symbol-name, grep and co-change searches read.

    **Lexical search.** ``embeddings.search_tsv`` is a stored generated column,
    so Postgres fills it for every existing row during this migration and keeps
    it current on every later insert or update; nothing in the embedder changes.
    Adding a stored generated column rewrites ``embeddings`` under an exclusive
    lock, so on a large table this step takes time: run it in a quiet window.

    **Trigram indexes.** ``pg_trgm`` GIN indexes on symbol names (fuzzy name
    lookup) and on stored symbol bodies (regex search). Both are partial on the
    three searchable kinds, which keeps the body index -- the one real storage
    cost here -- to the rows that can ever match.

    **Co-change.** ``file_cochange`` holds one row per pair of files that
    changed together, with the smaller UUID first so each pair is stored once.

    The GIN indexes are built ``CONCURRENTLY`` in an autocommit block, like the
    HNSW index before them, so writes keep flowing while they build. An
    interrupted concurrent build leaves an ``INVALID`` index that ``IF NOT
    EXISTS`` would then skip; recover with ``DROP INDEX CONCURRENTLY IF EXISTS
    <name>`` and re-run. Every statement is written so a re-run is a no-op:
    the test database is migrated once per xdist worker, and workers can reach
    an unmigrated database at the same time.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        f"GENERATED ALWAYS AS ({_SEARCH_TSV_EXPRESSION}) STORED"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS file_cochange (
            file_a_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            file_b_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
            together INTEGER NOT NULL,
            a_count INTEGER NOT NULL,
            b_count INTEGER NOT NULL,
            jaccard DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (file_a_id, file_b_id),
            CONSTRAINT ck_file_cochange_ordered_pair CHECK (file_a_id < file_b_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_file_cochange_repository_id ON file_cochange (repository_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_cochange_file_b_id ON file_cochange (file_b_id)")

    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_embeddings_search_tsv "
            "ON embeddings USING gin (search_tsv)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ast_symbols_name_trgm "
            f"ON ast_symbols USING gin (name gin_trgm_ops) WHERE {_SEARCHABLE_KINDS}"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ast_symbols_source_trgm "
            f"ON ast_symbols USING gin (source_code gin_trgm_ops) WHERE {_SEARCHABLE_KINDS}"
        )


def downgrade() -> None:
    """Remove all of it except the ``pg_trgm`` extension.

    The extension is left installed: dropping it is not needed to restore the
    previous schema, and it would fail if anything else had come to rely on it.
    """
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ast_symbols_source_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ast_symbols_name_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_embeddings_search_tsv")
    op.execute("DROP TABLE IF EXISTS file_cochange")
    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS search_tsv")
