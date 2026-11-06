"""The synthesize node: turns what the run gathered into the final answer.

When the agent called ``finish`` and the gate agreed, its answer is the answer
and no model call is made. In every other case (a limit was reached, the agent
wrote text instead of finishing, the gate ran out of patience) one model call
with no tools writes an answer from the evidence, saying what is missing. The
call is charged to the budget but never refused by it: it is how a run that has
used its allowance still answers, and its input is bounded by the evidence cap.
"""

from __future__ import annotations

import time
from typing import Any

from app.services.agent.deps import (
    SYNTHESIS_EFFORT,
    SYNTHESIS_MAX_OUTPUT_TOKENS,
    AgentDeps,
)
from app.services.agent.events import Event
from app.services.agent.nodes._model import stream_response, usage_of
from app.services.agent.prompts import (
    build_synthesis_prompt,
    opening_items,
    with_coverage_note,
)
from app.services.agent.state import AgentState, StopReason

NOTHING_WRITTEN = (
    "I could not write an answer from the evidence gathered. Ask again, or narrow the question."
)


async def write_answer(deps: AgentDeps, state: AgentState, reason: StopReason) -> str:
    """Writes the closing answer with one tool-free model call.

    Args:
        deps: The run's collaborators.
        state: The state to answer from.
        reason: Why the investigation ended, which the prompt explains to the model.
    """
    step = deps.next_step()
    started = time.perf_counter()
    prompt = build_synthesis_prompt(deps.brief, state["evidence"], reason.value)
    keep = deps.config.query.history_messages
    items = opening_items(prompt, state["history"][-keep:] if keep else [], state["question"])

    async def delta(text: str) -> None:
        await deps.event(Event.ANSWER_DELTA, {"text": text})

    response = await stream_response(
        deps.client,
        delta,
        model=deps.llm.model,
        input=items,
        max_output_tokens=SYNTHESIS_MAX_OUTPUT_TOKENS,
        **deps.llm.response_kwargs(SYNTHESIS_EFFORT),
    )
    input_tokens, output_tokens = usage_of(response)
    await deps.budget.add_usage(input_tokens, output_tokens)
    text = (getattr(response, "output_text", "") or "").strip()
    await deps.record(
        "synthesize",
        "synthesize",
        {
            "reason": reason.value,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "evidence_keys": list(state["evidence"]),
            "chars": len(text),
        },
        index=step,
        started=started,
    )
    return text or NOTHING_WRITTEN


def make_synthesize_node(deps: AgentDeps):
    """Builds the synthesize node."""

    async def synthesize(state: AgentState) -> dict[str, Any]:
        reason = state["stop_reason"] or StopReason.TEXT_REPLY
        if reason is StopReason.FINISHED and state["draft"]:
            answer = state["draft"]
        else:
            answer = await write_answer(deps, state, reason)
        # A worker that failed leaves a gap the answer must name, not hide.
        return {
            "answer": with_coverage_note(answer, state["worker_results"]),
            "stop_reason": reason,
        }

    return synthesize
