"""add per-user context window

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable per-user context window to ``users``.

    ``NULL`` is the contract, not an omission: it means "use the default
    window", so existing rows keep following the default if it changes.
    ``IF NOT EXISTS`` keeps a re-run a no-op, as in the other hand-written
    migrations, because the test database is migrated once per xdist worker and
    workers can reach it together.
    """
    op.get_bind().execute(
        sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_context_window INTEGER")
    )


def downgrade() -> None:
    """Drop the column; nothing else depends on it."""
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS ai_context_window")
