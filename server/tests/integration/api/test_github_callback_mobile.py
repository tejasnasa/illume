"""Mobile-specific contract on the GitHub OAuth callback.

Web callers receive a redirect with a session cookie. Native callers go a
different way:

- When the client passes ``state=illume://auth/callback`` (a URL on the
  configured allowlist), the callback redirects to that URL with the token
  bundled into the query string. This is the path a phone uses -- the OAuth
  dance runs in a system browser with no custom headers and no cookie jar.
  Token-in-URL is a known exposure and is documented as accepted for the
  resume build.
- When the client passes ``X-Illume-Client: mobile`` *without* an allowlisted
  state, the callback returns JSON with the token in the body. This is the
  path a server-to-server style call would take.

These tests pin all three contracts so a regression in any one of them would
not surface anywhere else.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.api.v1 import auth as auth_module
from app.core.config import settings
from app.core.security import decode_access_token

pytestmark = pytest.mark.integration

CALLBACK = "/api/v1/auth/github/callback"
GITHUB_LOGIN = "/api/v1/auth/github"


def _install_github_stub(monkeypatch, *, access_token: str = "gho_test_token") -> dict:
    """Replace ``httpx.AsyncClient`` with one that returns stubbed GitHub responses."""
    captured: dict = {}
    real_async_client = httpx.AsyncClient

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            captured.setdefault("requests", []).append(request)
            if request.url.host == "github.com" and request.url.path == "/login/oauth/access_token":
                return httpx.Response(200, json={"access_token": access_token})
            if request.url.host == "api.github.com" and request.url.path == "/user":
                return httpx.Response(
                    200,
                    json={
                        "id": 99887766,
                        "login": "stubuser",
                        "name": "Stub User",
                        "avatar_url": "https://avatars.githubusercontent.com/u/99887766",
                    },
                )
            if request.url.host == "api.github.com" and request.url.path == "/user/emails":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "email": "stub@example.com",
                            "primary": True,
                            "verified": True,
                        }
                    ],
                )
            return httpx.Response(404, json={})

    def _factory(**kwargs):
        kwargs.pop("transport", None)
        return real_async_client(transport=_Transport(), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return captured


@pytest.fixture
def stub_github(monkeypatch):
    captured = _install_github_stub(monkeypatch)
    yield captured


@pytest.fixture
def allowlist_with_deep_link(monkeypatch):
    monkeypatch.setattr(
        auth_module.settings,
        "OAUTH_REDIRECT_ALLOWLIST",
        ["illume://auth/callback"],
    )


@pytest.fixture
def empty_allowlist(monkeypatch):
    monkeypatch.setattr(auth_module.settings, "OAUTH_REDIRECT_ALLOWLIST", [])


class TestDeepLinkRedirect:
    """The natural native flow: allowlist state → redirect to that URL with token in query."""

    async def test_redirects_to_deep_link_with_token(
        self, client, allowlist_with_deep_link, stub_github, db_session
    ):
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code", "state": "illume://auth/callback"},
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        parsed = urlparse(response.headers["location"])
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "illume://auth/callback"
        query = parse_qs(parsed.query)
        assert "access_token" in query
        assert query["token_type"] == ["Bearer"]
        assert query["expires_in"] == [str(settings.MOBILE_TOKEN_EXPIRE_MINUTES * 60)]

    async def test_deep_link_token_decodes_to_a_real_user(
        self, client, allowlist_with_deep_link, stub_github, db_session
    ):
        from sqlalchemy import select

        from app.models.user import User

        response = await client.get(
            CALLBACK,
            params={"code": "valid-code", "state": "illume://auth/callback"},
            follow_redirects=False,
        )
        query = parse_qs(urlparse(response.headers["location"]).query)
        user_id = decode_access_token(query["access_token"][0])
        assert user_id is not None
        result = await db_session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        assert user.email == "stub@example.com"
        assert user.github_access_token == "gho_test_token"

    async def test_deep_link_token_lasts_longer_than_web_session(
        self, client, allowlist_with_deep_link, stub_github
    ):
        """Native sessions outlast the default web expiry so users do not have to re-login weekly"""
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code", "state": "illume://auth/callback"},
            follow_redirects=False,
        )
        query = parse_qs(urlparse(response.headers["location"]).query)
        assert int(query["expires_in"][0]) > settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


class TestDirectMobileJsonContract:
    """Direct callers with ``X-Illume-Client: mobile`` and no allowlisted state get JSON."""

    async def test_returns_json_with_token_in_body(self, client, empty_allowlist, stub_github):
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code"},
            headers={"X-Illume-Client": "mobile"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == settings.MOBILE_TOKEN_EXPIRE_MINUTES * 60

    async def test_token_decodes_to_a_real_user(
        self, client, empty_allowlist, stub_github, db_session
    ):
        from sqlalchemy import select

        from app.models.user import User

        response = await client.get(
            CALLBACK,
            params={"code": "valid-code"},
            headers={"X-Illume-Client": "mobile"},
        )
        body = response.json()

        user_id = decode_access_token(body["access_token"])
        assert user_id is not None
        result = await db_session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        assert user.email == "stub@example.com"
        assert user.github_access_token == "gho_test_token"

    async def test_token_lasts_longer_than_web_session(self, client, empty_allowlist, stub_github):
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code"},
            headers={"X-Illume-Client": "mobile"},
        )
        body = response.json()
        assert body["expires_in"] > settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    async def test_no_session_cookie_on_mobile_response(self, client, empty_allowlist, stub_github):
        """The JSON path does not set a cookie -- the token is in the body only."""
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code"},
            headers={"X-Illume-Client": "mobile"},
        )

        assert "set-cookie" not in {k.lower() for k in response.headers}


class TestWebContractUnchanged:
    """Web callers (no header, no allowlisted state) keep getting redirect+cookie."""

    async def test_returns_a_redirect_to_frontend(self, client, stub_github):
        response = await client.get(CALLBACK, params={"code": "valid-code"})

        assert response.status_code in (302, 307)
        assert response.headers["location"] == settings.FRONTEND_URL

    async def test_response_carries_the_session_cookie(self, client, stub_github):
        response = await client.get(CALLBACK, params={"code": "valid-code"})

        set_cookies = response.headers.get_list("set-cookie")
        assert any(cookie.startswith("access_token=") for cookie in set_cookies), set_cookies

    async def test_web_token_matches_default_expiry(self, client, stub_github):
        """Cookies on the redirect must reflect the configured web expiry."""
        response = await client.get(CALLBACK, params={"code": "valid-code"})

        set_cookies = response.headers.get_list("set-cookie")
        cookie = next(c for c in set_cookies if c.startswith("access_token="))
        assert f"Max-Age={settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}" in cookie

    async def test_body_has_no_token_for_web_caller(self, client, stub_github):
        """A redirect has no body, and the token must never reach the browser."""
        response = await client.get(CALLBACK, params={"code": "valid-code"})

        assert response.content == b""


class TestRedirectAllowlist:
    """The callback only redirects to a deep-link URI when it is on the allowlist."""

    async def test_allowlisted_state_redirects_to_that_uri(
        self, client, allowlist_with_deep_link, stub_github
    ):
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code", "state": "illume://auth/callback"},
            follow_redirects=False,
        )

        assert urlparse(response.headers["location"]).scheme == "illume"

    @pytest.mark.parametrize(
        "evil_uri",
        [
            pytest.param("https://evil.example.com/callback", id="different-host"),
            pytest.param("illume://auth/callback?stolen=1", id="query-added"),
            pytest.param("illume://auth/callback/", id="trailing-slash"),
            pytest.param("ILLUME://AUTH/CALLBACK", id="case-shifted"),
            pytest.param("illume://attacker.example.com/callback", id="subdomain-prefix"),
            pytest.param("//evil.example.com/callback", id="protocol-relative"),
        ],
    )
    async def test_unlisted_state_falls_back_to_frontend(
        self, client, allowlist_with_deep_link, stub_github, evil_uri
    ):
        """Open-redirect defence: a near-miss URI must not pass the allowlist."""
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code", "state": evil_uri},
            follow_redirects=False,
        )

        assert response.headers["location"] == settings.FRONTEND_URL

    async def test_empty_allowlist_ignores_state_param(self, client, empty_allowlist, stub_github):
        """With an empty allowlist, even a benign-looking URI is ignored."""
        response = await client.get(
            CALLBACK,
            params={"code": "valid-code", "state": "illume://auth/callback"},
            follow_redirects=False,
        )

        assert response.headers["location"] == settings.FRONTEND_URL


class TestGithubLoginState:
    """``/github`` echoes ``state`` to GitHub so the callback can recover it verbatim."""

    async def test_state_is_forwarded(self, client):
        """State goes through unchanged; the callback decides whether to honour it."""
        response = await client.get(
            GITHUB_LOGIN,
            params={"state": "illume://auth/callback"},
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers["location"]
        assert "state=" in location
        assert "illume" in location
        assert "auth/callback" in location

    async def test_omitting_state_omits_the_param(self, client):
        """Older callers that do not pass state must still work."""
        response = await client.get(GITHUB_LOGIN, follow_redirects=False)

        assert response.status_code in (302, 307)
        assert "state=" not in response.headers["location"]


class TestNegativeCases:
    """Failure paths that are independent of the mobile/web branch."""

    async def test_github_rejecting_the_code_yields_400(self, client, monkeypatch):
        real_async_client = httpx.AsyncClient

        def _factory(**kwargs):
            kwargs.pop("transport", None)

            class _Transport(httpx.AsyncBaseTransport):
                async def handle_async_request(self, request):
                    if (
                        request.url.host == "github.com"
                        and request.url.path == "/login/oauth/access_token"
                    ):
                        return httpx.Response(200, json={"error": "bad_verification_code"})
                    return httpx.Response(404, json={})

            return real_async_client(transport=_Transport(), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _factory)

        response = await client.get(CALLBACK, params={"code": "bad-code"})

        assert response.status_code == 400
