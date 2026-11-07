"""create agent_runs and agent_steps, link chat turns to runs

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the run record, its steps, and the link from a chat turn to its run.

    Everything is additive. The two tables are new, so creating them touches no
    existing data. ``chat_messages.agent_run_id`` is a nullable column with no
    default, which Postgres adds without rewriting the table, and its foreign key
    is added ``NOT VALID`` and then validated: validation takes only a
    ``SHARE UPDATE EXCLUSIVE`` lock, so reads and writes on ``chat_messages``
    continue while existing rows (all ``NULL``) are checked. ``agent_runs`` and
    ``chat_messages`` reference each other; the column is added after both exist.

    Every statement is written so a re-run is a no-op: the test database is
    migrated once per xdist worker, and workers can reach it together.
    """
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                repository_id UUID NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
                chat_message_id UUID REFERENCES chat_messages (id) ON DELETE SET NULL,
                question TEXT NOT NULL,
                standalone_question TEXT,
                preset TEXT NOT NULL,
                config JSONB NOT NULL,
                config_hash CHAR(64) NOT NULL,
                prompt_version TEXT,
                model TEXT,
                decider TEXT,
                ingested_commit_sha TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                stop_reason TEXT,
                answer TEXT,
                citations JSONB,
                verification JSONB,
                usage JSONB,
                tool_calls INTEGER,
                iterations INTEGER,
                latency_ms INTEGER,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ
            )
            """
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_user_repo_created "
            "ON agent_runs (user_id, repository_id, created_at)"
        )
    )

    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS agent_steps (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_id UUID NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                worker_id TEXT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                payload JSONB NOT NULL,
                tokens_in INTEGER,
                tokens_out INTEGER,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_agent_steps_run_seq UNIQUE (run_id, seq)
            )
            """
        )
    )
    # The retention task deletes by age; the unique constraint already serves lookups by run.
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_steps_created_at ON agent_steps (created_at)"
        )
    )

    bind.execute(
        sa.text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS agent_run_id UUID")
    )
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_chat_messages_agent_run_id'
                ) THEN
                    ALTER TABLE chat_messages
                        ADD CONSTRAINT fk_chat_messages_agent_run_id
                        FOREIGN KEY (agent_run_id) REFERENCES agent_runs (id)
                        ON DELETE SET NULL NOT VALID;
                    ALTER TABLE chat_messages VALIDATE CONSTRAINT fk_chat_messages_agent_run_id;
                END IF;
            END
            $$
            """
        )
    )


def downgrade() -> None:
    """Remove the link, then the two tables; nothing outside them depends on them."""
    op.execute(
        "ALTER TABLE chat_messages DROP CONSTRAINT IF EXISTS fk_chat_messages_agent_run_id"
    )
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS agent_run_id")
    op.execute("DROP INDEX IF EXISTS ix_agent_steps_created_at")
    op.execute("DROP TABLE IF EXISTS agent_steps")
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_user_repo_created")
    op.execute("DROP TABLE IF EXISTS agent_runs")
