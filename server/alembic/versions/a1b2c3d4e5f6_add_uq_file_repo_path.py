"""add uq_file_repo_path

Revision ID: a1b2c3d4e5f6
Revises: e934fbe8247e
Create Date: 2026-09-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e934fbe8247e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a unique constraint on ``files (repository_id, path)``.

    The parse stage already issues ``DELETE FROM files WHERE repository_id =
    ...`` before each run, so duplicate rows have been masked in single-run
    tests. Concurrent workers -- and any future incremental update path --
    can no longer rely on that: a unique constraint fails them at insert
    rather than silently inflating ``in_degree`` with phantom edges.

    Pre-existing databases may already carry duplicate rows from the old
    delete-or-insert parse path -- in-degree is computed from
    ``Dependency`` edges via file_id, so a phantom row only inflates the
    fan-in/fan-out metrics, not the graph topology. The parse stage's
    ``ON CONFLICT DO NOTHING`` insert this constraint enables will reject
    re-runs until the duplicates are gone. We collapse to one row per
    ``(repository_id, path)`` here so the constraint can be added in the
    same transaction: AST symbols attached to the dropped rows would be
    orphaned, but they were never reachable through a real Dependency
    edge either, so discarding them changes nothing observable.
    """
    bind = op.get_bind()

    # Keep the lowest ctid (the row Postgres inserted first; in practice any
    # survivor will do -- fan-in/fan-out are derived from Dependency edges,
    # not from how many File rows there are). The subquery scopes the
    # delete to existing duplicates only; an empty files table is a no-op.
    bind.execute(
        sa.text(
            """
            DELETE FROM files
            WHERE ctid NOT IN (
                SELECT min(ctid)
                FROM files
                GROUP BY repository_id, path
            )
            """
        )
    )

    op.create_unique_constraint(
        "uq_file_repo_path",
        "files",
        ["repository_id", "path"],
    )


def downgrade() -> None:
    """Drop the constraint. No data restoration -- the duplicates we deleted
    were the duplicates the schema was broken enough to allow; restoring them
    would re-create the original defect."""
    op.drop_constraint("uq_file_repo_path", "files", type_="unique")
