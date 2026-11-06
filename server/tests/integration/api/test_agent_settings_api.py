"""The agent settings endpoint: the context window agent runs work within.

It is a setting of its own, apart from the AI credential, so these tests also
pin that saving it needs no key and that removing the key leaves it alone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.user import User
from app.services.retrieval.config import (
    DEFAULT_CONTEXT_WINDOW,
    MAX_CONTEXT_WINDOW,
    MIN_CONTEXT_WINDOW,
)
from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

URL = "/api/v1/auth/me/agent-settings"
ME_URL = "/api/v1/auth/me"
CREDENTIALS_URL = "/api/v1/auth/me/ai-credentials"


async def _stored(db_session, user: User) -> int | None:
    row = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    await db_session.refresh(row)
    return row.ai_context_window


class TestRead:
    async def test_nothing_saved_reads_as_null_with_the_default_and_bounds(
        self, client, db_session
    ):
        user = await make_user(db_session)
        await authenticate(client, user)

        body = (await client.get(URL)).json()

        assert body == {
            "context_window": None,
            "context_window_default": DEFAULT_CONTEXT_WINDOW,
            "context_window_min": MIN_CONTEXT_WINDOW,
            "context_window_max": MAX_CONTEXT_WINDOW,
        }
        assert (DEFAULT_CONTEXT_WINDOW, MIN_CONTEXT_WINDOW, MAX_CONTEXT_WINDOW) == (
            250_000,
            32_000,
            1_000_000,
        )

    async def test_me_reports_the_window_and_the_default(self, client, db_session):
        user = await make_user(db_session)
        user.ai_context_window = 128_000
        await db_session.flush()
        await authenticate(client, user)

        body = (await client.get(ME_URL)).json()

        assert body["ai_context_window"] == 128_000
        assert body["ai_context_window_default"] == DEFAULT_CONTEXT_WINDOW


class TestWrite:
    async def test_a_window_is_saved_without_an_ai_key(self, client, db_session):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(URL, json={"context_window": 400_000})

        assert response.status_code == 200
        assert response.json()["context_window"] == 400_000
        assert (await client.get(URL)).json()["context_window"] == 400_000
        assert await _stored(db_session, user) == 400_000

    async def test_null_resets_to_the_default(self, client, db_session):
        user = await make_user(db_session)
        user.ai_context_window = 500_000
        await db_session.flush()
        await authenticate(client, user)

        response = await client.put(URL, json={"context_window": None})

        assert response.json()["context_window"] is None
        assert await _stored(db_session, user) is None

    @pytest.mark.parametrize("window", [MIN_CONTEXT_WINDOW, MAX_CONTEXT_WINDOW])
    async def test_the_bounds_are_inclusive(self, client, db_session, window):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(URL, json={"context_window": window})

        assert response.status_code == 200
        assert response.json()["context_window"] == window

    @pytest.mark.parametrize(
        "window",
        [MIN_CONTEXT_WINDOW - 1, 0, -5, MAX_CONTEXT_WINDOW + 1, 1.5, "lots"],
        ids=["below", "zero", "negative", "above", "fraction", "text"],
    )
    async def test_out_of_range_or_malformed_is_422_and_stores_nothing(
        self, client, db_session, window
    ):
        user = await make_user(db_session)
        user.ai_context_window = 300_000
        await db_session.flush()
        await authenticate(client, user)

        response = await client.put(URL, json={"context_window": window})

        assert response.status_code == 422
        assert await _stored(db_session, user) == 300_000

    async def test_removing_the_ai_key_keeps_the_window(self, client, db_session):
        user = await make_user(
            db_session, ai_api_key="sk-test-key-12345", ai_provider="openai", ai_model="m"
        )
        user.ai_context_window = 300_000
        await db_session.flush()
        await authenticate(client, user)

        assert (await client.delete(CREDENTIALS_URL)).status_code == 200

        assert await _stored(db_session, user) == 300_000


class TestAccess:
    async def test_one_users_window_never_reaches_another(self, client, db_session):
        owner = await make_user(db_session)
        other = await make_user(db_session)
        await authenticate(client, owner)
        await client.put(URL, json={"context_window": 900_000})

        assert await _stored(db_session, other) is None
        await authenticate(client, other)
        assert (await client.get(URL)).json()["context_window"] is None

    @pytest.mark.security
    @pytest.mark.parametrize("method", ["get", "put"])
    async def test_requires_authentication(self, client, method):
        kwargs = {"json": {"context_window": 64_000}} if method == "put" else {}
        response = await getattr(client, method)(URL, **kwargs)
        assert response.status_code == 401
