"""Encryption at rest for stored credentials (users' AI keys and GitHub tokens).

A user who saves an API key or links GitHub trusts the server with a credential that
can spend their money or read their code, so the stored value is AES-256-GCM
ciphertext rather than plaintext. The envelope is
``illume1.<keyId>.<ivB64>.<tagB64>.<ctB64>``.

Rules this module keeps:

* the plaintext, the envelope and the derived key are never logged or put in an
  exception message;
* there is no default key: ``CREDENTIAL_ENCRYPTION_KEY`` is a required setting;
* the mode is AEAD with a fresh random 96-bit IV per encryption;
* the associated data names what the value is (``credential:v1:<table>.<column>``),
  so a ciphertext copied into another credential column fails to decrypt.

Rotation needs no bookkeeping: new values are written with the current key, and
decryption tries the current key and then each key in
``CREDENTIAL_ENCRYPTION_KEY_PREVIOUS`` (comma-separated).

The threat model is the realistic incident: a leaked backup or database dump, a
read-only SQL injection, a ``SELECT *`` in a support tool. The running process holds
the key in its environment, so anyone who can read that environment can decrypt every
stored credential. This is not a vault.
"""

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENVELOPE_PREFIX = "illume1."
"""Marks a stored value as an envelope. A value without it is a pre-encryption plaintext."""

MIN_KEY_LENGTH = 32
"""Shortest accepted key setting; ``openssl rand -base64 32`` gives 44 characters."""

_HKDF_SALT = b"illume/credential-encryption/v1"
_HKDF_INFO = b"credential:v1"
_KEY_LENGTH = 32
_IV_LENGTH = 12
_TAG_LENGTH = 16
_KEY_ID_HEX_LENGTH = 8


class CredentialDecryptionError(Exception):
    """A stored credential could not be decrypted with any configured key."""


def credential_aad(table: str, column: str) -> bytes:
    """The associated data that binds a ciphertext to the column it is stored in."""
    return f"credential:v1:{table}.{column}".encode()


def _derive_key(passphrase: str) -> bytes:
    """Derive the 32-byte AES key from a key setting with HKDF-SHA256."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(passphrase.encode())


def _key_id(key: bytes) -> str:
    """A short, non-secret hint of which key wrote an envelope."""
    return hashlib.sha256(key).hexdigest()[:_KEY_ID_HEX_LENGTH]


def _current_key() -> bytes:
    from app.core.config import settings

    passphrase = settings.CREDENTIAL_ENCRYPTION_KEY
    if len(passphrase) < MIN_KEY_LENGTH:
        raise RuntimeError(
            f"CREDENTIAL_ENCRYPTION_KEY must be at least {MIN_KEY_LENGTH} characters."
        )
    return _derive_key(passphrase)


def _candidate_keys() -> list[bytes]:
    """The current key, then each previous key, in that order."""
    from app.core.config import settings

    keys = [_current_key()]
    for raw in settings.CREDENTIAL_ENCRYPTION_KEY_PREVIOUS.split(","):
        passphrase = raw.strip()
        if len(passphrase) >= MIN_KEY_LENGTH:
            keys.append(_derive_key(passphrase))
    return keys


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def is_envelope(value: str) -> bool:
    """Whether a stored value is an encrypted envelope."""
    return value.startswith(ENVELOPE_PREFIX)


def encrypt_secret(plaintext: str, aad: bytes) -> str:
    """Encrypt a credential for storage.

    Args:
        plaintext: The credential. Never logged.
        aad: The binding from :func:`credential_aad`.

    Returns:
        The envelope ``illume1.<keyId>.<ivB64>.<tagB64>.<ctB64>``.
    """
    key = _current_key()
    iv = os.urandom(_IV_LENGTH)
    sealed = AESGCM(key).encrypt(iv, plaintext.encode(), aad)
    ciphertext, tag = sealed[:-_TAG_LENGTH], sealed[-_TAG_LENGTH:]
    return f"{ENVELOPE_PREFIX}{_key_id(key)}.{_b64(iv)}.{_b64(tag)}.{_b64(ciphertext)}"


def decrypt_secret(envelope: str, aad: bytes) -> str:
    """Decrypt a stored envelope back to the credential.

    Args:
        envelope: The stored value.
        aad: The binding the value was encrypted with.

    Returns:
        The credential.

    Raises:
        CredentialDecryptionError: If the envelope is malformed, was written for
            another column, was tampered with, or no configured key opens it.
    """
    if not is_envelope(envelope):
        raise CredentialDecryptionError("Stored credential is not an encrypted envelope.")
    parts = envelope[len(ENVELOPE_PREFIX) :].split(".")
    if len(parts) != 4 or not all(parts):
        raise CredentialDecryptionError("Stored credential envelope is malformed.")
    try:
        iv, tag, ciphertext = (base64.b64decode(part, validate=True) for part in parts[1:])
    except ValueError:
        raise CredentialDecryptionError("Stored credential envelope is malformed.") from None
    if len(iv) != _IV_LENGTH or len(tag) != _TAG_LENGTH:
        raise CredentialDecryptionError("Stored credential envelope is malformed.")
    for key in _candidate_keys():
        try:
            return AESGCM(key).decrypt(iv, ciphertext + tag, aad).decode()
        except InvalidTag:
            # A wrong key and a tampered envelope fail the same way; try the next key.
            continue
    raise CredentialDecryptionError("Stored credential could not be decrypted.")
