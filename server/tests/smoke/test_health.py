"""The health endpoint reports dependency state, and needs no session."""

import asyncio
import time

import pytest

from app import main
from app.core import health

pytestmark = pytest.mark.smoke


async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


async def test_healthz_needs_no_session(client):
    """A caller with no cookie still gets a response, not a 401."""
    response = await client.get("/healthz")

    assert response.status_code != 401


async def test_healthz_degrades_to_503_when_a_dependency_is_down(client, monkeypatch):
    """A downed dependency is reported, not hidden behind a 200."""

    async def degraded() -> dict[str, str]:
        return {"database": "ok", "redis": "error"}

    monkeypatch.setattr(main, "probe_dependencies", degraded)

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "error"


async def test_probe_redis_reports_error_instead_of_hanging(monkeypatch):
    """A peer that never answers must not hold the request open.

    Neither client used by the probes has a connection timeout configured, so without
    the deadline in ``probe_redis`` this await would never return and the endpoint would
    hang rather than report unhealthy. The assertion is on the measured duration, not
    just the return value, because that is the property under test.
    """

    class HangingClient:
        async def ping(self):
            await asyncio.sleep(30)

        async def aclose(self):
            return None

    monkeypatch.setattr(health, "get_async_redis", lambda: HangingClient())
    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.05)

    started = time.monotonic()
    result = await health.probe_redis()
    elapsed = time.monotonic() - started

    assert result == "error"
    assert elapsed < 5, f"probe took {elapsed:.1f}s; the deadline did not fire"
