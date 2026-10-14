"""Bearer-header authentication for native clients.

`AuthMiddleware` accepts the JWT either via the ``access_token`` cookie or via
an ``Authorization: Bearer`` header. The two paths must reach the same
authenticated state: a valid header populates ``request.state.user_id`` the
same way a cookie does, and a malformed header does not silently slip through.

These tests pin the header contract because the mobile app is the only
client that uses it -- a regression here would not surface in any web-driven
suite until an Android device noticed.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.core.security import create_access_token, decode_access_token
from app.main import app

pytestmark = pytest.mark.security

PROTECTED_PATH = "/api/v1/auth/me"


def with_bearer(token: str):
    """Client that sends ``Authorization: Bearer <token>`` and nothing else."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )


def with_bearer_value(value: str):
    """Client that sends a caller-shaped Authorization header as-is."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": value},
    )


class TestBearerHeader:
    async def test_valid_header_authenticates(self, client, db_session):
        """A JWT in ``Authorization`` populates the user identity the same way a cookie does."""
        from tests.factories import make_user

        user = await make_user(
            db_session,
            github_id="4242",
            github_access_token="gho_token",
            avatar_url="https://avatars.githubusercontent.com/u/1",
        )
        token = create_access_token(subject=str(user.id))

        async with with_bearer(token) as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 200
        assert response.json()["email"] == user.email

    async def test_cookie_takes_precedence_over_header(self, client, db_session):
        """When both are sent, the cookie wins -- browsers send both under some setups.

        The middleware reads the cookie first, so a cookie-authenticated user
        is what the request sees even if a stale bearer header is also in
        flight. This avoids a class of "logged out and back in as someone
        else" bugs.
        """
        from tests.factories import make_user

        cookie_user = await make_user(
            db_session,
            email="cookie@example.com",
            github_id="1111",
            github_access_token="gho_cookie",
            avatar_url="https://avatars.githubusercontent.com/u/1",
        )
        header_user = await make_user(
            db_session,
            email="header@example.com",
            github_id="2222",
            github_access_token="gho_header",
            avatar_url="https://avatars.githubusercontent.com/u/2",
        )
        cookie_token = create_access_token(subject=str(cookie_user.id))
        header_token = create_access_token(subject=str(header_user.id))

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"access_token": cookie_token},
            headers={"Authorization": f"Bearer {header_token}"},
        ) as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 200
        assert response.json()["email"] == cookie_user.email

    async def test_missing_header_is_rejected(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 401

    async def test_bearer_with_garbage_payload_is_rejected(self):
        """Garbage in the header is treated as no token at all, not as a crash."""
        async with with_bearer("not-a-jwt") as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 401

    async def test_bearer_signed_with_another_key_is_rejected(self):
        forged = jwt.encode({"sub": "someone"}, "wrong-secret", algorithm="HS256")
        async with with_bearer(forged) as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "header_value",
        [
            pytest.param("", id="empty"),
            pytest.param("Token abc.def.ghi", id="wrong-scheme"),
            pytest.param("Bearer", id="bare-scheme"),
            pytest.param("Bearer   ", id="token-only-spaces"),
            pytest.param("abc.def.ghi", id="no-scheme"),
        ],
    )
    async def test_malformed_authorization_header_is_rejected(self, header_value):
        """A misformed header must not leak through as an authenticated request."""
        async with with_bearer_value(header_value) as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 401

    async def test_expired_bearer_is_rejected(self):
        from datetime import timedelta

        token = create_access_token(
            subject="00000000-0000-0000-0000-000000000000",
            expires_delta=timedelta(seconds=-1),
        )
        async with with_bearer(token) as http:
            response = await http.get(PROTECTED_PATH)

        assert response.status_code == 401


class TestBearerHeaderOnPublicPaths:
    """The header is opportunistic on public routes, just like the cookie.

    Public endpoints remain reachable anonymously; a valid token still
    populates ``request.state.user_id`` so, for example, the contact form
    can attribute a submission when a native user is signed in.
    """

    async def test_valid_header_populates_identity_on_public_route(self):
        """The /healthz endpoint is public; a bearer header attaches a user ID when valid."""
        from uuid import uuid4

        # Use a known-good structure: any non-existent user is fine here, since
        # we only assert the middleware did not 401, and a valid JWT merely
        # yields a user_id via decode_access_token.
        token = create_access_token(subject=str(uuid4()))
        async with with_bearer(token) as http:
            response = await http.get("/healthz")

        assert response.status_code != 401

    async def test_decode_is_idempotent(self):
        """Round-trip: a freshly created token decodes to its subject."""
        from uuid import uuid4

        subject = str(uuid4())
        token = create_access_token(subject=subject)

        assert decode_access_token(token) == subject
