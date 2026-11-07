"""One worker: the agent loop, restricted to a single sub-question.

A worker is the same loop the single agent runs, compiled on its own so it has
its own conversation, its own turn count and its own copy of the state. It
starts from the retrieval the run did once before fanning out, plus its part of
the question, and ends when it calls ``finish`` or reaches a limit.

Workers share the run's budget object and nothing else: the tool-call, token and
wall-clock limits are charged under one lock, so two workers can never both
spend the last tool call. A worker that fails or times out does not fail the
run. It returns the evidence it gathered and a result naming why it stopped,
and the other workers carry on into the merge.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.services.agent.deps import AgentDeps
from app.services.agent.errors import describe_error
from app.services.agent.events import Event
from app.services.agent.nodes._model import message_text
from app.services.agent.nodes.agent import make_agent_node
from app.services.agent.nodes.planner import worker_agent_settings
from app.services.agent.nodes.tools import make_tools_node
from app.services.agent.prompts import worker_message
from app.services.agent.state import (
    AgentState,
    Evidence,
    StopReason,
    SubQuestion,
    WorkerResult,
    WorkerStatus,
    initial_state,
)
from app.services.retrieval.channels.base import Emit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerInput:
    """What the graph sends one worker.

    Attributes:
        worker_id: The worker's id within the run.
        subquestion: The part of the question this worker investigates.
        items: The shared opening conversation, with the seed already in it and
            the worker's own instruction appended.
        evidence: The evidence the run had gathered before fanning out.
        question: The standalone question the plan was made for.
    """

    worker_id: str
    subquestion: SubQuestion
    items: list[dict[str, Any]]
    evidence: dict[str, Evidence]
    question: str

    def __hash__(self) -> int:
        # The payload holds lists and dicts; its id is what makes it unique.
        return hash(self.worker_id)


def _tagged(emit: Emit, worker_id: str) -> Emit:
    """An emitter that adds the worker's id to every payload."""

    async def tagged(event: str, payload: dict[str, Any]) -> None:
        await emit(event, {**payload, "worker_id": worker_id})

    return tagged


def _worker_deps(deps: AgentDeps, worker_id: str) -> AgentDeps:
    """The run's collaborators, restricted to one worker."""
    tool_ctx = replace(
        deps.tool_ctx,
        worker_id=worker_id,
        emit=_tagged(deps.tool_ctx.emit, worker_id),
    )
    return AgentDeps(
        config=deps.config,
        agent=worker_agent_settings(deps),
        llm=deps.llm,
        client=deps.client,
        tool_ctx=tool_ctx,
        registry=deps.registry,
        brief=deps.brief,
        budget=deps.budget,
        emit=deps.emit,
        steps=deps.steps,
        system_prompt=deps.system_prompt,
        decider=deps.decider,
        verifier=deps.verifier,
        screen=deps.screen,
        round_screen=deps.round_screen,
        worker_id=worker_id,
        step_counter=deps.step_counter,
    )


