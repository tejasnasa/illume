"""The request body limit and the feature switch on ``/mcp``.

Both are refused by the wrapper in front of the transport, so the checks are raw HTTP:
what is asserted is the status the wrapper produced, before any JSON-RPC was read.
"""

from __future__ import annotations

import pytest

from app.mcp import server as mcp_server
from app.mcp.server import MCP_MAX_BODY_BYTES
from tests.integration.mcp.test_mount import HEADERS, INITIALIZE, initialize

pytestmark = pytest.mark.integration

CHUNK = 256 * 1024


async def chunks(total: int):
    """A body of ``total`` bytes streamed in pieces, so the request carries no length."""
    sent = 0
    while sent < total:
        piece = min(CHUNK, total - sent)
        sent += piece
        yield b" " * piece


class TestBodyLimit:
    def test_the_limit_is_one_mebibyte(self):
        assert MCP_MAX_BODY_BYTES == 1_048_576

    async def test_a_normal_request_still_works(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers)

        assert response.status_code == 200

    async def test_a_declared_length_over_the_limit_is_413(self, mcp_http, auth_headers):
        response = await mcp_http.post(
            "/mcp",
            headers={**HEADERS, **auth_headers},
            content=b" " * (MCP_MAX_BODY_BYTES + 1),
        )

        assert response.status_code == 413

    async def test_a_chunked_body_over_the_limit_is_413(self, mcp_http, auth_headers):
        request = mcp_http.build_request(
            "POST",
            "/mcp",
            headers={**HEADERS, **auth_headers},
            content=chunks(MCP_MAX_BODY_BYTES + 1),
        )
        assert "content-length" not in request.headers

        response = await mcp_http.send(request)

        assert response.status_code == 413

    async def test_a_chunked_body_far_over_the_limit_is_413(self, mcp_http, auth_headers):
        response = await mcp_http.post(
            "/mcp",
            headers={**HEADERS, **auth_headers},
            content=chunks(MCP_MAX_BODY_BYTES * 4),
        )

        assert response.status_code == 413

    async def test_the_413_comes_before_the_token_check(self, mcp_http):
        response = await mcp_http.post(
            "/mcp", headers=HEADERS, content=b" " * (MCP_MAX_BODY_BYTES + 1)
        )

        assert response.status_code == 413

    async def test_a_body_of_exactly_the_limit_is_not_refused_for_its_size(
        self, mcp_http, auth_headers
    ):
        padded = chunks(MCP_MAX_BODY_BYTES)
        sized = mcp_http.build_request(
            "POST", "/mcp", headers={**HEADERS, **auth_headers}, content=padded
        )
        declared = await mcp_http.post(
            "/mcp",
            headers={**HEADERS, **auth_headers},
            content=b" " * MCP_MAX_BODY_BYTES,
        )
        streamed = await mcp_http.send(sized)

        # The padding is not JSON-RPC, so the transport rejects it as a bad request.
        assert declared.status_code == 400
        assert streamed.status_code == 400

    async def test_the_limit_is_read_when_the_request_arrives(
        self, mcp_http, auth_headers, monkeypatch
    ):
        monkeypatch.setattr(mcp_server, "MCP_MAX_BODY_BYTES", 10)

        response = await initialize(mcp_http, auth_headers)

        assert response.status_code == 413


class TestFeatureSwitch:
    @pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
    async def test_the_endpoint_is_404_when_switched_off(
        self, mcp_http, auth_headers, monkeypatch, path
    ):
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", False)

        response = await initialize(mcp_http, auth_headers, path)

        assert response.status_code == 404

    async def test_it_is_404_without_a_token_too(self, mcp_http, monkeypatch):
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", False)

        response = await mcp_http.post("/mcp", headers=HEADERS, json=INITIALIZE)

        assert response.status_code == 404

    async def test_switching_it_back_on_serves_it_again(self, mcp_http, auth_headers, monkeypatch):
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", False)
        assert (await initialize(mcp_http, auth_headers)).status_code == 404
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", True)

        assert (await initialize(mcp_http, auth_headers)).status_code == 200
