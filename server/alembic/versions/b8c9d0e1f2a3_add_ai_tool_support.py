"""add ai tool support columns

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record what the save-time probe learned about function calling.

    Both columns are nullable, and that is the contract rather than an
    oversight. ``NULL`` means "not measured" -- a row saved before the probe
    checked tools, or a probe that could not reach the provider. ``FALSE`` is a
    measurement: the provider answered and did not return a function call. The
    agent path checks the NULL case lazily; treating it as ``FALSE`` would
    disable agent presets for every existing user.

    ``IF NOT EXISTS`` keeps a re-run a no-op, matching the other
    hand-written migrations: the test database is migrated once per xdist
    worker and workers can reach it together.
    """
    bind = op.get_bind()
    bind.execute(
        sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_supports_tools BOOLEAN")
    )
    bind.execute(
        sa.text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "ai_tools_checked_at TIMESTAMP WITH TIME ZONE"
        )
    )


def downgrade() -> None:
    """Drop both columns; the default path does not depend on them."""
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS ai_tools_checked_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS ai_supports_tools")
