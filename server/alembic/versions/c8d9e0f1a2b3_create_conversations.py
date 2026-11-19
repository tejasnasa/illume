"""create conversations

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TITLE_LIMIT = 60
"""Longest generated title, ellipsis included."""


def upgrade() -> None:
    """
    Add conversations and attach every chat message to one.

    Each (user, repository) pair that already has messages gets one conversation,
    titled from its earliest question (whitespace collapsed, cut to 60 characters
    with an ellipsis) and dated from its first and last message. The new column is
    added nullable, filled, then made NOT NULL.

    Idempotency: the DDL is written so a re-run is a no-op, because the test
    database is migrated once per xdist worker and several workers can reach an
    un-migrated database at the same time.
    """
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_conversations_user_repo_updated "
            "ON conversations (user_id, repository_id, updated_at DESC)"
        )
    )

    bind.execute(
        sa.text(
            """
            ALTER TABLE chat_messages
            ADD COLUMN IF NOT EXISTS conversation_id UUID
            REFERENCES conversations(id) ON DELETE CASCADE
            """
        )
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO conversations (id, user_id, repository_id, title, created_at, updated_at)
            SELECT
                gen_random_uuid(),
                grouped.user_id,
                grouped.repository_id,
                CASE
                    WHEN grouped.collapsed = '' THEN 'New chat'
                    WHEN char_length(grouped.collapsed) > :limit
                        THEN rtrim(left(grouped.collapsed, :limit - 1)) || '…'
                    ELSE grouped.collapsed
                END,
                grouped.first_at,
                grouped.last_at
            FROM (
                SELECT
                    user_id,
                    repository_id,
                    min(created_at) AS first_at,
                    max(created_at) AS last_at,
                    btrim(regexp_replace(
                        (array_agg(question ORDER BY created_at, id))[1], '[[:space:]]+', ' ', 'g'
                    )) AS collapsed
                FROM chat_messages
                WHERE conversation_id IS NULL
                GROUP BY user_id, repository_id
            ) AS grouped
            """
        ),
        {"limit": TITLE_LIMIT},
    )
    bind.execute(
        sa.text(
            """
            UPDATE chat_messages AS m
            SET conversation_id = c.id
            FROM conversations AS c
            WHERE m.conversation_id IS NULL
              AND c.user_id = m.user_id
              AND c.repository_id = m.repository_id
            """
        )
    )

    bind.execute(sa.text("ALTER TABLE chat_messages ALTER COLUMN conversation_id SET NOT NULL"))
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_conversation_id "
            "ON chat_messages (conversation_id)"
        )
    )


def downgrade() -> None:
    """Detach the messages and drop the table; the messages themselves are kept."""
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_column("chat_messages", "conversation_id")
    op.drop_table("conversations")
