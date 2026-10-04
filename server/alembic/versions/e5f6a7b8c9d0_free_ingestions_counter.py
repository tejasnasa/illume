"""replace the free ingestion flag with a counter

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-04 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """
    Swap ``users.free_ingest_used`` for a count of ingestions spent.

    ``c3d4e5f6a7b8`` modelled the free ingestion allowance as a boolean, which
    can only express a grant of exactly one. The grant is now a tunable
    number (``FREE_INGESTIONS``), so the row has to record *how many* were
    spent rather than *whether* the single slot was.

    The counter carries ``server_default=text('0')`` for the same reason the
    other counters do: a row inserted via raw SQL -- the reingest rebuild path
    lists every column explicitly -- still lands in a usable state.

    There is deliberately **no backfill** from the old boolean. Translating
    ``true`` would have to guess which grant it was measured against, and the
    guess would be wrong the moment the policy moved: at a grant of three,
    every legacy account that had burned its single slot would be silently
    granted two more. Dropping the column instead makes the new policy apply
    uniformly to every row, which is the state the constants describe.
    """
    bind = op.get_bind()

    # Raw ``ALTER TABLE`` rather than ``op.add_column`` because the latter
    # raises on a column that already exists, with no parameter for the
    # idempotent form -- matching ``c3d4e5f6a7b8`` and ``5d6e7f8a01b2``.
    bind.execute(
        sa.text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS free_ingestions_used INTEGER DEFAULT 0 NOT NULL"
        )
    )
    bind.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS free_ingest_used"))


def downgrade() -> None:
    """
    Restore the boolean, collapsing "spent at least one" back to ``true``.

    The reverse translation is lossy -- the boolean cannot distinguish one
    spent ingestion from three -- but it is faithful to the question the old
    column asked, so a downgraded database behaves exactly as it did before
    the counter landed. Anything above zero becomes ``true``.
    """
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS free_ingest_used BOOLEAN DEFAULT false NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE users SET free_ingest_used = (free_ingestions_used > 0) "
            "WHERE free_ingestions_used > 0"
        )
    )
    bind.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS free_ingestions_used"))
