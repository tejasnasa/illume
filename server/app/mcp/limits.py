"""Rate limits on MCP tool calls.

Counters are fixed-window and live in Redis, keyed on the **user**: a user may
hold several tokens, so a per-token limit would multiply the stated one by the
number of tokens. Three limits apply:

- every tool call counts toward :data:`MCP_CALLS_PER_MINUTE`;
- a repository tool whose ``cost`` is ``model`` or ``network`` (it spends the
  operator's embedding key or reaches GitHub) also counts toward
  :data:`MCP_MODEL_CALLS_PER_MINUTE`;
- a repository tool called by a user without an AI key of their own also counts
  toward :data:`MCP_FREE_CALLS_PER_DAY`. Raw tools do not touch the free chat
  allowance, so without this a keyless account would have unlimited
  operator-paid calls.

Going over a limit is an ordinary tool result the model can read, not an HTTP
error. The limiter is best-effort: when Redis is unreachable the call is allowed
and a warning is logged, as with the live-log publisher.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MCP_CALLS_PER_MINUTE = 60
MCP_MODEL_CALLS_PER_MINUTE = 20
MCP_FREE_CALLS_PER_DAY = 300

MODEL_COST_CLASSES = frozenset({"model", "network"})
"""Registry tool costs that count toward :data:`MCP_MODEL_CALLS_PER_MINUTE`."""

_MINUTE_SECONDS = 60
_DAY_SECONDS = 86_400
_REDIS_TIMEOUT_SECONDS = 2.0
_EXPIRY_SLACK_SECONDS = 5


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class Limited:
    """A limit that has been reached.

    Attributes:
        detail: Which limit, in words.
        retry_after: Whole seconds until the window it belongs to ends.
    """

    detail: str
    retry_after: int

    @property
    def message(self) -> str:
        """What the model is told."""
        return f"Rate limited, retry in {self.retry_after} s ({self.detail})."


def window_key(scope: str, user_id: uuid.UUID, size: int, now: float) -> str:
    """The Redis key of the counter for ``scope`` in the window containing ``now``.

    Args:
        scope: ``calls``, ``model`` or ``daily``.
        user_id: The token owner.
        size: The window length in seconds.
        now: Seconds since the epoch.
    """
    return f"mcp:rl:{scope}:{user_id}:{int(now // size) * size}"


class RateLimiter:
    """Counts a user's MCP calls against the three limits.

    Args:
        redis_factory: Returns an async Redis client. The client is closed after
            each check, so the factory must hand out a fresh one every time.
    """

    def __init__(self, redis_factory: Callable[[], Any]) -> None:
        self._redis_factory = redis_factory

    async def check_call(self, user_id: uuid.UUID) -> Limited | None:
        """Count one call of any tool against the per-minute limit.

        Args:
            user_id: The token owner.

        Returns:
            The limit that was reached, or ``None`` when the call may go ahead.
        """
        return await self._check(
            user_id, [("calls", _MINUTE_SECONDS, MCP_CALLS_PER_MINUTE, "tool calls per minute")]
        )

    async def check_repository_call(
        self, user_id: uuid.UUID, *, cost: str, keyless: bool
    ) -> Limited | None:
        """Count one repository tool call against the cost-based limits.

        Args:
            user_id: The token owner.
            cost: The registry tool's ``cost``.
            keyless: Whether the user has no AI key of their own.

        Returns:
            The limit that was reached, or ``None`` when the call may go ahead.
        """
        hits: list[tuple[str, int, int, str]] = []
        if cost in MODEL_COST_CLASSES:
            hits.append(
                (
                    "model",
                    _MINUTE_SECONDS,
                    MCP_MODEL_CALLS_PER_MINUTE,
                    "search and file-reading calls per minute",
                )
            )
        if keyless:
            hits.append(("daily", _DAY_SECONDS, MCP_FREE_CALLS_PER_DAY, "repository calls per day"))
        return await self._check(user_id, hits) if hits else None

    async def _check(
        self, user_id: uuid.UUID, hits: list[tuple[str, int, int, str]]
    ) -> Limited | None:
        try:
            client = self._redis_factory()
            try:
                async with asyncio.timeout(_REDIS_TIMEOUT_SECONDS):
                    for scope, size, limit, detail in hits:
                        now = _now()
                        key = window_key(scope, user_id, size, now)
                        pipe = client.pipeline(transaction=True)
                        pipe.incr(key)
                        pipe.expire(key, size + _EXPIRY_SLACK_SECONDS)
                        count = (await pipe.execute())[0]
                        if count > limit:
                            window_end = (int(now // size) + 1) * size
                            return Limited(
                                f"limit {limit} {detail}", max(1, math.ceil(window_end - now))
                            )
            finally:
                await client.aclose()
        except Exception:
            logger.warning("mcp rate limiter unavailable; allowing the call", exc_info=True)
        return None
