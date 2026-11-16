"""The MCP endpoint is mounted, reachable at exactly ``/mcp``, and guarded at the transport.

Protocol checks drive an SDK client through the ``mcp_client`` fixture. The
checks below the protocol (redirects, ``Host`` and ``Origin``) post raw JSON-RPC.
Every request here carries a valid token, so what is proved is the transport's own
refusal, not the bearer check (``test_auth.py`` covers that). The last group runs
against the real API app, to prove opening ``/mcp`` to cookie-less callers opened
nothing else.
"""

from __future__ import annotations

import json

import pytest
from mcp_types.version import LATEST_HANDSHAKE_VERSION, MODERN_PROTOCOL_VERSIONS

from app.core.config import settings
from app.mcp.server import SERVER_NAME

pytestmark = pytest.mark.integration

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def sse_messages(body: str) -> list[dict]:
    """The JSON-RPC messages carried by an SSE response body."""
    return [
        json.loads(line.removeprefix("data:").strip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


async def initialize(mcp_http, auth_headers, path: str = "/mcp", **headers: str):
    return await mcp_http.post(
        path, headers={**HEADERS, **auth_headers, **headers}, json=INITIALIZE
    )


class TestProtocol:
    async def test_a_client_completes_initialize_and_sees_the_server(self, mcp_client):
        assert mcp_client.protocol_version == LATEST_HANDSHAKE_VERSION
        assert mcp_client.server_info.name == SERVER_NAME
        assert mcp_client.server_capabilities.tools is not None

    async def test_an_unknown_tool_is_an_error_result(self, mcp_client):
        result = await mcp_client.call_tool("no_such_tool", {})

        assert result.is_error is True
        assert "Unknown tool" in result.content[0].text

    async def test_a_client_on_the_newest_revision_is_served_too(self, mcp_connect, auth_headers):
        async with mcp_connect(mode="auto", **auth_headers) as client:
            version = client.protocol_version
            tools = (await client.list_tools()).tools
            result = await client.call_tool("whoami", {})

        assert version in MODERN_PROTOCOL_VERSIONS
        assert "whoami" in [tool.name for tool in tools]
        assert result.is_error is not True


class TestBarePath:
    async def test_post_without_a_trailing_slash_answers_in_place(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, "/mcp")

        assert response.status_code == 200
        assert "location" not in response.headers
        assert response.headers["content-type"].startswith("text/event-stream")
        [message] = sse_messages(response.text)
        assert message["result"]["serverInfo"]["name"] == SERVER_NAME

    async def test_the_slashed_path_is_served_too(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, "/mcp/")

        assert response.status_code == 200

    async def test_the_query_string_survives_the_rewrite(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, "/mcp?probe=1")

        assert response.status_code == 200

    async def test_a_path_below_the_endpoint_is_not_served(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, "/mcp/other")

        assert response.status_code == 404


class TestTransportSecurity:
    async def test_the_test_host_is_accepted(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, host="testserver")

        assert response.status_code == 200

    async def test_the_api_host_is_accepted(self, mcp_http, auth_headers):
        # `GITHUB_REDIRECT_URL` points at the API, here on localhost:8000.
        response = await initialize(mcp_http, auth_headers, host="localhost:8000")

        assert response.status_code == 200

    @pytest.mark.parametrize("host", ["evil.example.com", "localhost.evil.example.com:80"])
    async def test_a_foreign_host_is_refused(self, mcp_http, auth_headers, host):
        response = await initialize(mcp_http, auth_headers, host=host)

        assert response.status_code == 421

    async def test_a_request_without_an_origin_is_accepted(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers)

        assert "origin" not in response.request.headers
        assert response.status_code == 200

    async def test_the_frontend_origin_is_accepted(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, origin=settings.FRONTEND_URL)

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "origin", ["https://evil.example.com", "http://localhost.evil.example.com"]
    )
    async def test_a_foreign_browser_origin_is_refused(self, mcp_http, auth_headers, origin):
        response = await initialize(mcp_http, auth_headers, origin=origin)

        assert response.status_code == 403

    async def test_a_post_that_is_not_json_is_refused(self, mcp_http, auth_headers):
        response = await mcp_http.post(
            "/mcp", headers={**HEADERS, **auth_headers, "content-type": "text/plain"}, content="hi"
        )

        assert response.status_code == 400


class TestTheRestOfTheApiIsStillGuarded:
    async def test_a_repository_route_without_a_cookie_is_401(self, client):
        response = await client.get("/api/v1/repository")

        assert response.status_code == 401

    async def test_a_repository_sub_route_without_a_cookie_is_401(self, client):
        response = await client.get("/api/v1/repository/1/graph")

        assert response.status_code == 401

    @pytest.mark.parametrize("path", ["/mcpx", "/mcpx/", "/mcp-admin", "/mcp.json", "/MCP"])
    async def test_a_path_that_only_shares_the_prefix_is_not_public(self, client, path):
        response = await client.post(path, headers=HEADERS, json=INITIALIZE)

        assert response.status_code == 401
