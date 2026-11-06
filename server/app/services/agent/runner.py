"""Running one agent investigation end to end.

:func:`run_agent` is the single entry point. A streaming route, the evaluation
and the tests all call it; the route adds HTTP concerns around it and nothing
else does. It builds the run's collaborators, runs the graph under a hard
wall-clock limit, and turns every way a run can end into a :class:`RunResult`:

* a normal finish, or a limit that sent the run to its closing answer;
* a model call that failed, which becomes a failed result and an ``error``
  event with the message the chat endpoint would give the same failure;
* the graph's own step limit, which still produces an answer;
* the hard time limit, which answers from what was found without a model call;
* cancellation, which marks the run cancelled and re-raises so the caller's
  task ends as cancelled.

Whatever steps were taken before a failure stay in the step log.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.errors import GraphRecursionError
from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import File, Repository
from app.services.agent.budgets import RunBudget
from app.services.agent.deps import AgentDeps, ResultScreen, Verifier
from app.services.agent.errors import RunError, describe_error
from app.services.agent.events import Event, safe_emit
from app.services.agent.graph import build_graph, recursion_limit
from app.services.agent.nodes.merge import ordered_results
from app.services.agent.nodes.synthesize import write_answer
from app.services.agent.prompts import PROMPT_VERSION, RepoBrief, build_system_prompt, opening_items
from app.services.agent.state import (
    ChatTurn,
    Evidence,
    Plan,
    StopReason,
    WorkerResult,
    initial_state,
    resolve_citations,
)
from app.services.agent.steps import InMemorySteps, StepRecord, StepRecorder
from app.services.agent.tools import REGISTRY
from app.services.agent.tools.context import RepoSnapshot, ToolContext
from app.services.agent.tools.registry import ToolRegistry
from app.services.decisions import (
    Decider,
    DeciderUnavailable,
    RouteDecision,
    get_decider,
)
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import Embedder, Emit
from app.services.retrieval.config import AgentConfig, PipelineConfig
from app.services.retrieval.embedding import embed_texts
from app.services.retrieval.query import HistoryMessage

logger = logging.getLogger(__name__)

RunStatus = Literal["completed", "failed", "cancelled"]

ClientFactory = Callable[..., Any]
"""Builds the model client from ``AsyncOpenAI``-style keyword arguments."""

TIMED_OUT_ANSWER = (
    "The investigation ran out of time before an answer could be written. "
    "What was found is listed below; ask again, or narrow the question."
)


@dataclass(frozen=True)
class RunResult:
    """How a run ended.

    Attributes:
        run_id: The run's id.
        status: ``completed`` for any run that produced an answer, ``failed``
            when a model call failed, ``cancelled`` when the caller cancelled.
        stop_reason: Why the loop ended.
        answer: The final answer; empty for a failed or cancelled run.
        confidence_note: What the agent said was uncertain, when it said anything.
        cited: Evidence keys the answer cites, in order of first citation.
        unresolved: Cited keys, as written, that match nothing the run saw.
        evidence: Everything the run saw, by key.
        iterations: Model turns taken.
        tool_calls: Tool calls started.
        input_tokens: Input tokens the providers reported.
        output_tokens: Output tokens the providers reported.
        elapsed_seconds: Wall time of the run.
        limits_reached: The limits the run hit, in order.
        prompt_version: The prompt wording the run used.
        config_hash: :meth:`PipelineConfig.config_hash` of the configuration.
        limits: The limits in force, including the caller's input token limit.
        model: The generation model.
        route: The routing decision that chose this graph, when there was one.
        plan: The sub-questions the run was split into, when it was.
        workers: What each worker found, in plan order.
        error: Why the run failed, when it did.
    """

    run_id: uuid.UUID
    status: RunStatus
    stop_reason: StopReason
    answer: str
    confidence_note: str | None = None
    cited: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    evidence: dict[str, Evidence] = field(default_factory=dict)
    iterations: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    limits_reached: tuple[str, ...] = ()
    prompt_version: str = PROMPT_VERSION
    config_hash: str = ""
    limits: dict[str, int] = field(default_factory=dict)
    model: str = ""
    route: RouteDecision | None = None
    plan: Plan | None = None
    workers: tuple[WorkerResult, ...] = ()
    error: RunError | None = None


# --- the repository brief -----------------------------------------------------------


def _stack_phrase(stack: Any) -> str:
    """A detected stack as a short phrase, whatever shape ingestion stored."""
    if not stack:
        return ""
    if isinstance(stack, str):
        return stack
    if isinstance(stack, dict):
        parts: list[str] = []
        for value in stack.values():
            if isinstance(value, list | tuple):
                parts.extend(str(item) for item in value)
            elif value:
                parts.append(str(value))
        return ", ".join(dict.fromkeys(parts))
    if isinstance(stack, list | tuple):
        return ", ".join(str(item) for item in stack)
    return str(stack)


async def load_repo_brief(
    session_factory: async_sessionmaker[AsyncSession], repository: RepoSnapshot
) -> RepoBrief:
    """Reads the repository facts the system prompt shows."""
    async with session_factory() as db:
        row = (
            await db.execute(select(Repository).where(Repository.id == repository.id))
        ).scalar_one_or_none()
        file_count = (
            await db.execute(
                select(func.count()).select_from(File).where(File.repository_id == repository.id)
            )
        ).scalar_one()
        if row is None:
            return RepoBrief(name=repository.github_url, github_url=repository.github_url)
        entries: list[Any] = row.entry_points if isinstance(row.entry_points, list) else []
        return RepoBrief(
            name=row.name,
            github_url=row.github_url,
            primary_language=row.primary_language,
            stack=_stack_phrase(row.detected_stack),
            entry_points=tuple(str(entry) for entry in entries),
            file_count=int(file_count),
            branch=repository.ingested_branch,
            commit=repository.ingested_commit_sha,
        )


# --- the run -------------------------------------------------------------------------


def _effective_agent(config: PipelineConfig, context_window: int | None) -> AgentConfig:
    """The agent limits with the caller's context window applied.

    Raises:
        ValueError: When the preset has no agent settings.
        pydantic.ValidationError: When the window is outside what a run may be given.
    """
    if config.agent is None:
        raise ValueError(f"preset {config.name!r} has no agent settings")
    if context_window is None:
        return config.agent
    AgentConfig(context_window=context_window)  # validates the range
    return config.agent.model_copy(update={"context_window": context_window})


def _build_decider(
    config: PipelineConfig, llm: LLMConfig, emit: Emit, run_id: uuid.UUID
) -> Decider | None:
    """The run's decider, or ``None`` when no decision is configured to run.

    Planning asks its own question even when the sufficiency gate is off, so
    planner execution builds a decider either way.
    """
    if not config.checks.gate and config.execution != "planner":
        return None
    try:
        return get_decider(config.decider, llm=llm, emit=emit, session_id=str(run_id))
    except DeciderUnavailable:
        return None


async def run_agent(
    question: str,
    history: Sequence[HistoryMessage],
    *,
    repository: RepoSnapshot,
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMConfig,
    config: PipelineConfig,
    context_window: int | None = None,
    github_token: str | None = None,
    emit: Emit | None = None,
    steps: StepRecorder | None = None,
    run_id: uuid.UUID | None = None,
    route: RouteDecision | None = None,
    decider: Decider | None = None,
    embed: Embedder | None = None,
    brief: RepoBrief | None = None,
    verifier: Verifier | None = None,
    screen: ResultScreen | None = None,
    registry: ToolRegistry | None = None,
    client_factory: ClientFactory | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RunResult:
    """Answers a question about a repository by exploring it with tools.

    The caller resolves everything that belongs to a user (the credential, the
    GitHub token, the context window) and passes it as plain values, so no
    ORM instance is carried into the run.

    Args:
        question: The question as typed.
        history: Earlier turns, oldest first.
        repository: The repository to explore. Only its rows are readable.
        session_factory: Opens one database session per tool call.
        llm: The generation credential.
        config: The configuration; it must use agent execution.
        context_window: Input tokens one model call may carry. Callers pass the
            user's own window (see
            :func:`~app.services.agent.budgets.context_window_for`); ``None``
            keeps the configuration's.
        github_token: The repository owner's GitHub token, for ``read_file``.
        emit: Receives the run's events.
        steps: Receives the run's steps; an in-memory log by default.
        run_id: The run's id; generated when omitted.
        route: The routing decision that chose this configuration, if one was made.
        decider: Makes the gate's decisions; built from ``config.decider`` when
            the gate is on and none is given.
        embed: Embeds query text for the tools; the operator's embedding call by default.
        brief: Repository facts for the prompt; read from the database when omitted.
        verifier: Checks the answer's citations; none by default.
        screen: Inspects tool results before the model sees them; none by default.
        registry: The tools; the shared registry by default.
        client_factory: Builds the model client; ``AsyncOpenAI`` by default.
        clock: Monotonic seconds, for the budget.

    Returns:
        How the run ended. Model failures are returned as a failed result rather
        than raised.

    Raises:
        asyncio.CancelledError: When the run is cancelled, after it has been
            marked cancelled.
        ValueError: When ``config`` has no agent settings.
    """
    run_id = run_id or uuid.uuid4()
    sink: Emit = emit if emit is not None else _discard
    recorder: StepRecorder = steps if steps is not None else InMemorySteps()
    agent_config = _effective_agent(config, context_window)

    budget = RunBudget(agent_config, emit=sink, clock=clock)
    the_brief = brief or await load_repo_brief(session_factory, repository)
    the_decider = decider if decider is not None else _build_decider(config, llm, sink, run_id)
    if config.checks.gate and the_decider is None:
        await safe_emit(
            sink,
            Event.DEGRADED,
            {"stage": "gate", "reason": "no decider is available; the sufficiency check is off"},
        )

    tool_ctx = ToolContext(
        run_id=run_id,
        repository=repository,
        session_factory=session_factory,
        llm=llm,
        pipeline=config,
        github_token=github_token,
        decider=the_decider,
        budget=budget,
        emit=sink,
        embed=embed or embed_texts,
    )
    factory = client_factory if client_factory is not None else AsyncOpenAI
    deps = AgentDeps(
        config=config,
        agent=agent_config,
        llm=llm,
        client=factory(**llm.client_kwargs()),
        tool_ctx=tool_ctx,
        registry=registry or REGISTRY,
        brief=the_brief,
        budget=budget,
        emit=sink,
        steps=recorder,
        system_prompt=build_system_prompt(the_brief),
        decider=the_decider,
        verifier=verifier,
        screen=screen,
    )
    turns = [ChatTurn(role=m.role, content=m.content) for m in history]  # type: ignore[arg-type]
    replayed = turns[-config.query.history_messages :] if config.query.history_messages else []
    state = initial_state(
        question,
        turns,
        opening_items(deps.system_prompt, replayed, question),
        route=route,
    )
    limits = {
        "max_iterations": agent_config.max_iterations,
        "max_tool_calls": agent_config.max_tool_calls,
        "max_seconds": agent_config.max_seconds,
        "hard_cancel_seconds": agent_config.hard_cancel_seconds,
        "max_input_tokens": agent_config.max_input_tokens,
        "context_window": agent_config.context_window,
    }
    if config.planner is not None:
        limits["max_workers"] = config.planner.max_workers
        limits["worker_iterations"] = config.planner.worker_iterations
    await safe_emit(
        sink,
        Event.RUN_STARTED,
        {
            "run_id": str(run_id),
            "model": llm.model,
            "prompt_version": PROMPT_VERSION,
            "config_hash": config.config_hash(),
            "limits": limits,
        },
    )

    latest = state
    stop: StopReason | None = None
    failure: RunError | None = None
    answer: str | None = None
    graph = build_graph(deps)

    hard_limit = asyncio.timeout(agent_config.hard_cancel_seconds)
    try:
        async with hard_limit:
            try:
                async for snapshot in graph.astream(
                    state,
                    {"recursion_limit": recursion_limit(agent_config.max_iterations)},
                    stream_mode="values",
                ):
                    latest = snapshot
            except GraphRecursionError:
                stop = StopReason.RECURSION
                answer = await write_answer(deps, latest, StopReason.RECURSION)
    except asyncio.CancelledError:
        result = await _result(
            deps, run_id, config, limits, latest, "cancelled", StopReason.CANCELLED, "", None
        )
        await _finish(deps, result)
        raise
    except Exception as error:
        if isinstance(error, TimeoutError) and hard_limit.expired():
            stop = StopReason.HARD_TIMEOUT
            answer = _timed_out_answer(latest)
            await safe_emit(
                sink,
                Event.DEGRADED,
                {
                    "stage": "budget",
                    "limit": "hard_cancel_seconds",
                    "used": round(budget.elapsed(), 1),
                    "allowed": agent_config.hard_cancel_seconds,
                },
            )
        else:
            failure = describe_error(error)
            stop = StopReason.ERROR
            answer = ""
            if failure.kind == "internal":
                logger.exception("agent run %s failed", run_id)
            await recorder.record(
                StepRecord(
                    index=deps.next_step(),
                    kind="error",
                    node="runner",
                    payload={
                        "kind": failure.kind,
                        "message": failure.message,
                        "exception": failure.exception,
                        "status": failure.status,
                    },
                )
            )
            await safe_emit(
                sink,
                Event.ERROR,
                {"kind": failure.kind, "message": failure.message, "status": failure.status},
            )

    if stop is None:
        stop = latest["stop_reason"] or StopReason.TEXT_REPLY
        answer = latest["answer"] or ""

    status: RunStatus = "failed" if failure is not None else "completed"
    result = await _result(
        deps, run_id, config, limits, latest, status, stop, answer or "", failure
    )
    if status == "completed":
        await safe_emit(
            sink,
            Event.ANSWER,
            {
                "text": result.answer,
                "cited": list(result.cited),
                "unresolved": list(result.unresolved),
                "stop_reason": result.stop_reason.value,
                "confidence_note": result.confidence_note,
            },
        )
    await _finish(deps, result)
    return result


async def _discard(event: str, payload: dict[str, Any]) -> None:
    """The default emitter, for callers that do not stream progress."""


def _timed_out_answer(state: Any) -> str:
    """The answer of a run cancelled at the hard limit: the evidence, unsummarised."""
    keys = list(state["evidence"])
    if not keys:
        return TIMED_OUT_ANSWER
    listed = "\n".join(f"- [{key}]" for key in keys[:30])
    return f"{TIMED_OUT_ANSWER}\n\n{listed}"


async def _result(
    deps: AgentDeps,
    run_id: uuid.UUID,
    config: PipelineConfig,
    limits: dict[str, int],
    state: Any,
    status: RunStatus,
    stop: StopReason,
    answer: str,
    error: RunError | None,
) -> RunResult:
    usage = await deps.budget.snapshot()
    citations = resolve_citations(answer, state["evidence"]) if answer else None
    plan = state["plan"]
    workers = tuple(ordered_results(state))
    return RunResult(
        run_id=run_id,
        status=status,
        stop_reason=stop,
        answer=answer,
        confidence_note=state["confidence_note"],
        cited=citations.cited if citations else (),
        unresolved=citations.unresolved if citations else (),
        evidence=dict(state["evidence"]),
        iterations=state["iteration"] + sum(worker.iterations for worker in workers),
        tool_calls=usage.tool_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        elapsed_seconds=usage.elapsed_seconds,
        limits_reached=usage.reached,
        prompt_version=PROMPT_VERSION,
        config_hash=config.config_hash(),
        limits=limits,
        model=deps.llm.model,
        route=state["route"],
        plan=plan,
        workers=workers,
        error=error,
    )


async def _finish(deps: AgentDeps, result: RunResult) -> None:
    """Writes the outcome to the step log and announces that the run ended."""
    try:
        await deps.steps.finish(result)
    except Exception:
        logger.warning("recording the end of run %s failed", result.run_id, exc_info=True)
    await safe_emit(
        deps.emit,
        Event.RUN_FINISHED,
        {
            "run_id": str(result.run_id),
            "status": result.status,
            "stop_reason": result.stop_reason.value,
            "iterations": result.iterations,
            "tool_calls": result.tool_calls,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "elapsed_seconds": result.elapsed_seconds,
        },
    )
