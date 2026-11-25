"""Stored credentials are AES-GCM envelopes bound to their column and openable after rotation."""

import pytest

from app.core.config import settings
from app.core.crypto import (
    ENVELOPE_PREFIX,
    CredentialDecryptionError,
    credential_aad,
    decrypt_secret,
    encrypt_secret,
)
from app.models.encrypted import EncryptedString

pytestmark = pytest.mark.unit

SECRET = "sk-live-0123456789abcdef"
AAD = credential_aad("users", "ai_api_key")
OLD_KEY = "an-older-credential-encryption-key-of-enough-length"


def test_an_envelope_round_trips_and_does_not_contain_the_plaintext():
    envelope = encrypt_secret(SECRET, AAD)

    assert envelope.startswith(ENVELOPE_PREFIX)
    assert SECRET not in envelope
    assert decrypt_secret(envelope, AAD) == SECRET


def test_each_encryption_uses_a_fresh_iv():
    assert encrypt_secret(SECRET, AAD) != encrypt_secret(SECRET, AAD)


def test_an_envelope_moved_to_another_column_does_not_decrypt():
    envelope = encrypt_secret(SECRET, AAD)

    with pytest.raises(CredentialDecryptionError):
        decrypt_secret(envelope, credential_aad("users", "github_access_token"))


def test_a_tampered_envelope_does_not_decrypt():
    head, ciphertext = encrypt_secret(SECRET, AAD).rsplit(".", 1)
    flipped = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]

    with pytest.raises(CredentialDecryptionError):
        decrypt_secret(f"{head}.{flipped}", AAD)


@pytest.mark.parametrize(
    "value",
    [SECRET, f"{ENVELOPE_PREFIX}abc", f"{ENVELOPE_PREFIX}a.b.c.d", f"{ENVELOPE_PREFIX}a..."],
)
def test_a_malformed_value_is_refused_without_echoing_it(value):
    with pytest.raises(CredentialDecryptionError) as raised:
        decrypt_secret(value, AAD)

    assert SECRET not in str(raised.value)


def test_a_value_written_with_a_previous_key_still_decrypts_after_rotation(monkeypatch):
    current = settings.CREDENTIAL_ENCRYPTION_KEY
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", OLD_KEY)
    envelope = encrypt_secret(SECRET, AAD)

    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", current)
    with pytest.raises(CredentialDecryptionError):
        decrypt_secret(envelope, AAD)

    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY_PREVIOUS", f"too-short, {OLD_KEY}")
    assert decrypt_secret(envelope, AAD) == SECRET


def test_a_short_key_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "short")

    with pytest.raises(RuntimeError, match="at least 32 characters"):
        encrypt_secret(SECRET, AAD)


class TestEncryptedString:
    column = EncryptedString("users", "ai_api_key")

    def test_writes_an_envelope_and_reads_the_plaintext(self):
        stored = self.column.process_bind_param(SECRET, dialect=None)

        assert stored.startswith(ENVELOPE_PREFIX)
        assert self.column.process_result_value(stored, dialect=None) == SECRET

    def test_null_stays_null(self):
        assert self.column.process_bind_param(None, dialect=None) is None
        assert self.column.process_result_value(None, dialect=None) is None

    def test_an_envelope_is_not_encrypted_twice(self):
        envelope = encrypt_secret(SECRET, AAD)

        assert self.column.process_bind_param(envelope, dialect=None) == envelope

    def test_a_row_from_before_encryption_reads_as_written(self):
        assert self.column.process_result_value(SECRET, dialect=None) == SECRET
