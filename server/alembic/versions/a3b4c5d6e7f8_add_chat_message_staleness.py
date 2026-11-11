"""add chat_messages staleness columns

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-11 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add what is needed to tell when an answer's cited files have changed.

    ``answered_commit_sha`` and ``cited_paths`` are written with the answer;
    the ``stale_*`` columns are written by a later sync. All are nullable, so
    existing messages simply never become stale.
    """
    op.add_column("chat_messages", sa.Column("answered_commit_sha", sa.String(), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column("cited_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("chat_messages", sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column("stale_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("chat_messages", sa.Column("stale_commit_sha", sa.String(), nullable=True))


def downgrade() -> None:
    """Drop the staleness columns."""
    op.drop_column("chat_messages", "stale_commit_sha")
    op.drop_column("chat_messages", "stale_paths")
    op.drop_column("chat_messages", "stale_at")
    op.drop_column("chat_messages", "cited_paths")
    op.drop_column("chat_messages", "answered_commit_sha")
