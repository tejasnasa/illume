"""Dependency probes behind the health endpoint.

Each probe *reports* rather than raises: an unreachable dependency is a fact the
endpoint returns, not an error it propagates. That is what lets a caller tell
"the API is up and its database is down" from "the API is not answering at all".

Both probes are wrapped in a deadline because neither client configured here sets
a connection timeout of its own -- ``redis.asyncio.from_url`` has no
``socket_connect_timeout`` and asyncpg's default connect timeout is 60s -- so a
peer that accepts nothing would hold the request open instead of being reported
down. The deadline is the only thing that bounds the endpoint.
"""

import asyncio
import logging
from collections.abc import Awaitable
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.redis import get_async_redis

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 1.5

OK = "ok"
ERROR = "error"


async def probe_database() -> str:
    """Return ``"ok"`` when Postgres answers a trivial query, else ``"error"``."""
    # A connection of its own rather than the application's engine. The application's pool
    # hands back a connection created on whichever event loop touched it first, and a
    # pooled asyncpg connection reused from a different loop raises instead of answering --
    # so the probe would report "unreachable" for a reason that has nothing to do with the
    # database. NullPool leaves nothing behind to go stale, and the probe is asking whether
    # a connection can be established at all, which is the honest question for a readiness
    # check anyway.
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return OK
    except Exception:  # noqa: BLE001 -- a probe reports, it never raises
        logger.warning("health probe: database unreachable", exc_info=True)
        return ERROR
    finally:
        try:
            await asyncio.wait_for(engine.dispose(), PROBE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001
            pass


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
        # Releasing the client is best-effort and bounded too: a close that waits on a
        # dead socket would reintroduce the hang the timeout above just removed.
        try:
            await asyncio.wait_for(client.aclose(), PROBE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001
            pass


async def probe_dependencies() -> dict[str, str]:
    """Probe every dependency concurrently and return their verdicts.

    Returns:
        One ``"ok"`` or ``"error"`` per dependency, keyed by name.
    """
    database, redis = await asyncio.gather(probe_database(), probe_redis())
    return {"database": database, "redis": redis}
