"""The per-user run cap against the real Redis: refusals, release and expiry."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services.agent.slots import RunSlots, slot_key

pytestmark = pytest.mark.integration


@pytest.fixture
async def user_id(redis_client):
    user = uuid.uuid4()
    yield user
    await redis_client.delete(slot_key(user))


async def test_the_limit_holds_and_release_makes_room(user_id, redis_client):
    slots = RunSlots(limit=2, ttl=60)

    assert await slots.acquire(user_id)
    assert await slots.acquire(user_id)
    assert not await slots.acquire(user_id)
    assert await redis_client.zcard(slot_key(user_id)) == 2

    await slots.release(user_id)
    assert await slots.acquire(user_id)


async def test_releasing_the_last_slot_leaves_no_key_behind(user_id, redis_client):
    slots = RunSlots(limit=1, ttl=60)
    assert await slots.acquire(user_id)

    await slots.release(user_id)

    assert await redis_client.exists(slot_key(user_id)) == 0


async def test_refused_attempts_do_not_extend_a_slot(user_id, redis_client):
    slots = RunSlots(limit=1, ttl=60)
    assert await slots.acquire(user_id)
    before = await redis_client.zrange(slot_key(user_id), 0, -1, withscores=True)

    for _ in range(5):
        assert not await slots.acquire(user_id)

    assert await redis_client.zrange(slot_key(user_id), 0, -1, withscores=True) == before
    assert 0 < await redis_client.ttl(slot_key(user_id)) <= 60


async def test_a_leaked_slot_frees_after_its_ttl_even_while_the_user_keeps_retrying(
    user_id, redis_client
):
    slots = RunSlots(limit=1, ttl=5)
    assert await slots.acquire(user_id)  # the run is then killed; nothing releases it

    refused = 0
    for _ in range(5):
        await asyncio.sleep(0.5)
        refused += not await slots.acquire(user_id)
    assert refused == 5

    await asyncio.sleep(3.5)  # past the slot's own expiry, retries notwithstanding
    assert await slots.acquire(user_id)


async def test_each_leaked_slot_expires_on_its_own(user_id, redis_client):
    slots = RunSlots(limit=2, ttl=3)
    assert await slots.acquire(user_id)
    await asyncio.sleep(2)
    assert await slots.acquire(user_id)
    assert not await slots.acquire(user_id)

    await asyncio.sleep(1.5)  # the first has expired, the second has not

    assert await slots.acquire(user_id)
    assert not await slots.acquire(user_id)
