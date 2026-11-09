"""The planner node: splits a question into the investigations that answer it.

Planning is optional. When the run has a decider it is first asked whether the
question needs several independent investigations at all; a question it judges
simple goes straight to the single agent, which keeps the common case fast even
with parallel execution switched on. One structured model call then writes the
plan, and the graph fans out to it.

A plan that cannot be written, or that comes back too small to be worth running,
is not an error: the node reports that planning was skipped and the single agent
answers.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.nodes._model import usage_of
from app.services.agent.prompts import plan_user, planner_system
from app.services.agent.state import AgentState, Plan, SubQuestion
from app.services.decisions import decide_plan
from app.services.retrieval.config import AgentConfig, PlannerConfig
from app.services.retrieval.llm_json import call_json_response

logger = logging.getLogger(__name__)

FOCUSES: frozenset[str] = frozenset({"code", "graph", "history"})

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subquestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "focus": {"type": "string", "enum": ["code", "graph", "history"]},
                },
                "required": ["question", "focus"],
                "additionalProperties": False,
            },
        },
        "synthesis_hint": {"type": "string"},
    },
    "required": ["subquestions", "synthesis_hint"],
    "additionalProperties": False,
}


def worker_id(position: int) -> str:
    """The id of the worker that takes the sub-question at ``position`` (from 1)."""
    return f"w{position}"


def parse_plan(value: Any, *, max_workers: int, min_subquestions: int) -> Plan | None:
    """Turns a parsed model answer into a plan, or ``None`` when it is unusable.

    Empty questions are dropped, an unknown focus becomes ``code``, and a plan
    longer than ``max_workers`` is cut to it. A plan with fewer than
    ``min_subquestions`` entries is not worth fanning out.

    Each sub-question is numbered ``w1``, ``w2``, ... in order, which is the id
    of the worker that will take it, so the plan and the workers' own events
    name the same lane.

    Args:
        value: The parsed JSON value the model returned.
        max_workers: The most sub-questions a plan may hold.
        min_subquestions: The fewest a plan needs to run.
    """
    if not isinstance(value, dict):
        return None
    raw = value.get("subquestions")
    if not isinstance(raw, list):
        return None

    subquestions: list[SubQuestion] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question = entry.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        focus = entry.get("focus")
        subquestions.append(
            SubQuestion(
                id=worker_id(len(subquestions) + 1),
                question=question.strip(),
                focus=focus if focus in FOCUSES else "code",
            )
        )
        if len(subquestions) >= max_workers:
            break

    if len(subquestions) < min_subquestions:
        return None
    hint = value.get("synthesis_hint")
    return Plan(
        subquestions=tuple(subquestions),
        synthesis_hint=hint.strip() if isinstance(hint, str) else "",
    )


def make_planner_node(deps: AgentDeps):
    """Builds the planner node."""

    async def skip(reason: str) -> dict[str, Any]:
        payload = {"skipped": True, "reason": reason}
        await deps.event(Event.PLAN, payload)
        return {"plan": None}

    async def planner(state: AgentState) -> dict[str, Any]:
        settings = deps.config.planner
        assert settings is not None
        question = state["standalone_question"] or state["question"]

        decision = None
        if deps.decider is not None:
            try:
                decision = await decide_plan(
                    deps.decider,
                    question,
                    threshold=settings.plan_threshold,
                    record=deps.decision_sink("planner"),
                )
            except Exception as error:
                # A pre-check that cannot answer must not stop the run.
                reason = f"{type(error).__name__}: {error}"[:300]
                logger.warning("the planning check failed: %s", reason)
                await deps.event(Event.DEGRADED, {"stage": "planner", "reason": reason})
        if decision is not None and not decision.plan:
            await deps.event(
                Event.PLAN,
                {
                    "skipped": True,
                    "reason": "pre_check",
                    "probability": decision.probability,
                    "threshold": decision.threshold,
                    "model": decision.model,
                },
            )
            return {"plan": None}

        step = deps.next_step()
        started = time.perf_counter()
        try:
            parsed, response = await call_json_response(
                deps.client,
                deps.llm,
                system=planner_system(
                    max_workers=settings.max_workers,
                    min_subquestions=settings.min_subquestions,
                ),
                user=plan_user(
                    deps.brief,
                    question,
                    max_workers=settings.max_workers,
                    min_subquestions=settings.min_subquestions,
                ),
                format_name="plan",
                schema=PLAN_SCHEMA,
            )
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"[:300]
            logger.warning("planning failed: %s", reason)
            await deps.event(Event.DEGRADED, {"stage": "planner", "reason": reason})
            await deps.record(
                "plan",
                "planner",
                {"skipped": True, "reason": "model_failure", "error": reason},
                index=step,
                started=started,
            )
            return await skip("model_failure")

        input_tokens, output_tokens = usage_of(response)
        await deps.budget.add_usage(input_tokens, output_tokens)
        plan = parse_plan(
            parsed,
            max_workers=settings.max_workers,
            min_subquestions=settings.min_subquestions,
        )
        if plan is None:
            await deps.record(
                "plan",
                "planner",
                {
                    "skipped": True,
                    "reason": "too_few_subquestions",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                index=step,
                started=started,
            )
            return await skip("too_few_subquestions")

        model = str(getattr(response, "model", "") or "")
        plan = Plan(
            subquestions=plan.subquestions,
            synthesis_hint=plan.synthesis_hint,
            model=model,
        )
        await deps.record(
            "plan",
            "planner",
            {
                "skipped": False,
                "subquestions": [sub.to_dict() for sub in plan.subquestions],
                "synthesis_hint": plan.synthesis_hint,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": model,
            },
            index=step,
            started=started,
        )
        await deps.event(Event.PLAN, {"skipped": False, **plan.to_dict()})
        return {"plan": plan}

    return planner


def worker_agent_settings(deps: AgentDeps) -> AgentConfig:
    """The agent settings one worker runs under.

    The only difference from the run's settings is the turn limit, which a
    worker takes from the planner. Every worker keeps the run's context window,
    so compaction behaves the same wherever the loop runs.

    Args:
        deps: The run's collaborators.
    """
    settings = deps.config.planner
    assert isinstance(settings, PlannerConfig)
    return deps.agent.model_copy(update={"max_iterations": settings.worker_iterations})
