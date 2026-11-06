"""The verify node: a hook for checking the finished answer's citations.

With no verifier supplied the node passes the answer through. With one, a report
of unsupported claims sends the agent back to repair them, as many times as the
configuration allows; after that the answer stands as it is.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.prompts import repair_feedback_message
from app.services.agent.state import AgentState

logger = logging.getLogger(__name__)


def make_verify_node(deps: AgentDeps):
    """Builds the verify node."""

    async def verify(state: AgentState) -> dict[str, Any]:
        if deps.verifier is None or not state["answer"]:
            return {}
        try:
            report = await deps.verifier(state)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"[:300]
            logger.warning("verification failed: %s", reason)
            await deps.event(Event.DEGRADED, {"stage": "verify", "reason": reason})
            return {}
        if report is None:
            return {}
        update: dict[str, Any] = {"verification": report}
        if report.failed and state["repair_rounds"] < deps.agent.max_repair_rounds:
            update.update(
                {
                    "items": [
                        {
                            "role": "user",
                            "content": repair_feedback_message(report.unsupported),
                        }
                    ],
                    "repair_rounds": state["repair_rounds"] + 1,
                    "draft": None,
                    "answer": None,
                    "stop_reason": None,
                    "turn_end": None,
                }
            )
        return update

    return verify
