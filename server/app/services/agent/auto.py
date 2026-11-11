"""The ``auto`` preset: one routing decision that picks a concrete preset.

A request for ``auto`` is resolved before the run starts. One Jev decision
classifies the question, :data:`ROUTE_PRESETS` maps the route to a preset, and
the run then proceeds exactly as if that preset had been requested. The decision
runs on the operator's key and is not charged to anyone.

The resolution never fails a request. Whenever the route cannot be trusted the
run takes :data:`FALLBACK_PRESET` instead, and says why in
:attr:`AutoRoute.fallback_reason`:

* ``unavailable``: no decision model can be built (no ``OPENROUTER_API_KEY``).
* ``timeout``: the decision took longer than :data:`ROUTE_TIMEOUT_SECONDS`.
* ``error``: the decision request failed.
* ``low_confidence``: the chosen route's probability is under
  :data:`~app.services.decisions.points.ROUTE_CONFIDENCE`.
* ``no_tool_support``: the route asked for the agent and the user's model
  cannot call tools.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.decisions import (
    ROUTE_CONFIDENCE,
    Decider,
    DeciderUnavailable,
    DecisionRecord,
    JevDecider,
    Route,
    decide_route,
)
from app.services.rag import ChatMessage

logger = logging.getLogger(__name__)

AUTO = "auto"
"""The preset name that asks for a routing decision."""

FALLBACK_PRESET = "structural"
"""The preset used whenever the route cannot be trusted."""

ROUTE_TIMEOUT_SECONDS = 4.0
"""How long the decision may take before the fallback is used."""

ROUTE_PRESETS: dict[Route, str] = {
    Route.LOCAL: "hybrid_rerank",
    Route.RELATIONAL: "structural",
    Route.HISTORY: "structural",
    Route.GLOBAL: "deep_agent",
    Route.OUT_OF_SCOPE: "classic",
}
"""The preset each route resolves to."""


@dataclass(frozen=True)
class AutoRoute:
    """What an ``auto`` request resolved to.

    Attributes:
        resolved_preset: The preset the run uses.
        route: The route the decision chose, or ``None`` when no decision was made.
        confidence: The probability of that route, when known.
        probabilities: The probability of every route, when reported.
        fallback_reason: Why :data:`FALLBACK_PRESET` was used instead of the
            route's own preset; ``None`` when the route was followed.
        model: The model that answered, when one did.
        decision: The decision record for the step log, when one was made.
    """

    resolved_preset: str
    route: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    fallback_reason: str | None = None
    model: str | None = None
    decision: dict[str, Any] | None = None

    def event_data(self) -> dict[str, Any]:
        """The ``route`` event's data."""
        return {
            "route": self.route,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
            "resolved_preset": self.resolved_preset,
            "fallback_reason": self.fallback_reason,
        }


def last_user_turn(history: Sequence[ChatMessage]) -> str | None:
    """The most recent user message of the history, or ``None`` when there is none."""
    return next((turn.content for turn in reversed(history) if turn.role == "user"), None)


async def resolve_auto(
    question: str,
    history: Sequence[ChatMessage],
    *,
    decider: Decider | None = None,
    supports_tools: Callable[[], Awaitable[bool | None]] | None = None,
    timeout: float | None = None,
    confidence_floor: float = ROUTE_CONFIDENCE,
) -> AutoRoute:
    """Decides which concrete preset answers the question.

    Args:
        question: The question as asked.
        history: Earlier turns; only the last user turn is shown to the decision.
        decider: Who decides. ``None`` builds the Jev decider from the operator key.
        supports_tools: Reports whether the user's model can call tools. Asked
            only when the route needs the agent; ``False`` means it cannot.
        timeout: Seconds the decision may take; :data:`ROUTE_TIMEOUT_SECONDS` when omitted.
        confidence_floor: The probability the chosen route must reach.

    Returns:
        The resolution. Never raises: every failure becomes the fallback preset.
    """
    if decider is None:
        try:
            decider = JevDecider()
        except DeciderUnavailable as error:
            logger.info("auto routing fell back: %s", error)
            return AutoRoute(FALLBACK_PRESET, fallback_reason="unavailable")

    timeout = ROUTE_TIMEOUT_SECONDS if timeout is None else timeout
    records: list[DecisionRecord] = []

    async def keep(record: DecisionRecord) -> None:
        records.append(record)

    try:
        decision = await asyncio.wait_for(
            decide_route(
                decider,
                question,
                last_user_turn=last_user_turn(history),
                confidence_floor=confidence_floor,
                record=keep,
            ),
            timeout,
        )
    except TimeoutError:
        logger.warning("auto routing timed out after %.1fs", timeout)
        return AutoRoute(FALLBACK_PRESET, fallback_reason="timeout")
    except Exception:
        logger.warning("auto routing failed", exc_info=True)
        return AutoRoute(FALLBACK_PRESET, fallback_reason="error")

    common: dict[str, Any] = {
        "route": decision.route.value,
        "confidence": decision.confidence,
        "probabilities": decision.probabilities,
        "model": decision.model,
        "decision": records[0].to_dict() if records else None,
    }
    if not decision.accepted:
        return AutoRoute(FALLBACK_PRESET, fallback_reason="low_confidence", **common)

    preset = ROUTE_PRESETS[decision.route]
    if preset == "deep_agent" and supports_tools is not None and await supports_tools() is False:
        return AutoRoute(FALLBACK_PRESET, fallback_reason="no_tool_support", **common)
    return AutoRoute(preset, **common)
