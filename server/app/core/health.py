"""Dependency probes behind the health endpoint.

A probe *reports* rather than raises: an unreachable dependency is a fact the endpoint
returns, not an error it propagates. That is what lets a caller tell "the API is up and a
dependency is down" from "the API is not answering at all".

**There is deliberately no database probe here, and adding one back is not an improvement.**
Reaching Postgres means opening a connection, so a check that does it measures connection
setup -- DNS, TCP, TLS, authentication -- rather than whether the application can serve
database traffic. Against a remote instance that took longer than any sensible health-check
budget, so the endpoint reported a perfectly healthy database as down. The application's own
pool is not a way around it either: a pooled asyncpg connection belongs to the event loop
that created it, and reusing one from another loop raises instead of answering.

Database health is covered functionally instead, by the end-to-end suite, which reads real
pages and writes and re-reads a chat turn through the deployed stack. That is a better
signal than a synthetic ping, and it costs the endpoint nothing.

Redis has neither problem: a ping is a single round trip over a connection that is cheap to
open, so it is worth probing here.
"""

import asyncio
import logging
from collections.abc import Awaitable
from typing import cast

from app.core.redis import get_async_redis

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 1.5

OK = "ok"
ERROR = "error"


async def probe_redis() -> str:
    """Return ``"ok"`` when Redis answers a ping, else ``"error"``."""
    client = get_async_redis()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            # redis-py types `ping` as returning either a value or an awaitable, because the
            # sync and async clients share a base class. On this client it is always awaitable.
            await cast(Awaitable[bool], client.ping())
        return OK
    except Exception:  # noqa: BLE001 -- a probe reports, it never raises
        logger.warning("health probe: redis unreachable", exc_info=True)
        return ERROR
    finally:
        # Releasing the client is best-effort and bounded too: a close that waits on a dead
        # socket would reintroduce the hang the timeout above just removed.
        try:
            await asyncio.wait_for(client.aclose(), PROBE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001
            pass


async def probe_dependencies() -> dict[str, str]:
    """Probe every dependency and return their verdicts, keyed by name.

    Returns:
        One ``"ok"`` or ``"error"`` per probed dependency.
    """
    return {"redis": await probe_redis()}
