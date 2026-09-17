"""The health endpoint is reachable without a session."""

import pytest

pytestmark = pytest.mark.smoke


async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_healthz_needs_no_session(client):
    """A caller with no cookie still gets a response, not a 401."""
    response = await client.get("/healthz")

    assert response.status_code != 401
