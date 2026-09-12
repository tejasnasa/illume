"""drop global commit hash uniqueness

Revision ID: e934fbe8247e
Revises: b4e7be529e5b
Create Date: 2026-09-12 13:32:56.149197

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e934fbe8247e'
down_revision: Union[str, Sequence[str], None] = 'b4e7be529e5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `e5f221c31fc2` had already added `uq_commit_repo_hash` when `570a9dabb547`
    # created `commits_hash_key` on the same column, so the global constraint was
    # redundant from the moment it existed and was never dropped.
    #
    # It is not merely redundant. `git_analyzer._bulk_insert_commits` writes with
    # `ON CONFLICT (repository_id, hash) DO NOTHING`, and `ON CONFLICT` only covers the
    # index it names -- so a conflict on the global constraint propagates out of
    # `analyze_git_history` and fails the entire ingestion, on the last stage of a long
    # pipeline that has already cloned, parsed, and scored.
    #
    # Commit hashes are content-addressed, so two repositories share one whenever they
    # share history: a fork and its upstream, a vendored library, or the same repository
    # ingested twice under two records. None of those is an error.
    #
    # This is a strict relaxation -- no existing row can violate the looser constraint --
    # so it cannot fail on existing data.
    op.drop_constraint("commits_hash_key", "commits", type_="unique")


def downgrade() -> None:
    """Downgrade schema."""
    # Re-imposing the constraint fails on any database that holds the same hash under two
    # repositories, which is exactly the state the upgrade permits. Failing is correct
    # here, but a bare IntegrityError would not say why, so the count is checked first.
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "  SELECT hash FROM commits GROUP BY hash HAVING count(*) > 1"
            ") AS duplicated"
        )
    ).scalar_one()

    if duplicates:
        raise RuntimeError(
            f"Refusing to downgrade: {duplicates} commit hash(es) appear under more than "
            "one repository, and the constraint being restored would reject them. "
            "Inspect with: SELECT hash, count(*) FROM commits GROUP BY hash "
            "HAVING count(*) > 1;"
        )

    op.create_unique_constraint("commits_hash_key", "commits", ["hash"])
