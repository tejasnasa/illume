"""AuthMiddleware: what it lets through, and what it must not.

The middleware decides public access with `path.startswith(prefix)` over a fixed list.
Prefix matching is a classic bypass surface, so the probing cases below are the point of
this module: they assert that hostile variants sharing a prefix with a public route do
not slip past authentication.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app

pytestmark = pytest.mark.security

# Prefixes the middleware treats as public (app/middleware/auth.py).
PUBLIC_PREFIXES = [
    "/healthz",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
    "/api/v1/auth/github",
    "/api/v1/auth/github/callback",
    "/api/v1/ws",
    "/openapi.json",
]

# A protected endpoint, used to observe whether a request was authenticated.
PROTECTED_PATH = "/api/v1/auth/me"


@pytest.fixture
async def anonymous():
    """Client with no cookie at all."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


def with_cookie(token: str):
    """Client that sends `token` as the session cookie."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"access_token": token},
    )


class TestUnauthenticatedRejection:
    async def test_missing_cookie_is_rejected(self, anonymous):
        response = await anonymous.get(PROTECTED_PATH)

        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param("not-a-jwt", id="garbage"),
            pytest.param("", id="empty"),
            pytest.param("aaa.bbb.ccc", id="three-empty-segments"),
        ],
    )
    async def test_malformed_cookie_is_rejected(self, token):
        async with with_cookie(token) as client:
            response = await client.get(PROTECTED_PATH)

        assert response.status_code == 401
        # A malformed token is distinguished from a missing one in the response body.
        assert response.json()["detail"] in {
            "Not authenticated",
            "Invalid or expired token",
        }

    async def test_token_signed_with_another_key_is_rejected(self):
        from jose import jwt

        forged = jwt.encode({"sub": "someone"}, "wrong-secret", algorithm="HS256")
        async with with_cookie(forged) as client:
            response = await client.get(PROTECTED_PATH)

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired token"


class TestPublicPaths:
    @pytest.mark.parametrize("path", PUBLIC_PREFIXES)
    async def test_public_prefix_is_not_401(self, anonymous, path):
        """Public routes must be reachable without a session."""
        response = await anonymous.get(path)

        assert response.status_code != 401, f"{path} should be public"


class TestPrefixBypassProbing:
    """
    Hostile variants that share a prefix with a public route.

    `startswith` means a public prefix extends to anything appended to it. Some of these
    cannot reach a real handler (there is no route registered), so a 404 is an acceptable
    outcome -- what must never happen is a 2xx, which would mean the middleware waved the
    request through and some handler served it.

    Note `/api/v1/auth/logout` is itself public, so appending to it is not a bypass in the
    sense the others are; it is included to pin the observed behaviour rather than to
    assert a defence.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/auth/loginXXX",
            "/api/v1/auth/register/../me",
            "/api/v1/wsadmin",
            "/api/v1/ws/ingest/not-a-uuid",
            "/openapi.json.bak",
            "/healthz/../api/v1/auth/me",
        ],
    )
    async def test_hostile_variant_never_returns_success(self, anonymous, path):
        response = await anonymous.get(path)

        assert not (200 <= response.status_code < 300), (
            f"{path} returned {response.status_code}; a public prefix must not extend "
            f"to arbitrary suffixes"
        )

    async def test_case_variant_of_public_prefix_is_not_public(self, anonymous):
        """Paths are case-sensitive, so /HEALTHZ is not /healthz."""
        response = await anonymous.get("/HEALTHZ")

        assert response.status_code == 401

    async def test_percent_encoded_slash_does_not_bypass(self, anonymous):
        """%2F must not be decoded into a path separator that shifts the prefix match."""
        response = await anonymous.get("/api/v1/auth%2Flogin")

        assert response.status_code != 200


class TestAuthenticatedRequests:
    async def test_github_linked_user_passes_the_middleware(self, client, db_session):
        """
        A valid cookie passes the middleware. `/me` then resolves the user through the
        auth dependency, so a 200 proves `request.state.user_id` was populated and
        handed on.

        Uses the `client` fixture, not a bare AsyncClient: `/me` reads the database, and
        the direct-insert factory lives inside the test's rolled-back transaction. Only
        the dependency-overridden client sees those rows.

        The user is GitHub-linked because `/me` cannot currently serialize one that is
        not -- see `test_me_serializes_user_without_github_link`.
        """
        from tests.factories import make_user

        user = await make_user(
            db_session,
            github_id="12345",
            github_access_token="gho_token",
            avatar_url="https://avatars.githubusercontent.com/u/1",
        )
        client.cookies.set("access_token", create_access_token(subject=str(user.id)))

        response = await client.get(PROTECTED_PATH)

        assert response.status_code == 200
        assert response.json()["email"] == user.email


class TestMeResponse:
    async def test_me_serializes_user_without_github_link(self, client, db_session):
        """
        `/me` must work for a user who registered by email and never linked GitHub.

        The GitHub columns are nullable, and the response model used to declare them as
        required strings, so serializing such a user raised and the endpoint returned a
        500.
        """
        from tests.factories import make_user

        user = await make_user(db_session)
        client.cookies.set("access_token", create_access_token(subject=str(user.id)))

        response = await client.get(PROTECTED_PATH)

        assert response.status_code == 200
        body = response.json()
        assert body["avatar_url"] is None
        assert body["github_id"] is None

    async def test_me_does_not_return_the_github_token(self, client, db_session):
        """
        The raw OAuth token must never reach the browser.

        It is only needed server-side, for cloning, so it is absent from the response
        model entirely rather than merely nulled for unlinked users.
        """
        from tests.factories import make_user

        user = await make_user(
            db_session,
            github_id="12345",
            github_access_token="gho_secret_token",
            avatar_url="https://avatars.githubusercontent.com/u/1",
        )
        client.cookies.set("access_token", create_access_token(subject=str(user.id)))

        response = await client.get(PROTECTED_PATH)

        assert response.status_code == 200
        assert "github_access_token" not in response.json()
        assert "gho_secret_token" not in response.text

    async def test_expired_token_is_rejected(self):
        from datetime import timedelta

        token = create_access_token(
            subject="00000000-0000-0000-0000-000000000000",
            expires_delta=timedelta(seconds=-1),
        )
        async with with_cookie(token) as client:
            response = await client.get(PROTECTED_PATH)

        assert response.status_code == 401

    async def test_cors_preflight_from_frontend_origin_is_allowed(self, anonymous):
        response = await anonymous.options(
            PROTECTED_PATH,
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code in {200, 204}
        assert response.headers.get("access-control-allow-origin") == ("http://localhost:3000")
