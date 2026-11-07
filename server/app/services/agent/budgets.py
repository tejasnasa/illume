"""The limits of one run, counted in one place.

:class:`RunBudget` is the single object every part of a run shares. Its counters
are read and changed behind one ``asyncio.Lock``, so a limit is enforced the
moment it is crossed even when several tool calls or workers charge it at once.
It also announces each crossing as a ``degraded`` event, once per limit, so the
interface can say why an answer arrived early.

Model turns per agent are bounded by ``max_iterations`` and counted in the
graph state, because that limit belongs to one agent and not to the whole run.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.services.retrieval.channels.base import Emit
from app.services.retrieval.config import DEFAULT_CONTEXT_WINDOW, AgentConfig

logger = logging.getLogger(__name__)


class BudgetLimit(StrEnum):
    """A limit a run can reach. The value is the name of the config field."""

    ITERATIONS = "max_iterations"
    TOOL_CALLS = "max_tool_calls"
    SECONDS = "max_seconds"
    INPUT_TOKENS = "max_input_tokens"


def context_window_for(user_window: int | None) -> int:
    """The context window a user's runs use.

    Args:
        user_window: The value stored on the user, or ``None`` when they have
            not chosen one.

    Returns:
        The user's window, or the default when they have none.
    """
    return DEFAULT_CONTEXT_WINDOW if user_window is None else user_window


@dataclass(frozen=True)
class BudgetSnapshot:
    """What a run has used so far.

    Attributes:
        tool_calls: Tool calls started.
        input_tokens: Input tokens providers reported.
        output_tokens: Output tokens providers reported.
        elapsed_seconds: Wall time since the run began.
        reached: The limits that have been reached, in the order they were.
        quarantines: Tool results the injection screen withheld.
    """

    tool_calls: int
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    reached: tuple[str, ...]
    quarantines: int = 0


async def _discard(event: str, payload: dict[str, Any]) -> None:
    """The default emitter, for callers that do not stream progress."""


class RunBudget:
    """Counts tool calls, tokens and wall clock for one run.

    Implements :class:`~app.services.agent.tools.context.SharedBudget`.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        emit: Emit = _discard,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            config: The limits.
            emit: Receives one ``degraded`` event per limit reached.
            clock: Monotonic seconds; replaceable so tests need not wait.
        """
        self._config = config
        self._emit = emit
        self._clock = clock
        self._started = clock()
        self._lock = asyncio.Lock()
        self._tool_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._quarantines = 0
        self._announced: list[BudgetLimit] = []

    @property
    def config(self) -> AgentConfig:
        """The limits this budget enforces."""
        return self._config

    def elapsed(self) -> float:
        """Seconds since the run began."""
        return self._clock() - self._started

    async def reserve_tool_calls(self, count: int) -> int:
        """Claims up to ``count`` tool calls and returns how many were granted."""
        async with self._lock:
            granted = max(min(count, self._config.max_tool_calls - self._tool_calls), 0)
            self._tool_calls += granted
            return granted

    async def add_usage(self, input_tokens: int, output_tokens: int = 0) -> None:
        """Adds the tokens a provider reported for one model call."""
        async with self._lock:
            self._input_tokens += max(input_tokens, 0)
            self._output_tokens += max(output_tokens, 0)

    async def note_quarantine(self) -> None:
        """Counts one tool result the injection screen withheld."""
        async with self._lock:
            self._quarantines += 1

    def _reached_locked(self) -> BudgetLimit | None:
        """The first limit that has been reached. The caller holds the lock."""
        if self._input_tokens >= self._config.max_input_tokens:
            return BudgetLimit.INPUT_TOKENS
        if self._tool_calls >= self._config.max_tool_calls:
            return BudgetLimit.TOOL_CALLS
        if self.elapsed() >= self._config.max_seconds:
            return BudgetLimit.SECONDS
        return None

    async def exceeded(self) -> str | None:
        """The name of a limit that has been reached, or ``None``.

        The first time a limit is seen reached it is announced with a
        ``degraded`` event. Using the last tool call counts as reaching the
        limit: no further call can be started.
        """
        payload: dict[str, Any] | None = None
        async with self._lock:
            limit = self._reached_locked()
            if limit is not None and limit not in self._announced:
                self._announced.append(limit)
                payload = self._payload(limit)
        if payload is not None:
            await self._announce(payload)
        return limit.value if limit is not None else None

    async def note_reached(self, limit: BudgetLimit, used: int, allowed: int) -> None:
        """Announces a limit the caller counted itself, such as model turns."""
        async with self._lock:
            if limit in self._announced:
                return
            self._announced.append(limit)
        await self._announce(
            {"stage": "budget", "limit": limit.value, "used": used, "allowed": allowed}
        )

    def _payload(self, limit: BudgetLimit) -> dict[str, Any]:
        used, allowed = {
            BudgetLimit.INPUT_TOKENS: (self._input_tokens, self._config.max_input_tokens),
            BudgetLimit.TOOL_CALLS: (self._tool_calls, self._config.max_tool_calls),
            BudgetLimit.SECONDS: (round(self.elapsed(), 1), self._config.max_seconds),
            BudgetLimit.ITERATIONS: (0, self._config.max_iterations),
        }[limit]
        return {"stage": "budget", "limit": limit.value, "used": used, "allowed": allowed}

    async def _announce(self, payload: dict[str, Any]) -> None:
        try:
            await self._emit("degraded", payload)
        except Exception:
            logger.warning("emitting the budget degradation failed", exc_info=True)

    async def snapshot(self) -> BudgetSnapshot:
        """What the run has used so far."""
        async with self._lock:
            return BudgetSnapshot(
                tool_calls=self._tool_calls,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                elapsed_seconds=round(self.elapsed(), 3),
                reached=tuple(limit.value for limit in self._announced),
                quarantines=self._quarantines,
            )
