"""add byok and free tier

Revision ID: c3d4e5f6a7b8
Revises: 5d6e7f8a01b2
Create Date: 2026-09-26 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "5d6e7f8a01b2"
branch_labels: str | None = None
depends_on: str | None = None


# --- Backfill SQL ----------------------------------------------------------
#
# Module-level constants so the integration test in
# ``tests/migrations/test_migrate.py`` can execute the exact statement the
# migration runs -- a copy in the test would drift the first time someone
# rewrites the migration but forgets to update the test, and the drift would
# never surface because both sides pass independently.
#
# The second ``UPDATE`` is **not** restored by :func:`downgrade` -- it is a
# deliberate operational change that lives alongside the schema.

MARK_USERS_WITH_REPOS_AS_FREE_INGEST_USED = """
    UPDATE users
    SET free_ingest_used = true
    WHERE EXISTS (SELECT 1 FROM repositories r WHERE r.user_id = users.id)
"""

CLEAR_AUTO_UPDATE_FOR_KEYLESS_OWNERS = """
    UPDATE repositories
    SET auto_update_enabled = false, next_sync_at = NULL
    WHERE user_id IN (SELECT id FROM users WHERE ai_api_key IS NULL)
"""


def upgrade() -> None:
    """
    Add the BYOK credential columns and free-tier counters to ``users``.

    Six columns land on ``users``: four for the user's stored key
    (``ai_provider``, ``ai_api_key``, ``ai_model``, ``ai_key_validated_at``)
    and two counters for the free-tier allowance (``free_ingest_used``,
    ``free_chat_messages_used``). Every BYOK column is nullable: a user with
    no key is the free-tier case, not a malformed row. The counters carry
    ``server_default=text(...)`` so a row inserted via raw SQL -- the reingest
    rebuild path -- still lands in a usable state, matching the pattern in
    ``5d6e7f8a01b2_add_auto_update_fields``.

    Idempotency: every ``ADD COLUMN`` is ``IF NOT EXISTS`` so a re-run against
    a database left half-upgraded by an interrupted run picks up where it
    left off rather than raising -- the same property the prior migration's
    raw ``ALTER TABLE`` statements rely on.

    Backfill follows the column adds and runs in the same transaction so a
    single ``upgrade head`` lands the schema and the operational state:

    * ``free_ingest_used = true`` for every user who already owns at least
      one ``Repository``. Existing accounts have already "spent" their free
      ingestion by virtue of having a repository, so the backfill is the
      honest reflection of state.
    * ``repositories.auto_update_enabled = false`` and
      ``repositories.next_sync_at = NULL`` for every repository owned by a
      keyless user. Auto-update runs on the server key, and the operator's
      free-tier key does not pay for existing accounts at deploy time.

    The second ``UPDATE`` is **not** restored by :func:`downgrade`. A
    downgrade re-creates the columns; it does not reverse a deliberate
    business decision to stop paying for already-ingested repos.
    """
    bind = op.get_bind()

    # --- users columns ------------------------------------------------------
    #
    # Raw ``ALTER TABLE`` rather than ``op.add_column`` because the latter
    # raises on a column that already exists, with no parameter for the
    # idempotent form -- matching ``5d6e7f8a01b2_add_auto_update_fields``.
    add_column_statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_provider VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_api_key VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_model VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_key_validated_at TIMESTAMP WITH TIME ZONE",
        (
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS free_ingest_used BOOLEAN DEFAULT false NOT NULL"
        ),
        (
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS free_chat_messages_used INTEGER DEFAULT 0 NOT NULL"
        ),
    ]
    for stmt in add_column_statements:
        bind.execute(sa.text(stmt))

    # --- backfill: existing users have spent their free ingestion -----------
    #
    # A user with at least one repository has demonstrably ingested at least
    # once. Marking them as having used the free ingestion means a fresh
    # deployment does not silently grant every legacy account an extra
    # one-shot. The ``EXISTS`` is correlated to the ``users.id`` and uses
    # ``r.user_id`` -- the join is on the index ``ix_repositories_user_id``
    # (added in ``2ffeeb4ce948_add_more_cascade_on_delete``), so this is a
    # single index scan rather than a hash aggregate.
    bind.execute(sa.text(MARK_USERS_WITH_REPOS_AS_FREE_INGEST_USED))

    # --- backfill: keyless users stop getting free auto-update --------------
    #
    # A user with no stored key (``ai_api_key IS NULL``) has no way to pay
    # for an auto-update cycle; the operator's free-tier key cannot be
    # expected to subsidise every legacy repository indefinitely. Flipping
    # ``auto_update_enabled`` to ``false`` and clearing ``next_sync_at``
    # removes them from the sweep's claim predicate (which requires
    # ``auto_update_enabled`` to be ``true``) without changing any other
    # column. Existing artefacts survive; the user can re-enable auto-update
    # in the settings screen once they have stored a key.
    bind.execute(sa.text(CLEAR_AUTO_UPDATE_FOR_KEYLESS_OWNERS))


def downgrade() -> None:
    """
    Drop the columns added by :func:`upgrade`.

    The auto-update and free-ingest backfills are **not** reversed -- they
    represent a deliberate business decision (existing accounts have used
    their free allowance, and the server key no longer pays for them). A
    downgrade re-creates the schema but leaves the row state alone; restoring
    the old behaviour would require re-running the prior migration.
    """
    op.drop_column("users", "free_chat_messages_used")
    op.drop_column("users", "free_ingest_used")
    op.drop_column("users", "ai_key_validated_at")
    op.drop_column("users", "ai_model")
    op.drop_column("users", "ai_api_key")
    op.drop_column("users", "ai_provider")
