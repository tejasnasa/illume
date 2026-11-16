"""The rate limiter's windows, keys and failure mode, against a fake Redis."""

from __future__ import annotations

import logging
import uuid

import fakeredis
import fakeredis.aioredis
import pytest

from app.mcp import limits
from app.mcp.limits import (
    MCP_CALLS_PER_MINUTE,
    MCP_FREE_CALLS_PER_DAY,
    MCP_MODEL_CALLS_PER_MINUTE,
    RateLimiter,
    window_key,
)

# 1_700_000_050 is ten seconds into a minute, so that window has 50 seconds left.
NOW = 1_700_000_050.0


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def limiter(server):
    return RateLimiter(lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"t": NOW}
    monkeypatch.setattr(limits, "_now", lambda: now["t"])
    return now


async def test_the_call_after_the_limit_is_refused_with_the_seconds_left(limiter):
    user = uuid.uuid4()
    for _ in range(MCP_CALLS_PER_MINUTE):
        assert await limiter.check_call(user) is None

    limited = await limiter.check_call(user)

    assert limited is not None
    assert limited.retry_after == 50
    assert "retry in 50 s" in limited.message


async def test_a_new_window_starts_a_new_count(limiter, clock):
    user = uuid.uuid4()
    for _ in range(MCP_CALLS_PER_MINUTE + 1):
        await limiter.check_call(user)

    clock["t"] = NOW + 50

    assert await limiter.check_call(user) is None


async def test_users_are_counted_separately(limiter):
    first, second = uuid.uuid4(), uuid.uuid4()
    for _ in range(MCP_CALLS_PER_MINUTE + 1):
        await limiter.check_call(first)

    assert await limiter.check_call(second) is None


async def test_only_model_and_network_tools_count_toward_the_model_limit(limiter):
    user = uuid.uuid4()
    for _ in range(MCP_MODEL_CALLS_PER_MINUTE + 5):
        assert await limiter.check_repository_call(user, cost="free", keyless=False) is None

    for _ in range(MCP_MODEL_CALLS_PER_MINUTE):
        assert await limiter.check_repository_call(user, cost="model", keyless=False) is None
    assert await limiter.check_repository_call(user, cost="model", keyless=False) is not None
    assert await limiter.check_repository_call(user, cost="network", keyless=False) is not None


async def test_the_daily_cap_applies_to_keyless_users_only(limiter, server):
    keyless, owner = uuid.uuid4(), uuid.uuid4()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    for user in (keyless, owner):
        await redis.set(window_key("daily", user, 86_400, NOW), MCP_FREE_CALLS_PER_DAY)

    over = await limiter.check_repository_call(keyless, cost="free", keyless=True)
    fine = await limiter.check_repository_call(owner, cost="free", keyless=False)

    assert over is not None
    assert "per day" in over.detail
    assert fine is None


async def test_a_counter_expires_with_its_window(limiter, server):
    user = uuid.uuid4()
    await limiter.check_call(user)
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    ttl = await redis.ttl(window_key("calls", user, 60, NOW))

    assert 0 < ttl <= 65


async def test_an_unreachable_redis_allows_the_call_and_warns(caplog):
    def down():
        raise ConnectionError("no redis")

    caplog.set_level(logging.WARNING, logger="app.mcp.limits")

    assert await RateLimiter(down).check_call(uuid.uuid4()) is None
    assert (
        await RateLimiter(down).check_repository_call(uuid.uuid4(), cost="model", keyless=True)
        is None
    )
    assert "allowing the call" in caplog.text


async def test_the_hourly_ask_limit_refuses_the_next_run_with_the_seconds_left(limiter):
    user = uuid.uuid4()
    for _ in range(limits.MCP_ASK_PER_HOUR):
        assert await limiter.check_ask(user) is None

    limited = await limiter.check_ask(user)

    window_end = (int(NOW // 3600) + 1) * 3600
    assert limited is not None
    assert limited.retry_after == int(window_end - NOW)
    assert "ask_illume runs per hour" in limited.message


async def test_the_ask_limit_is_per_user(limiter):
    first, second = uuid.uuid4(), uuid.uuid4()
    for _ in range(limits.MCP_ASK_PER_HOUR + 1):
        await limiter.check_ask(first)

    assert await limiter.check_ask(second) is None
