"""Password hashing and JWT encode/decode.

These are pure functions with no database or network, so they carry the best
value-per-line in the suite. The bcrypt truncation cases are the reason the SHA-256
pre-hash exists; if that pre-hash is ever removed, they fail.
"""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from jose import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.unit


def _b64url(data: dict) -> str:
    """base64url-encode a JSON object without padding, as JWT specifies."""
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _handcrafted_token(header: dict, claims: dict, signature: str = "") -> str:
    """Assemble a JWT by hand, bypassing any library's signing rules."""
    return f"{_b64url(header)}.{_b64url(claims)}.{signature}"


class TestPasswordHashing:
    def test_round_trips(self):
        hashed = hash_password("correct horse battery staple")

        assert verify_password("correct horse battery staple", hashed)

    def test_rejects_wrong_password(self):
        hashed = hash_password("correct horse battery staple")

        assert not verify_password("Correct horse battery staple", hashed)

    def test_salts_each_hash(self):
        """The same password must not produce the same digest twice."""
        first = hash_password("same-password")
        second = hash_password("same-password")

        assert first != second
        assert verify_password("same-password", first)
        assert verify_password("same-password", second)

    @pytest.mark.parametrize(
        "password",
        [
            "🔐🗝️ passphrase with emoji",
            "пароль-на-кириллице",
            "密码密码密码密码",
            "a" * 1000,
        ],
        ids=["emoji", "cyrillic", "cjk", "1000-chars"],
    )
    def test_handles_long_and_non_ascii_passwords(self, password):
        """
        bcrypt silently truncates at 72 bytes, so without the SHA-256 pre-hash two
        passwords sharing a 72-byte prefix would be interchangeable. The 1000-character
        case and the multi-byte scripts both exceed that limit once encoded.
        """
        hashed = hash_password(password)

        assert verify_password(password, hashed)

    def test_long_passwords_differing_after_byte_72_are_distinct(self):
        """The specific failure the pre-hash exists to prevent."""
        prefix = "a" * 72
        first = hash_password(prefix + "XXXX")
        second = hash_password(prefix + "YYYY")

        assert not verify_password(prefix + "YYYY", first)
        assert not verify_password(prefix + "XXXX", second)

    def test_empty_password_is_still_hashed(self):
        """Not a policy statement -- registration enforces a minimum length separately."""
        hashed = hash_password("")

        assert verify_password("", hashed)
        assert not verify_password("non-empty", hashed)


class TestAccessTokens:
    def test_encodes_subject(self):
        token = create_access_token(subject="user-123")

        assert decode_access_token(token) == "user-123"

    def test_honours_custom_expiry(self):
        with freeze_time("2026-01-01 12:00:00"):
            token = create_access_token(subject="user-123", expires_delta=timedelta(minutes=5))

            claims = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            assert datetime.fromtimestamp(claims["exp"], tz=UTC) == (
                datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
            )

    def test_default_expiry_comes_from_settings(self):
        with freeze_time("2026-01-01 12:00:00"):
            token = create_access_token(subject="user-123")

            claims = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            expected = datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
            assert datetime.fromtimestamp(claims["exp"], tz=UTC) == expected

    def test_expires(self):
        with freeze_time("2026-01-01 12:00:00") as frozen:
            token = create_access_token(subject="user-123", expires_delta=timedelta(minutes=5))

            assert decode_access_token(token) == "user-123"

            frozen.tick(timedelta(minutes=6))
            assert decode_access_token(token) is None


class TestDecodeRejection:
    """
    Every rejection path returns None rather than raising. Callers treat a falsy return
    as unauthenticated, so an exception here would surface as a 500 on a bad cookie.
    """

    def test_rejects_empty_string(self):
        assert decode_access_token("") is None

    def test_rejects_garbage(self):
        assert decode_access_token("not-a-jwt") is None

    def test_rejects_token_signed_with_another_key(self):
        forged = jwt.encode({"sub": "attacker"}, "a-different-secret", algorithm="HS256")

        assert decode_access_token(forged) is None

    def test_rejects_tampered_payload(self):
        token = create_access_token(subject="user-123")
        header, payload, signature = token.split(".")
        # Swap the subject, keep the original signature.
        tampered_payload = jwt.encode({"sub": "someone-else"}, "x", algorithm="HS256")
        tampered = f"{header}.{tampered_payload.split('.')[1]}.{signature}"

        assert decode_access_token(tampered) is None

    def test_rejects_alg_none(self):
        """
        The classic JWT bypass: claim `alg: none` and drop the signature.

        python-jose refuses to *encode* with `alg: none`, so the token is assembled by
        hand the way an attacker would -- base64url header and claims, empty signature.
        Decoding must reject it because algorithms are pinned to HS256.
        """
        unsigned = _handcrafted_token({"alg": "none", "typ": "JWT"}, {"sub": "attacker"})

        assert decode_access_token(unsigned) is None

    def test_rejects_hs256_algorithm_confusion_against_empty_key(self):
        """A token signed with an empty key must not validate against the real one."""
        forged = jwt.encode({"sub": "attacker"}, "", algorithm="HS256")

        assert decode_access_token(forged) is None

    def test_rejects_missing_subject(self):
        """A structurally valid, correctly signed token with no subject is not a session."""
        token = jwt.encode(
            {"exp": datetime.now(UTC) + timedelta(hours=1)},
            settings.SECRET_KEY,
            algorithm="HS256",
        )

        assert decode_access_token(token) is None
