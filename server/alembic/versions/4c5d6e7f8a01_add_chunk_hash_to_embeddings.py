"""add chunk_hash to embeddings

Revision ID: 4c5d6e7f8a01
Revises: 4b8d6e2a97f1
Create Date: 2026-09-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c5d6e7f8a01"
down_revision: Union[str, Sequence[str], None] = "4b8d6e2a97f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a nullable ``chunk_hash`` column to ``embeddings``.

    The incremental embedder populates this column and uses it to detect
    chunks whose rendered text changed without their source changing --
    e.g. a symbol whose callers or definition changed, or an annotated
    file whose reading-order note was rewritten. NULL on existing rows
    is fine: the reconcile deletes-and-re-embeds any row missing a hash
    the first time the incremental path runs against it. ``String(64)``
    covers both SHA-256 (64 hex chars) and SHA-1 (40) with room to spare;
    the embedder hashes are not a security primitive so a wider column
    does no harm.
    """
    op.add_column(
        "embeddings",
        sa.Column("chunk_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Drop ``chunk_hash``.

    No data restoration is possible -- the column was added nullable and
    legacy rows never had a hash, so this is a clean drop.
    """
    op.drop_column("embeddings", "chunk_hash")
