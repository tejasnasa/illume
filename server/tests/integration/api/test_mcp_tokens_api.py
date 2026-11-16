"""The MCP token routes: mint, list and revoke personal access tokens."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.mcp_token import McpToken
from app.services.mcp_tokens import MAX_TOKENS_PER_USER, hash_token, resolve_token
from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

URL = "/api/v1/auth/me/mcp-tokens"
METADATA_KEYS = {"id", "name", "prefix", "created_at", "last_used_at", "expires_at"}


class TestCreate:
    async def test_returns_the_plaintext_once_with_the_metadata(self, client, db_session):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.post(URL, json={"name": "laptop"})

        assert response.status_code == 201
        body = response.json()
        assert set(body) == METADATA_KEYS | {"token"}
        assert body["token"].startswith("ilm_")
        assert body["name"] == "laptop"
        assert body["prefix"] == body["token"][len("ilm_") :][:8]
        assert body["expires_at"] is not None
        assert body["last_used_at"] is None

    async def test_the_default_lifetime_is_ninety_days_and_null_is_never(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        default = (await client.post(URL, json={"name": "a"})).json()
        never = (await client.post(URL, json={"name": "b", "expires_in_days": None})).json()
        thirty = (await client.post(URL, json={"name": "c", "expires_in_days": 30})).json()

        now = datetime.now().astimezone()
        assert timedelta(days=89) < datetime.fromisoformat(default["expires_at"]) - now
        assert datetime.fromisoformat(default["expires_at"]) - now <= timedelta(days=90)
        assert never["expires_at"] is None
        assert datetime.fromisoformat(thirty["expires_at"]) - now <= timedelta(days=30)

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"name": ""},
            {"name": "x" * 61},
            {"name": "bad\x00name"},
            {"name": "ok", "expires_in_days": 7},
            {"name": "ok", "expires_in_days": "forever"},
        ],
    )
    async def test_rejects_an_invalid_payload(self, client, db_session, body):
        await authenticate(client, await make_user(db_session))

        assert (await client.post(URL, json=body)).status_code == 422

    async def test_a_sixty_character_name_is_accepted(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.post(URL, json={"name": "x" * 60})).status_code == 201

    async def test_the_cap_is_a_409(self, client, db_session):
        await authenticate(client, await make_user(db_session))
        for index in range(MAX_TOKENS_PER_USER):
            assert (await client.post(URL, json={"name": f"t{index}"})).status_code == 201

        response = await client.post(URL, json={"name": "one too many"})

        assert response.status_code == 409

    async def test_revoking_frees_a_slot_under_the_cap(self, client, db_session):
        await authenticate(client, await make_user(db_session))
        ids = [
            (await client.post(URL, json={"name": f"t{index}"})).json()["id"]
            for index in range(MAX_TOKENS_PER_USER)
        ]

        assert (await client.delete(f"{URL}/{ids[0]}")).status_code == 204

        assert (await client.post(URL, json={"name": "again"})).status_code == 201


class TestList:
    async def test_never_includes_the_plaintext_or_the_hash(self, client, db_session):
        await authenticate(client, await make_user(db_session))
        created = (await client.post(URL, json={"name": "laptop"})).json()

        response = await client.get(URL)

        assert response.status_code == 200
        [listed] = response.json()
        assert set(listed) == METADATA_KEYS
        assert listed["id"] == created["id"]
        assert created["token"] not in response.text
        assert hash_token(created["token"]) not in response.text

    async def test_omits_revoked_tokens(self, client, db_session):
        await authenticate(client, await make_user(db_session))
        first = (await client.post(URL, json={"name": "first"})).json()
        second = (await client.post(URL, json={"name": "second"})).json()
        third = (await client.post(URL, json={"name": "third"})).json()
        await client.delete(f"{URL}/{second['id']}")

        listed = (await client.get(URL)).json()

        assert {t["id"] for t in listed} == {first["id"], third["id"]}

    async def test_an_empty_list_is_an_empty_array(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(URL)).json() == []


class TestRevoke:
    async def test_a_revoked_token_no_longer_resolves(self, client, db_session):
        await authenticate(client, await make_user(db_session))
        created = (await client.post(URL, json={"name": "laptop"})).json()
        assert await resolve_token(db_session, created["token"]) is not None

        response = await client.delete(f"{URL}/{created['id']}")

        assert response.status_code == 204
        assert response.content == b""
        assert await resolve_token(db_session, created["token"]) is None
        assert (await client.get(URL)).json() == []

    async def test_revoking_twice_is_still_a_success(self, client, db_session):
        await authenticate(client, await make_user(db_session))
        created = (await client.post(URL, json={"name": "laptop"})).json()

        assert (await client.delete(f"{URL}/{created['id']}")).status_code == 204
        assert (await client.delete(f"{URL}/{created['id']}")).status_code == 204

    async def test_an_unknown_id_is_a_404(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.delete(f"{URL}/{uuid.uuid4()}")).status_code == 404

    async def test_a_malformed_id_is_a_422(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.delete(f"{URL}/not-a-uuid")).status_code == 422


class TestUnauthenticated:
    async def test_every_route_is_a_401_without_a_session(self, client):
        token_id = uuid.uuid4()

        assert (await client.get(URL)).status_code == 401
        assert (await client.post(URL, json={"name": "laptop"})).status_code == 401
        assert (await client.delete(f"{URL}/{token_id}")).status_code == 401


class TestStorage:
    async def test_the_row_holds_the_digest_and_no_plaintext(self, client, db_session):
        user = await make_user(db_session)
        await authenticate(client, user)
        created = (await client.post(URL, json={"name": "laptop"})).json()

        row = (
            await db_session.execute(select(McpToken).where(McpToken.user_id == user.id))
        ).scalar_one()

        assert row.token_hash == hash_token(created["token"])
        for column in McpToken.__table__.columns:
            assert created["token"] not in str(getattr(row, column.name)), column.name
