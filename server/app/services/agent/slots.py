"""A per-user cap on agent runs in flight.

One run is tens of model calls and holds a connection to the provider for as
long as it lasts, so each user may have a small number at once. The slots live
in Redis, so the cap holds across API processes. Each slot is a member of a
sorted set scored by its own expiry time, so a process that dies without
releasing its slot loses just that slot once its time passes, however much the
user keeps asking in the meantime.
"""

from __future__ import annotations

import logging
import uuid

from app.core.redis import get_async_redis

logger = logging.getLogger(__name__)

MAX_CONCURRENT_RUNS = 2
"""Runs one user may have in flight."""

SLOT_TTL_SECONDS = 960
"""Longer than the longest run a request can ask for, so a live run keeps its slot."""

# Expired slots are pruned first, so a refused attempt changes nothing: it adds
# no member and moves no expiry. The key's own TTL only tidies up an idle key.
_ACQUIRE = """
local now = tonumber(redis.call('TIME')[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    return 0
end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

# Any one slot may be given back; the one closest to expiring goes first.
_RELEASE = """
redis.call('ZPOPMIN', KEYS[1])
return redis.call('ZCARD', KEYS[1])
"""


def slot_key(user_id: uuid.UUID | str) -> str:
    """The Redis sorted set holding a user's runs in flight."""
    return f"agent:runs:{user_id}"


class RunSlots:
    """Claims and releases a user's run slots.

    Redis trouble never blocks a question: when the slots cannot be reached, a
    slot is granted and the problem is logged. The cap protects the provider and
    the API process; it is not a billing control.
    """

    def __init__(self, limit: int = MAX_CONCURRENT_RUNS, ttl: int = SLOT_TTL_SECONDS) -> None:
        self.limit = limit
        self.ttl = ttl

    async def acquire(self, user_id: uuid.UUID | str) -> bool:
        """Claims a slot.

        Returns:
            ``False`` when the user already has ``limit`` runs in flight.
        """
        client = get_async_redis()
        try:
            granted = await client.eval(  # type: ignore[misc]
                _ACQUIRE, 1, slot_key(user_id), self.limit, self.ttl, uuid.uuid4().hex
            )
            return bool(granted)
        except Exception:
            logger.warning("could not claim a run slot; allowing the run", exc_info=True)
            return True
        finally:
            await _close(client)

    async def release(self, user_id: uuid.UUID | str) -> None:
        """Gives a slot back; a failure is logged and left to the TTL."""
        client = get_async_redis()
        try:
            await client.eval(_RELEASE, 1, slot_key(user_id))  # type: ignore[misc]
        except Exception:
            logger.warning("could not release a run slot; the TTL will", exc_info=True)
        finally:
            await _close(client)


async def _close(client) -> None:
    try:
        await client.aclose()
    except Exception:
        logger.debug("closing the Redis client failed", exc_info=True)
