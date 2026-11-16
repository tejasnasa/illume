"""create mcp_tokens

Revision ID: b7c8d9e0f1a2
Revises: a3b4c5d6e7f8
Create Date: 2026-11-14 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add the table holding the personal access tokens used by MCP clients.

    Only the SHA-256 digest of a token is stored, under a unique index that
    is also the lookup path. The foreign key cascades, so deleting a user
    takes their tokens with it.

    Idempotency: the DDL is written so a re-run is a no-op, because the test
    database is migrated once per xdist worker and several workers can reach
    an un-migrated database at the same time.
    """
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS mcp_tokens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(60) NOT NULL,
                token_prefix VARCHAR(16) NOT NULL,
                token_hash VARCHAR(64) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                last_used_at TIMESTAMP WITH TIME ZONE,
                expires_at TIMESTAMP WITH TIME ZONE,
                revoked_at TIMESTAMP WITH TIME ZONE
            )
            """
        )
    )

    # The unique index is created rather than a table constraint so that its
    # name matches the one the model declares; it is what makes a token
    # lookup a single indexed read and rejects a duplicate digest.
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_mcp_tokens_token_hash ON mcp_tokens (token_hash)"
        )
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_mcp_tokens_user_id ON mcp_tokens (user_id)")
    )


def downgrade() -> None:
    """Drop the table; the indexes go with it."""
    op.drop_table("mcp_tokens")
