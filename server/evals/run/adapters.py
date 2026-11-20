"""The two adapters that turn a gold item and an arm into one :class:`Generation`, and ``auto``.

Single-shot arms run :func:`~app.services.retrieval.single_shot.answer`; agent arms run
:func:`~app.services.agent.runner.run_agent` with an in-memory step log and the clone-backed
tool registry. Both append the eval-only ``Files:`` instruction to the question, meter every
model call, and return a record rather than raising. A run that failed, or whose reranker
silently degraded (an arm that lost its reranker would otherwise be scored as if it had one),
is an error record and never a result.

``auto`` is composed, not generated: :func:`route_item` makes the product's routing decision for
a question and :func:`compose_auto` copies the generation of the arm that route resolves to.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass, field
from typing import Any

from openai import AsyncOpenAI

from app.services.agent.auto import FALLBACK_PRESET, resolve_auto
from app.services.agent.events import Event
from app.services.agent.runner import run_agent
from app.services.agent.steps import InMemorySteps, StepRecord
from app.services.agent.tools.context import RepoSnapshot
from app.services.agent.tools.registry import ToolRegistry
from app.services.decisions import Decider
from app.services.llm_config import LLMConfig
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.channels.base import Embedder, RetrievalContext
from app.services.retrieval.citations import parse_key
from app.services.retrieval.single_shot import answer, build_citing_prompt, build_classic_prompt
from evals.arms import (
    AUTO,
    EVAL_INSTRUCTION,
    Arm,
    get_arm,
    question_with_instruction,
)
from evals.gold.schema import GoldItem
from evals.run.metering import (
    Meter,
    costs_from_decision,
    costs_from_decisions,
    costs_from_trace,
    metered_client_factory,
    metered_rerankers,
    patched_direct_clients,
)
from evals.run.records import (
    CandidateRecord,
    ChannelHitRecord,
    Generation,
    RouteRecord,
    RunTokens,
    StepRecordOut,
    composed_record_key,
    record_key,
)

CtxFactory = Callable[[], AbstractAsyncContextManager[RetrievalContext]]
"""Opens a retrieval context (a session, the embedder) for one single-shot generation."""

RERANKER_DEGRADED = "reranker_degraded"

AUTO_ARM_BY_PRESET: dict[str, str] = {
    "hybrid_rerank": "hybrid_rerank",
    "structural": "structural_rerank",
    "deep_agent": "agent",
    "classic": "classic",
}
"""The evaluation arm that runs what each product preset runs."""

FALLBACK_ARM = AUTO_ARM_BY_PRESET[FALLBACK_PRESET]

_ERROR_CHARS = 500


def _single_shot_prompt_version() -> str:
    """A short hash of the single-shot prompt templates, so a wording change re-keys results."""
    text = build_citing_prompt("{context}") + build_classic_prompt("{question}", [])
    return "single-shot-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


SINGLE_SHOT_PROMPT_VERSION = _single_shot_prompt_version()


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:_ERROR_CHARS]


def candidate_records(candidates: Sequence[Candidate]) -> list[CandidateRecord]:
    """Candidates as records: rank, source type, file and the channels that found each."""
    records = []
    for rank, candidate in enumerate(candidates, start=1):
        path = candidate.file_path
        if path is None:
            parsed = parse_key(candidate.key)
            path = parsed.path if parsed is not None else None
        records.append(
            CandidateRecord(
                key=candidate.key,
                rank=rank,
                source_type=candidate.source_type,
                file_path=path,
                channels=[
                    ChannelHitRecord(channel=hit.channel, variant=hit.variant, rank=hit.rank)
                    for hit in candidate.channel_hits
                ],
            )
        )
    return records


def _key(item: GoldItem, arm: Arm, llm: LLMConfig, prompt_version: str | None, repeat: int) -> str:
    return record_key(
        item_id=item.id,
        question=item.question,
        repo=item.repo,
        base_commit=item.base_commit,
        arm_config_hash=arm.config_hash(),
        model=llm.model,
        prompt_version=prompt_version,
        instruction=EVAL_INSTRUCTION,
        repeat=repeat,
    )


# --- single-shot -------------------------------------------------------------------


async def run_single_shot(
    item: GoldItem,
    arm: Arm,
    *,
    ctx_factory: CtxFactory,
    llm: LLMConfig,
    meter: Meter,
    client_factory: Callable[..., Any] | None = None,
    repeat: int = 0,
    history: Sequence[Any] = (),
) -> Generation:
    """Answers one question with a single-shot arm and records everything about it.

    The generation call and every retrieval call that builds its own client are metered, and
    the reranker's reported cost is read from the retrieval trace.

    Args:
        item: The gold item; its question is sent with the eval-only instruction appended.
        arm: A generated single-shot arm.
        ctx_factory: Opens the retrieval context (session and embedder) for this generation.
        llm: The generation credential and model.
        meter: The run's meter. This generation's usage is also kept on a child of it.
        client_factory: Builds the real client; ``AsyncOpenAI`` when omitted.
        repeat: Which repeat of the pair this is.
        history: Prior turns; none for the evaluation.

    Returns:
        The generation, or an error record when the answerer raised or the reranker degraded.
    """
    config = arm.config
    if config is None or config.execution != "single_shot":
        raise ValueError(f"arm {arm.name!r} is not a single-shot arm")
    base = client_factory or AsyncOpenAI
    scope = meter.scope()
    started = time.perf_counter()
    common: dict[str, Any] = {
        "record_key": _key(item, arm, llm, SINGLE_SHOT_PROMPT_VERSION, repeat),
        "item_id": item.id,
        "arm": arm.name,
        "repeat": repeat,
        "config_hash": arm.config_hash(),
        "model": llm.model,
        "prompt_version": SINGLE_SHOT_PROMPT_VERSION,
    }

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    try:
        async with ctx_factory() as ctx:
            with patched_direct_clients(scope, base):
                result = await answer(
                    config,
                    question_with_instruction(item.question),
                    ctx=ctx,
                    history=history,
                    llm=llm,
                    client_factory=metered_client_factory(scope, base, kind="generate"),
                )
    except Exception as failure:
        return Generation(
            **common,
            status="error",
            error=_describe(failure),
            usages=scope.usages,
            unmetered_paths=scope.unmetered,
            latency_ms=elapsed(),
        )

    retrieval = result.retrieval
    trace = retrieval.trace
    scope.extend(costs_from_trace(trace))

    error: str | None = None
    if config.rerank.kind != "none" and (
        trace.reranker_degraded or (retrieval.pool and not trace.rerank_calls)
    ):
        error = RERANKER_DEGRADED

    return Generation(
        **common,
        answer=result.answer,
        cited_keys=list(result.cited_keys),
        candidates=candidate_records(retrieval.candidates),
        pool=candidate_records(retrieval.pool),
        channel_trace=[asdict(entry) for entry in trace.channels],
        degraded=[dict(entry) for entry in trace.degraded],
        usages=scope.usages,
        unmetered_paths=scope.unmetered,
        flagged=bool(trace.degraded) or bool(scope.unmetered),
        error=error,
        status="error" if error else "ok",
        latency_ms=elapsed(),
    )


# --- agent -------------------------------------------------------------------------


def step_records(steps: Sequence[StepRecord]) -> list[StepRecordOut]:
    """An agent's steps flattened for analysis.

    The tool and its arguments come from tool-call steps; the evidence keys of a step are the
    keys a tool call contributed, or the seed retrieval's keys.
    """
    records = []
    for step in steps:
        payload = step.payload
        is_tool = step.kind == "tool_call"
        keys = payload.get("evidence_keys") or (
            payload.get("keys") if step.kind == "seed" else None
        )
        status = payload.get("status")
        records.append(
            StepRecordOut(
                index=step.index,
                kind=step.kind,
                node=step.node,
                tool=str(payload["tool"]) if is_tool and payload.get("tool") else None,
                arguments=str(payload["arguments"]) if is_tool and "arguments" in payload else None,
                evidence_keys=[str(key) for key in keys or ()],
                worker_id=step.worker_id,
                duration_ms=step.duration_ms or float(payload.get("elapsed_ms") or 0.0),
                status=str(status) if status is not None else None,
            )
        )
    return records


def count_unavailable(steps: Sequence[StepRecord]) -> int:
    """Tool results whose status is ``unavailable``, whether the call or its output says so."""
    count = 0
    for step in steps:
        if step.kind != "tool_call":
            continue
        payload = step.payload
        data = payload.get("data") or {}
        if payload.get("status") == "unavailable" or data.get("status") == "unavailable":
            count += 1
    return count


def reranker_degraded_in(steps: Sequence[StepRecord], events: Sequence[Mapping[str, Any]]) -> bool:
    """Whether any retrieval inside the run reported that its reranker fell back.

    Looked for in the ``degraded`` events, in the seed step's degradation list and in
    ``search_code`` results, which list the stages that were unavailable.
    """
    if any(event.get("stage") == "rerank" for event in events):
        return True
    for step in steps:
        if step.kind == "seed":
            degraded = step.payload.get("degraded") or []
            if any(
                isinstance(entry, dict) and entry.get("stage") == "rerank" for entry in degraded
            ):
                return True
        elif step.kind == "tool_call":
            data = step.payload.get("data") or {}
            if "rerank" in (data.get("degraded") or []):
                return True
    return False


async def run_agent_arm(
    item: GoldItem,
    arm: Arm,
    *,
    repository: RepoSnapshot,
    session_factory: Any,
    llm: LLMConfig,
    meter: Meter,
    registry: ToolRegistry,
    client_factory: Callable[..., Any] | None = None,
    decider: Decider | None = None,
    embed: Embedder | None = None,
    repeat: int = 0,
    history: Sequence[Any] = (),
) -> Generation:
    """Answers one question with an agent arm and records the run.

    Args:
        item: The gold item; its question is sent with the eval-only instruction appended.
        arm: A generated agent or planner arm.
        repository: The repository snapshot the tools read.
        session_factory: Opens one database session per tool call.
        llm: The generation credential and model.
        meter: The run's meter. This generation's usage is also kept on a child of it.
        registry: The tool registry, normally from
            :func:`~evals.run.clone_tools.build_clone_registry`.
        client_factory: Builds the real client; ``AsyncOpenAI`` when omitted.
        decider: The planner's decider; the product builds its own when omitted.
        embed: The query embedder; the product's metered embedding call when omitted.
        repeat: Which repeat of the pair this is.
        history: Prior turns; none for the evaluation.

    Returns:
        The generation: the answer, every step, the product's own token counts and the metered
        usage; an error record when the run failed or a reranker inside it degraded.
    """
    config = arm.config
    if config is None or config.execution == "single_shot":
        raise ValueError(f"arm {arm.name!r} is not an agent arm")
    base = client_factory or AsyncOpenAI
    scope = meter.scope()
    steps = InMemorySteps()
    events: list[dict[str, Any]] = []

    async def emit(event: str, payload: dict[str, Any]) -> None:
        if event == Event.DEGRADED:
            events.append(dict(payload))

    started = time.perf_counter()
    prompt_version: str | None = None
    common: dict[str, Any] = {
        "item_id": item.id,
        "arm": arm.name,
        "repeat": repeat,
        "config_hash": arm.config_hash(),
        "model": llm.model,
    }

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    try:
        with patched_direct_clients(scope, base), metered_rerankers(scope):
            result = await run_agent(
                question_with_instruction(item.question),
                history,
                repository=repository,
                session_factory=session_factory,
                llm=llm,
                config=config,
                emit=emit,
                steps=steps,
                decider=decider,
                embed=embed,
                registry=registry,
                client_factory=metered_client_factory(scope, base, kind="agent"),
            )
    except Exception as failure:
        return Generation(
            **common,
            record_key=_key(item, arm, llm, prompt_version, repeat),
            status="error",
            error=_describe(failure),
            steps=step_records(steps.steps),
            usages=scope.usages,
            unmetered_paths=scope.unmetered,
            latency_ms=elapsed(),
        )

    prompt_version = result.prompt_version
    decisions = [
        step.payload for step in steps.steps if step.kind == "decision" and "point" in step.payload
    ]
    scope.extend(costs_from_decisions(decisions))
    unavailable = count_unavailable(steps.steps)

    error: str | None = None
    if result.status != "completed":
        detail = f"{result.error.kind}: {result.error.message}" if result.error else result.status
        error = detail[:_ERROR_CHARS]
    elif config.rerank.kind != "none" and reranker_degraded_in(steps.steps, events):
        error = RERANKER_DEGRADED

    return Generation(
        **common,
        record_key=_key(item, arm, llm, prompt_version, repeat),
        prompt_version=prompt_version,
        answer=result.answer,
        cited_keys=list(result.cited),
        steps=step_records(steps.steps),
        stop_reason=result.stop_reason.value,
        run_tokens=RunTokens(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
        usages=scope.usages,
        unavailable_tool_results=unavailable,
        unmetered_paths=scope.unmetered,
        flagged=unavailable > 0 or bool(scope.unmetered),
        error=error,
        status="error" if error else "ok",
        latency_ms=elapsed(),
    )


# --- auto --------------------------------------------------------------------------


def arm_for_preset(preset: str) -> str:
    """The evaluation arm that runs what the product preset ``preset`` runs.

    Raises:
        KeyError: When the product has a preset the table does not know, so a change to the
            product's routing cannot go unnoticed.
    """
    try:
        return AUTO_ARM_BY_PRESET[preset]
    except KeyError:
        raise KeyError(f"no evaluation arm for the product preset {preset!r}") from None


async def route_item(
    item: GoldItem, *, decider: Decider | None = None, timeout: float | None = None
) -> RouteRecord:
    """Makes the product's routing decision for one question.

    The question is routed as the user would have asked it, without the eval-only instruction.
    A decision that fails, times out or is not confident falls back exactly as the product does,
    to the arm that runs the product's fallback preset.

    Args:
        item: The gold item.
        decider: Who decides; the product builds its Jev decider when omitted.
        timeout: Seconds the decision may take; the product's limit when omitted.
    """
    resolved = await resolve_auto(item.question, (), decider=decider, timeout=timeout)
    usages = [costs_from_decision(resolved.decision)] if resolved.decision else []
    return RouteRecord(
        item_id=item.id,
        route=resolved.route,
        confidence=resolved.confidence,
        resolved_preset=resolved.resolved_preset,
        target_arm=arm_for_preset(resolved.resolved_preset),
        fallback_reason=resolved.fallback_reason,
        model=resolved.model,
        usages=usages,
    )


@dataclass
class AutoComposition:
    """The outcome of composing ``auto``.

    Attributes:
        generations: One ``auto`` record per routed item whose target arm has a generation.
        missing: ``(item_id, target_arm)`` pairs whose target arm has no generation yet.
    """

    generations: list[Generation] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)


def compose_auto(
    route_records: Sequence[RouteRecord],
    generations_by_item_arm: Mapping[tuple[str, str], Generation],
) -> AutoComposition:
    """Builds the ``auto`` records from the routes and the generations of the arms they pick.

    Each record is a copy of the target arm's generation with ``arm="auto"``, the route filled
    in, and the usage of the target plus the decision. Its ``composed_from`` names the target, so
    a budget does not count the target's spend twice. A target that errored stays an error. A
    target with no generation is reported in ``missing`` instead of raising.

    Args:
        route_records: One routing decision per item.
        generations_by_item_arm: Generations keyed by ``(item_id, arm_name)``.
    """
    composition = AutoComposition()
    auto = get_arm(AUTO)
    for route in route_records:
        target = generations_by_item_arm.get((route.item_id, route.target_arm))
        if target is None:
            composition.missing.append((route.item_id, route.target_arm))
            continue
        composition.generations.append(
            target.model_copy(
                update={
                    "arm": AUTO,
                    "config_hash": auto.config_hash(),
                    "record_key": composed_record_key(target.record_key, route),
                    "usages": [*target.usages, *route.usages],
                    "latency_ms": target.latency_ms + sum(u.latency_ms for u in route.usages),
                    "route": route,
                    "composed_from": route.target_arm,
                }
            )
        )
    return composition


__all__ = [
    "AUTO_ARM_BY_PRESET",
    "FALLBACK_ARM",
    "RERANKER_DEGRADED",
    "SINGLE_SHOT_PROMPT_VERSION",
    "AutoComposition",
    "arm_for_preset",
    "candidate_records",
    "compose_auto",
    "count_unavailable",
    "reranker_degraded_in",
    "route_item",
    "run_agent_arm",
    "run_single_shot",
    "step_records",
]