def _instrumented(
    deps: AgentDeps, name: str, node: Callable[[AgentState], Awaitable[dict[str, Any]]]
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Wraps a node so its start and end land in the worker's lane."""

    async def run(state: AgentState) -> dict[str, Any]:
        await deps.event(Event.NODE, {"node": name, "phase": "started"})
        update = await node(state)
        await deps.event(Event.NODE, {"node": name, "phase": "done"})
        return update

    return run


def _after_agent(state: AgentState) -> str:
    if state["turn_end"] == "tools":
        return "tools"
    if state["turn_end"] == "nudge":
        return "agent"
    return END


def _after_tools(state: AgentState) -> str:
    if state["stop_reason"] is not None or state["turn_end"] == "finish":
        return END
    return "agent"


def build_worker_graph(deps: AgentDeps):
    """Compiles the agent loop as a subgraph for one worker.

    The loop is the same one the single agent runs: a model turn, its tool
    calls, and back. It ends on ``finish``, a limit, a plain-text answer or the
    graph's step limit; the gate and the closing answer belong to the run, not
    to a worker.

    Args:
        deps: The worker's own collaborators.
    """
    graph = StateGraph(AgentState)
    agent = _instrumented(deps, "agent", make_agent_node(deps))
    tools = _instrumented(deps, "tools", make_tools_node(deps))
    graph.add_node("agent", cast(Any, agent))
    graph.add_node("tools", cast(Any, tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _after_agent, ["tools", "agent", END])
    graph.add_conditional_edges("tools", _after_tools, ["agent", END])
    return graph.compile()


def _text_answer(state: AgentState) -> str:
    """The last assistant message, when the model answered in plain text."""
    if state["turn_end"] != "text":
        return ""
    for item in reversed(state["items"]):
        if item.get("type") == "message":
            text = message_text([item]).strip()
            if text:
                return text
    return ""


def _partial_answer(state: AgentState, stop: StopReason) -> str:
    """A summary of what a worker gathered when it never wrote an answer."""
    keys = list(state["evidence"])
    if not keys:
        return f"No answer was written: the investigation stopped ({stop.value})."
    listed = ", ".join(keys[:20])
    more = f" and {len(keys) - 20} more" if len(keys) > 20 else ""
    return (
        f"No answer was written: the investigation stopped ({stop.value}). "
        f"Evidence gathered: {listed}{more}."
    )


def _worker_status(stop: StopReason) -> WorkerStatus:
    """How a worker that ran to its own end is reported."""
    if stop in (StopReason.FINISHED, StopReason.TEXT_REPLY):
        return "completed"
    return "partial"


async def _run(deps: AgentDeps, payload: WorkerInput) -> tuple[WorkerResult, dict[str, Evidence]]:
    """Runs one worker and returns its result whatever happens inside it."""
    graph = build_worker_graph(deps)
    state = initial_state(payload.subquestion.question, [], payload.items)
    state["evidence"] = dict(payload.evidence)

    latest: AgentState = state
    stop: StopReason = StopReason.TEXT_REPLY
    status: WorkerStatus = "completed"
    failure: str | None = None
    try:
        # Imported here: the graph module builds this one, so a module-level
        # import would close the cycle.
        from app.services.agent.graph import recursion_limit

        async for snapshot in graph.astream(
            state,
            {"recursion_limit": recursion_limit(deps.agent.max_iterations)},
            stream_mode="values",
        ):
            latest = snapshot
        stop = latest["stop_reason"] or (
            StopReason.FINISHED if latest["draft"] else StopReason.TEXT_REPLY
        )
        status = _worker_status(stop)
    except asyncio.CancelledError:
        raise
    except GraphRecursionError:
        stop = StopReason.RECURSION
        status = "partial"
    except TimeoutError:
        stop = StopReason.MAX_SECONDS
        status = "timed_out"
        await _announce_failure(deps, payload, "timeout", "the worker timed out")
    except Exception as error:
        stop = StopReason.ERROR
        status = "failed"
        run_error = describe_error(error)
        failure = f"{run_error.kind}: {run_error.message}"
        if run_error.kind == "internal":
            logger.exception("worker %s failed", payload.worker_id)
        await deps.record(
            "error",
            "worker",
            {
                "kind": run_error.kind,
                "message": run_error.message,
                "exception": run_error.exception,
                "status": run_error.status,
            },
        )
        await _announce_failure(deps, payload, run_error.kind, run_error.message)

    answer = (latest["draft"] or "").strip() or _text_answer(latest)
    if not answer:
        answer = _partial_answer(latest, stop)
    result = WorkerResult(
        worker_id=payload.worker_id,
        subquestion_id=payload.subquestion.id,
        question=payload.subquestion.question,
        focus=payload.subquestion.focus,
        status=status,
        stop_reason=stop,
        answer=answer,
        evidence_keys=tuple(latest["evidence"]),
        iterations=latest["iteration"],
        error=failure,
    )
    return result, dict(latest["evidence"])


async def _announce_failure(deps: AgentDeps, payload: WorkerInput, kind: str, message: str) -> None:
    """Reports a worker that could not finish, without failing the run."""
    await deps.event(
        Event.WORKER_FAILED,
        {
            "worker_id": payload.worker_id,
            "subquestion": payload.subquestion.question,
            "kind": kind,
            "message": message,
        },
    )


def make_worker_node(deps: AgentDeps):
    """Builds the node the graph fans out to, one invocation per sub-question."""

    async def worker(payload: WorkerInput) -> dict[str, Any]:
        worker_deps = _worker_deps(deps, payload.worker_id)
        step = deps.next_step()
        started = time.perf_counter()
        await worker_deps.event(Event.NODE, {"node": "worker", "phase": "started"})
        result, evidence = await _run(worker_deps, payload)
        await worker_deps.record("worker", "worker", result.to_dict(), index=step, started=started)
        await worker_deps.event(
            Event.NODE,
            {
                "node": "worker",
                "phase": "done",
                "status": result.status,
                "stop_reason": result.stop_reason.value,
            },
        )
        return {"evidence": evidence, "worker_results": [result]}

    return worker


def worker_items(
    items: list[dict[str, Any]], subquestion: SubQuestion, question: str
) -> list[dict[str, Any]]:
    """The shared opening conversation with the worker's instruction appended."""
    return [
        *items,
        {
            "role": "user",
            "content": worker_message(question, subquestion.focus, subquestion.question),
        },
    ]
