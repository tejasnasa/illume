"""The merge node: one answer from every worker's findings.

The workers ran without seeing each other, so their findings can overlap or
contradict one another. One tool-free model call reads the original question,
each worker's part and findings, and the evidence they gathered together, and
writes a single cited answer. The answer becomes the run's draft, which the closing path
then takes as the answer.

A worker that failed is named in the prompt and, when the model does not name
it, in a closing note, so the gap is visible in the answer rather than silent.
The merged answer is also added to the main conversation, so an answer sent
back for more work is continued rather than started over.
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
from app.services.agent.prompts import build_merge_prompt, opening_items, with_coverage_note
from app.services.agent.state import AgentState, Plan, WorkerResult

NOTHING_MERGED = (
    "The parallel investigations produced no findings that could be combined into an answer."
)


def ordered_results(state: AgentState) -> list[WorkerResult]:
    """The workers' results in the order the plan named them."""
    plan: Plan | None = state["plan"]
    order = (
        {subquestion.id: index for index, subquestion in enumerate(plan.subquestions)}
        if plan is not None
        else {}
    )
    return sorted(
        state["worker_results"],
        key=lambda result: order.get(result.subquestion_id, len(order)),
    )


def make_merge_node(deps: AgentDeps):
    """Builds the merge node."""

    async def merge(state: AgentState) -> dict[str, Any]:
        results = ordered_results(state)
        plan = state["plan"]
        step = deps.next_step()
        started = time.perf_counter()
        prompt = build_merge_prompt(
            deps.brief,
            state["standalone_question"] or state["question"],
            results,
            state["evidence"],
            plan.synthesis_hint if plan is not None else "",
        )
        items = opening_items(prompt, [], state["question"])

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
        text = (getattr(response, "output_text", "") or "").strip() or NOTHING_MERGED
        text = with_coverage_note(text, results)
        await deps.record(
            "merge",
            "merge",
            {
                "workers": [result.to_dict() for result in results],
                "evidence_keys": list(state["evidence"]),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "chars": len(text),
            },
            index=step,
            started=started,
        )
        # The workers' conversations stay with them, so the merged answer is
        # what the main agent's conversation holds.
        return {
            "draft": text,
            "turn_end": "finish",
            "items": [{"role": "assistant", "content": text}],
        }

    return merge
