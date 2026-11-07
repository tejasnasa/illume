"""The verify node: checks the finished answer's citations and marks what failed.

With no verifier supplied the node passes the answer through. With one, a report
of failing claims sends the agent back to repair them, as many times as the
configuration allows. After that, the answer stands as it is: every claim keeps
its text and gains a machine-readable mark naming its verdict, so nothing is
deleted and the interface can badge the claim instead.

The report is recorded as a step and emitted as a ``verify`` event. When the
verifier itself cannot run, the run continues and says so; a decision outage is
handled inside the verifier, which judges the claims unsupported rather than
trusting an unchecked answer.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.prompts import repair_feedback_message
from app.services.agent.state import AgentState
from app.services.agent.verification import finalize_answer

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

        repairing = report.failed and state["repair_rounds"] < deps.agent.max_repair_rounds
        payload = report.to_dict()
        payload.update({"repair": repairing, "repair_rounds": state["repair_rounds"]})
        await deps.record("verify", "verify", payload)
        await deps.event(
            Event.VERIFY,
            {
                "counts": report.counts,
                "claims": [claim.to_dict() for claim in report.claims],
                "failed": report.failed,
                "repair": repairing,
                "defaulted": report.defaulted,
            },
        )

        update: dict[str, Any] = {"verification": report}
        if repairing:
            update.update(
                {
                    "items": [
                        {
                            "role": "user",
                            "content": repair_feedback_message(report.failures),
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

        if state["answer"]:
            update["answer"] = finalize_answer(state["answer"], report)
        return update

    return verify
