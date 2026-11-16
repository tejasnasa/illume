"""The MCP feature switch as the rest of the API sees it."""

from __future__ import annotations

import pytest

from app.mcp import server as mcp_server
from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

ME = "/api/v1/auth/me"
URL = "/api/v1/auth/me/mcp-tokens"


class TestMe:
    async def test_reports_mcp_as_enabled_by_default(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(ME)).json()["mcp_enabled"] is True

    async def test_reports_mcp_as_disabled_when_switched_off(self, client, db_session, monkeypatch):
        await authenticate(client, await make_user(db_session))
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", False)

        assert (await client.get(ME)).json()["mcp_enabled"] is False


class TestWhileSwitchedOff:
    async def test_the_endpoint_is_404(self, client, monkeypatch):
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", False)

        assert (await client.post("/mcp", json={})).status_code == 404
        assert (await client.post("/mcp/", json={})).status_code == 404

    async def test_the_endpoint_still_asks_for_a_token_when_switched_on(self, client):
        assert (await client.post("/mcp", json={})).status_code == 401

    async def test_tokens_can_still_be_listed_created_and_revoked(
        self, client, db_session, monkeypatch
    ):
        await authenticate(client, await make_user(db_session))
        kept = (await client.post(URL, json={"name": "kept"})).json()
        monkeypatch.setattr(mcp_server, "MCP_ENABLED", False)

        listed = await client.get(URL)
        created = await client.post(URL, json={"name": "new"})
        revoked = await client.delete(f"{URL}/{kept['id']}")

        assert listed.status_code == 200
        assert [t["id"] for t in listed.json()] == [kept["id"]]
        assert created.status_code == 201
        assert revoked.status_code == 204
        assert {t["id"] for t in (await client.get(URL)).json()} == {created.json()["id"]}
