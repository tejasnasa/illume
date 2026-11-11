"""drop agent_runs.verification

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the column that held a run's verification result.

    Nothing writes or reads it any more, so the column holds only old values
    that no code interprets.
    """
    op.drop_column("agent_runs", "verification")


def downgrade() -> None:
    """Add the column back, nullable and empty, as it was created."""
    op.add_column(
        "agent_runs",
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
