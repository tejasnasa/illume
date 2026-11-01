"""create push_tokens

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add the table holding the push tokens a user's devices have registered.

    One row is one device. The token is unique across the table rather than
    unique per user: a device keeps its token when the account behind it
    changes, and the second registration has to be able to take the token
    over from the first. The foreign key cascades, so deleting a user takes
    their devices' tokens with it.

    The platform is constrained to the two values the client sends rather
    than stored as a Postgres enum: the set is fixed and tiny, and an enum
    type would need its own migration to widen.

    Idempotency: the DDL is written so a re-run is a no-op. The test
    database is migrated once per xdist worker, and several workers can
    reach an un-migrated database at the same time; a plain ``CREATE TABLE``
    would have one of them fail on "relation already exists" and take the
    whole run with it.
    """
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS push_tokens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token VARCHAR NOT NULL,
                platform VARCHAR(16) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                CONSTRAINT ck_push_tokens_platform CHECK (platform IN ('android', 'ios'))
            )
            """
        )
    )

    # The unique index on the token is what makes a second registration of
    # the same device an update rather than a duplicate row. It is created
    # here rather than as a table constraint so that its name matches the
    # one the model declares.
    bind.execute(
        sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_push_tokens_token ON push_tokens (token)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_push_tokens_user_id ON push_tokens (user_id)")
    )


def downgrade() -> None:
    """Drop the table; the indexes go with it."""
    op.drop_table("push_tokens")
