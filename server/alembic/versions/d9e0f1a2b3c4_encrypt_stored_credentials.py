"""encrypt stored credentials

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-11-25 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.crypto import credential_aad, decrypt_secret, encrypt_secret, is_envelope

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("github_access_token", "ai_api_key")


def _rewrite(bind, convert) -> None:
    """Apply ``convert(column, value)`` to every non-null credential in ``users``."""
    for column in COLUMNS:
        rows = bind.execute(
            sa.text(f"SELECT id, {column} FROM users WHERE {column} IS NOT NULL")
        ).all()
        for user_id, value in rows:
            new = convert(column, value)
            if new != value:
                bind.execute(
                    sa.text(f"UPDATE users SET {column} = :value WHERE id = :id"),
                    {"value": new, "id": user_id},
                )


def upgrade() -> None:
    """
    Encrypt every stored GitHub token and AI key with ``CREDENTIAL_ENCRYPTION_KEY``.

    Idempotency: values that are already envelopes are left alone, so a re-run (or
    several xdist workers migrating the test database at once) is a no-op.
    """

    def encrypt(column: str, value: str) -> str:
        if is_envelope(value):
            return value
        return encrypt_secret(value, credential_aad("users", column))

    _rewrite(op.get_bind(), encrypt)


def downgrade() -> None:
    """Decrypt every stored credential back to plaintext."""

    def decrypt(column: str, value: str) -> str:
        if not is_envelope(value):
            return value
        return decrypt_secret(value, credential_aad("users", column))

    _rewrite(op.get_bind(), decrypt)
