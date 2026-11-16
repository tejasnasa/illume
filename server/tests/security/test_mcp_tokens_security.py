"""MCP token isolation between users, and that a token is not a session."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.factories import make_user
from tests.helpers import authenticate, make_two_users

pytestmark = pytest.mark.security

URL = "/api/v1/auth/me/mcp-tokens"


async def test_user_b_cannot_list_user_as_tokens(client, db_session):
    a, b = await make_two_users(db_session)
    await authenticate(client, a)
    created = (await client.post(URL, json={"name": "a-laptop"})).json()
    await authenticate(client, b)

    listed = (await client.get(URL)).json()

    assert listed == []
    assert created["id"] not in str(listed)


async def test_user_b_cannot_revoke_user_as_token(client, db_session):
    a, b = await make_two_users(db_session)
    await authenticate(client, a)
    created = (await client.post(URL, json={"name": "a-laptop"})).json()
    await authenticate(client, b)

    response = await client.delete(f"{URL}/{created['id']}")

    assert response.status_code == 404
    await authenticate(client, a)
    assert [t["id"] for t in (await client.get(URL)).json()] == [created["id"]]


async def test_an_mcp_token_is_not_a_session(client, db_session):
    await authenticate(client, await make_user(db_session))
    created = (await client.post(URL, json={"name": "laptop"})).json()
    client.cookies.clear()

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {created['token']}"}
    )

    assert response.status_code == 401


async def test_an_mcp_token_cannot_reach_the_token_routes_either(client, db_session):
    await authenticate(client, await make_user(db_session))
    created = (await client.post(URL, json={"name": "laptop"})).json()
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {created['token']}"}

    assert (await client.get(URL, headers=headers)).status_code == 401
    assert (await client.post(URL, json={"name": "x"}, headers=headers)).status_code == 401


async def test_no_column_of_the_stored_row_contains_the_plaintext(client, db_session):
    user = await make_user(db_session)
    await authenticate(client, user)
    created = (await client.post(URL, json={"name": "laptop"})).json()

    stored = (
        await db_session.execute(
            text("SELECT t::text FROM mcp_tokens t WHERE t.user_id = :user_id"),
            {"user_id": user.id},
        )
    ).scalar_one()

    assert created["token"] not in stored
