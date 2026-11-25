"""A string column stored as an encrypted envelope.

Encryption happens in the column type, so every reader and writer -- async routes,
Celery tasks, scripts and tests -- gets plaintext in Python and ciphertext in the
database without knowing either exists. Equality comparisons against the column do not
work (each write uses a fresh IV); ``IS NULL`` / ``IS NOT NULL`` do.
"""

import logging

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.crypto import credential_aad, decrypt_secret, encrypt_secret, is_envelope

logger = logging.getLogger(__name__)


class EncryptedString(TypeDecorator):
    """A ``String`` column whose values are encrypted at rest.

    A stored value without the envelope prefix is a row written before encryption,
    returned as-is until the migration that encrypts existing rows has run.
    """

    impl = String
    cache_ok = True

    def __init__(self, table: str, column: str) -> None:
        super().__init__()
        self.table = table
        self.column = column

    @property
    def _aad(self) -> bytes:
        return credential_aad(self.table, self.column)

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None or is_envelope(value):
            return value
        return encrypt_secret(value, self._aad)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        if not is_envelope(value):
            logger.warning("%s.%s holds an unencrypted value", self.table, self.column)
            return value
        return decrypt_secret(value, self._aad)
