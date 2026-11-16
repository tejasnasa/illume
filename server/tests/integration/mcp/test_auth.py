"""Only a valid Illume token reaches the MCP transport, on every request.

Rejections are checked with raw HTTP so the assertions are about the response the
wrapper itself produced, before any JSON-RPC was processed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from mcp.shared.exceptions import MCPError
from sqlalchemy import select, update

from app.mcp.server import SERVER_NAME
from app.models.mcp_token import McpToken
from app.services.mcp_tokens import create_token, revoke_token
from tests.factories import make_user
from tests.integration.mcp.test_mount import HEADERS, INITIALIZE, initialize

pytestmark = pytest.mark.integration


def assert_plain_401(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "resource_metadata" not in response.headers["www-authenticate"]
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "invalid or missing Illume token"
    with pytest.raises(ValueError):
        json.loads(response.text)


class TestRejection:
    async def test_no_token_is_401(self, mcp_http):
        assert_plain_401(await mcp_http.post("/mcp", headers=HEADERS, json=INITIALIZE))

    async def test_a_garbage_token_is_401(self, mcp_http):
        response = await initialize(mcp_http, {}, authorization="Bearer not-a-token")

        assert_plain_401(response)

    async def test_a_well_formed_but_unknown_token_is_401(self, mcp_http):
        response = await initialize(mcp_http, {}, authorization="Bearer ilm_" + "A" * 43)

        assert_plain_401(response)

    async def test_a_non_bearer_scheme_is_401(self, mcp_http, mcp_token):
        response = await initialize(mcp_http, {}, authorization=f"Basic {mcp_token}")

        assert_plain_401(response)

    async def test_an_empty_bearer_value_is_401(self, mcp_http):
        assert_plain_401(await initialize(mcp_http, {}, authorization="Bearer "))

    async def test_a_revoked_token_is_401(self, mcp_http, db_session, mcp_user, mcp_token):
        token_id = await db_session.scalar(
            select(McpToken.id).where(McpToken.user_id == mcp_user.id)
        )
        await revoke_token(db_session, mcp_user.id, token_id)

        response = await initialize(mcp_http, {}, authorization=f"Bearer {mcp_token}")

        assert_plain_401(response)

    async def test_an_expired_token_is_401(self, mcp_http, db_session, mcp_user, mcp_token):
        await db_session.execute(
            update(McpToken)
            .where(McpToken.user_id == mcp_user.id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db_session.commit()

        response = await initialize(mcp_http, {}, authorization=f"Bearer {mcp_token}")

        assert_plain_401(response)

    async def test_the_rejection_happens_before_the_body_is_read(self, mcp_http):
        response = await mcp_http.post("/mcp", headers=HEADERS, content="{not json")

        assert_plain_401(response)

    async def test_a_bad_host_without_a_token_is_401_not_421(self, mcp_http):
        response = await initialize(mcp_http, {}, host="evil.example.com")

        assert response.status_code == 401


class TestAcceptance:
    async def test_a_valid_token_initializes(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers)

        assert response.status_code == 200
        assert "www-authenticate" not in response.headers

    async def test_the_scheme_is_case_insensitive(self, mcp_http, mcp_token):
        response = await initialize(mcp_http, {}, authorization=f"bearer {mcp_token}")

        assert response.status_code == 200

    async def test_a_valid_token_lists_the_account_tools_and_not_ping(self, mcp_client):
        names = [tool.name for tool in (await mcp_client.list_tools()).tools]

        assert "whoami" in names
        assert "list_repositories" in names
        assert "ping" not in names

    async def test_the_server_describes_itself_to_the_model(self, mcp_client):
        assert mcp_client.server_info.name == SERVER_NAME
        instructions = mcp_client.instructions

        assert "list_repositories" in instructions
        assert "<source" in instructions

    async def test_a_client_without_a_token_cannot_connect(self, mcp_connect):
        with pytest.raises(BaseException):  # noqa: B017  (the SDK wraps the 401 in a group)
            async with mcp_connect():
                pass

    async def test_the_token_of_another_user_authenticates_as_that_user(
        self, mcp_connect, db_session
    ):
        other = await make_user(db_session, email="someone-else@example.com")
        _, plaintext = await create_token(db_session, other.id, "other", 30)

        async with mcp_connect(authorization=f"Bearer {plaintext}") as client:
            result = await client.call_tool("whoami", {})

        assert result.structured_content["email"] == "someone-else@example.com"


class TestPerRequestVerification:
    async def test_revoking_a_token_mid_session_fails_the_next_call(
        self, mcp_connect, db_session, mcp_user, mcp_token, auth_headers
    ):
        async with mcp_connect(**auth_headers) as client:
            assert (await client.call_tool("whoami", {})).is_error is not True

            token_id = await db_session.scalar(
                select(McpToken.id).where(McpToken.user_id == mcp_user.id)
            )
            await revoke_token(db_session, mcp_user.id, token_id)

            with pytest.raises(MCPError):
                await client.call_tool("whoami", {})


class TestTransportSecurityWithAToken:
    async def test_a_disallowed_host_is_421(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, host="evil.example.com")

        assert response.status_code == 421

    async def test_a_foreign_origin_is_403(self, mcp_http, auth_headers):
        response = await initialize(mcp_http, auth_headers, origin="https://evil.example.com")

        assert response.status_code == 403
