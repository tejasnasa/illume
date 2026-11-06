"""The gate node: asks whether the evidence is enough before the agent may answer.

It runs when the agent has finished, or has replied in plain text, and there is
evidence to judge. The decider only says whether the evidence suffices; when it
does not, the agent is sent back to name the gap itself. The number of times
the gate may send the agent back is capped, so it cannot trap the loop.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.nodes.agent import limit_reached
from app.services.agent.prompts import gate_feedback_message
from app.services.agent.state import AgentState, StopReason
from app.services.decisions import decide_sufficiency

logger = logging.getLogger(__name__)


def make_gate_node(deps: AgentDeps):
    """Builds the gate node."""

    async def gate(state: AgentState) -> dict[str, Any]:
        finishing = state["turn_end"] == "finish"
        accepted = StopReason.FINISHED if finishing else StopReason.TEXT_REPLY

        judging = deps.config.checks.gate and deps.decider is not None and bool(state["evidence"])
        if not judging:
            return {"stop_reason": accepted}

        if state["gate_rejections"] >= deps.agent.max_gate_rejections:
            await deps.event(
                Event.GATE,
                {"verdict": "exhausted", "rejections": state["gate_rejections"]},
            )
            return {"stop_reason": StopReason.GATE_EXHAUSTED, "draft": None}

        assert deps.decider is not None
        step = deps.next_step()
        try:
            decision = await decide_sufficiency(
                deps.decider,
                state["standalone_question"],
                {key: item.text for key, item in state["evidence"].items()},
                threshold=deps.config.checks.sufficiency_threshold,
                record=deps.decision_sink("gate"),
            )
        except Exception as error:
            # A gate that cannot answer must not block an answer.
            reason = f"{type(error).__name__}: {error}"[:300]
            logger.warning("the sufficiency check failed: %s", reason)
            await deps.event(Event.DEGRADED, {"stage": "gate", "reason": reason})
            return {"stop_reason": accepted}

        payload = {
            "verdict": "sufficient" if decision.sufficient else "insufficient",
            "probability": decision.probability,
            "threshold": decision.threshold,
            "evidence_items": decision.evidence_items,
            "rejections": state["gate_rejections"],
            "defaulted": decision.defaulted,
        }
        await deps.record("gate", "gate", payload, index=step)
        await deps.event(Event.GATE, payload)

        if decision.sufficient:
            return {"stop_reason": accepted}

        stopped = await limit_reached(deps, state)
        if stopped is not None:
            return {"stop_reason": stopped, "draft": None}

        feedback = gate_feedback_message(decision.probability)
        return {
            "items": [{"role": "user", "content": feedback}],
            "gate_feedback": feedback,
            "gate_rejections": state["gate_rejections"] + 1,
            "draft": None,
            "turn_end": None,
        }

    return gate
