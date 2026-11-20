"""The records one generation writes, as plain JSON-serialisable models.

A :class:`Generation` is everything later stages need from one answer: what was retrieved and in
what order, what each channel contributed, the agent's steps, the metered usage, and whether the
run may be scored at all. A run that failed, or whose reranker silently degraded, is a record
with ``status="error"`` and never a score of zero.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

UsageKind = Literal[
    "generate", "rewrite", "hyde", "embed", "rerank", "decision", "agent", "judge", "other"
]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Usage(_Record):
    """One metered call to a provider.

    Attributes:
        provider: Who answered: a host name, or ``openai`` for the SDK's default endpoint.
        model: The model the response reported, or the one asked for when it reported none.
        kind: What the call was for.
        input_tokens: Input tokens, cached ones included.
        cached_input_tokens: How many of the input tokens were served from the provider's cache.
        output_tokens: Output tokens.
        reported_cost_usd: The cost the provider reported, when it reported one.
        latency_ms: Wall time of the call.
    """

    provider: str
    model: str
    kind: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reported_cost_usd: float | None = None
    latency_ms: float = 0.0


class ChannelHitRecord(_Record):
    """Where one channel ranked a candidate."""

    channel: str
    variant: int
    rank: int


class CandidateRecord(_Record):
    """One retrieved candidate with its rank and which channels found it.

    Attributes:
        key: The citation key.
        rank: One-based position in the list it appears in.
        source_type: ``symbol``, ``file``, ``commit``, ``pull_request`` or ``document``.
        file_path: The owning file, when the candidate has one.
        channels: Every channel hit that found it.
    """

    key: str
    rank: int
    source_type: str
    file_path: str | None = None
    channels: list[ChannelHitRecord] = Field(default_factory=list)


class StepRecordOut(_Record):
    """One step of an agent run, flattened for analysis.

    Attributes:
        index: Position in the run.
        kind: The step kind: ``seed``, ``tool_call``, ``model_call`` and so on.
        node: The graph node it ran in.
        tool: The tool, for a tool call.
        arguments: The arguments the model wrote, for a tool call.
        evidence_keys: Keys the step contributed to the run's evidence.
        worker_id: The worker that took it, or ``None`` for the main agent.
        duration_ms: Wall time of the step.
        status: The step's own status, such as a tool call's.
    """

    index: int
    kind: str
    node: str
    tool: str | None = None
    arguments: str | None = None
    evidence_keys: list[str] = Field(default_factory=list)
    worker_id: str | None = None
    duration_ms: float = 0.0
    status: str | None = None


class RunTokens(_Record):
    """The product's own token counts for an agent run."""

    input_tokens: int = 0
    output_tokens: int = 0


class RouteRecord(_Record):
    """One routing decision for the composed ``auto`` arm.

    Attributes:
        item_id: The question routed.
        route: The route the decision chose, or ``None`` when no decision was made.
        confidence: The probability of that route, when known.
        resolved_preset: The product preset the router resolved to.
        target_arm: The evaluation arm that preset maps to.
        fallback_reason: Why the fallback was used instead of the route's own preset.
        model: The decision model that answered, when one did.
        usages: The decision's metered cost.
        cost_usd: What the decision cost, once the runner has priced it.
    """

    item_id: str
    route: str | None = None
    confidence: float | None = None
    resolved_preset: str
    target_arm: str
    fallback_reason: str | None = None
    model: str | None = None
    usages: list[Usage] = Field(default_factory=list)
    cost_usd: float | None = None


class Generation(_Record):
    """Everything recorded about one answer to one question by one arm.

    Attributes:
        record_key: A hash of everything that affects the answer; see :func:`record_key`.
        item_id: The gold item.
        arm: The arm's name.
        repeat: Which repeat of the pair this is.
        config_hash: The arm's behaviour hash.
        model: The generation model.
        prompt_version: The wording of the prompts the arm used.
        answer: The answer text; kept on error records for diagnosis, never scored.
        cited_keys: Keys the answer cites (empty for the Classic shape).
        candidates: The final candidate list, best first (single-shot arms).
        pool: The fused pool the reranker saw (single-shot arms).
        channel_trace: One entry per channel and variant, as the pipeline traced it.
        degraded: Every degradation the retrieval reported.
        steps: The agent's steps.
        stop_reason: Why an agent run stopped.
        run_tokens: The product's own token counts, for agent runs.
        usages: Every metered call.
        unavailable_tool_results: Tool results with status ``unavailable``.
        unmetered_paths: Call paths whose cost could not be metered.
        flagged: The run completed but something about it needs a look.
        error: Why the run is an error record.
        status: ``ok``, or ``error``.
        latency_ms: Wall time of the whole generation.
        route: The routing decision, on composed ``auto`` records.
        composed_from: The arm a composed record was copied from.
        cost_usd: What every attempt at this pair cost, once the runner has priced it; for a
            composed record, the target's cost plus the decision's, which a budget must not
            count again.
        attempts: How many attempts the runner made, the last of which is this record.
        meter_gap_tokens: For an agent run, the metered agent-model tokens minus the product's
            own count; a large negative value means a call path went unmetered.
    """

    record_key: str
    item_id: str
    arm: str
    repeat: int = 0
    config_hash: str
    model: str
    prompt_version: str | None = None
    answer: str = ""
    cited_keys: list[str] = Field(default_factory=list)
    candidates: list[CandidateRecord] = Field(default_factory=list)
    pool: list[CandidateRecord] = Field(default_factory=list)
    channel_trace: list[dict[str, Any]] = Field(default_factory=list)
    degraded: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[StepRecordOut] = Field(default_factory=list)
    stop_reason: str | None = None
    run_tokens: RunTokens | None = None
    usages: list[Usage] = Field(default_factory=list)
    unavailable_tool_results: int = 0
    unmetered_paths: list[str] = Field(default_factory=list)
    flagged: bool = False
    error: str | None = None
    status: Literal["ok", "error"] = "ok"
    latency_ms: float = 0.0
    route: RouteRecord | None = None
    composed_from: str | None = None
    cost_usd: float | None = None
    attempts: int = 1
    meter_gap_tokens: int | None = None

    @model_validator(mode="after")
    def _error_matches_status(self) -> Self:
        if (self.status == "error") != (self.error is not None):
            raise ValueError("an error record needs `error`, and only an error record has it")
        return self

    def metered_tokens(self, *kinds: str) -> tuple[int, int]:
        """Input and output tokens summed over usages of the given kinds (all when none given)."""
        chosen = [u for u in self.usages if not kinds or u.kind in kinds]
        return sum(u.input_tokens for u in chosen), sum(u.output_tokens for u in chosen)

    def reported_cost(self) -> float:
        """The sum of the costs providers reported; calls that reported none add nothing."""
        return sum(u.reported_cost_usd or 0.0 for u in self.usages)


class JudgeVersion(_Record):
    """Who graded and with which prompt: the identity a judgment belongs to.

    Attributes:
        prompt_version: The version of the judge's prompt and output schema.
        model: The judge model id asked for.
        host: The host the judge was called on (``openai`` for the SDK's default endpoint);
            never a path or a key.
        api_style: The transport, ``responses`` or ``chat``.
        judged_on: The date the grade was made, ``YYYY-MM-DD``. It is recorded but is not part
            of the judgment's key, so resuming on another day does not grade a pair again.
    """

    prompt_version: str
    model: str
    host: str
    api_style: str = "responses"
    judged_on: str


class Judgment(_Record):
    """One grade of one generation by one judge, or the record that grading it failed.

    Attributes:
        judgment_key: A hash of the generation's key and the judge's identity; see
            :func:`judgment_key`.
        generation_key: The ``record_key`` of the generation graded.
        item_id: The gold item.
        family: The item's family, kept so results group without reading the gold again.
        arm: The generation's arm, kept for analysis only; the judge is never told it.
        repeat: Which repeat of the pair this is.
        judge: The judge's identity.
        status: ``ok``, or ``error`` when the judge's output could not be used.
        correct: How correct the answer is, 0 to 3.
        faithful: How well the cited evidence supports the answer, 0 to 3.
        abstained: Whether the answer declines to answer.
        rationale: The judge's reasons.
        raw: The judge's raw output, kept on an error record.
        error: Why the record is an error record.
        reported_model: The model the provider reported answering.
        usages: The metered call.
        cost_usd: What grading cost; ``0`` on a reused judgment.
        reused_from: The key of the judgment this one was copied from, for a composed record
            whose answer is identical to its target's.
    """

    judgment_key: str
    generation_key: str
    item_id: str
    family: str
    arm: str
    repeat: int = 0
    judge: JudgeVersion
    status: Literal["ok", "error"] = "ok"
    correct: int | None = None
    faithful: int | None = None
    abstained: bool | None = None
    rationale: str = ""
    raw: str | None = None
    error: str | None = None
    reported_model: str | None = None
    usages: list[Usage] = Field(default_factory=list)
    cost_usd: float | None = None
    reused_from: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.status == "error") != (self.error is not None):
            raise ValueError("an error record needs `error`, and only an error record has it")
        scores = (self.correct, self.faithful, self.abstained)
        if self.status == "ok" and any(value is None for value in scores):
            raise ValueError("a graded record needs correct, faithful and abstained")
        if self.status == "error" and any(value is not None for value in scores):
            raise ValueError("an error record is never scored")
        for score in (self.correct, self.faithful):
            if score is not None and not 0 <= score <= 3:
                raise ValueError("scores run from 0 to 3")
        return self


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_key(
    *,
    item_id: str,
    question: str,
    repo: str,
    base_commit: str,
    arm_config_hash: str,
    model: str,
    prompt_version: str | None,
    instruction: str,
    repeat: int,
) -> str:
    """The key of one generation: a hash of everything that affects the answer.

    It is not keyed by the arm's name, so two arms that behave the same share a key and an
    unchanged arm is recognised across runs, while a changed config, prompt, model, item text
    or instruction produces a new key.
    """
    return _digest(
        {
            "item": {"id": item_id, "question": question, "repo": repo, "base": base_commit},
            "config": arm_config_hash,
            "model": model,
            "prompt": prompt_version,
            "instruction": instruction,
            "repeat": repeat,
        }
    )


def judgment_key(*, generation_key: str, prompt_version: str, model: str, host: str) -> str:
    """The key of one judgment: the generation graded and who graded it.

    The date is not part of it, so a run resumed on another day recognises finished pairs, while
    a new prompt version, model or host grades the generation again.
    """
    return _digest(
        {"judge": generation_key, "prompt": prompt_version, "model": model, "host": host}
    )


def composed_record_key(target_key: str, route: RouteRecord) -> str:
    """The key of an ``auto`` record: the target generation plus the routing that chose it."""
    return _digest(
        {
            "auto": target_key,
            "route": route.route,
            "preset": route.resolved_preset,
            "model": route.model,
        }
    )


__all__ = [
    "CandidateRecord",
    "ChannelHitRecord",
    "Generation",
    "JudgeVersion",
    "Judgment",
    "RouteRecord",
    "RunTokens",
    "StepRecordOut",
    "Usage",
    "UsageKind",
    "composed_record_key",
    "judgment_key",
    "record_key",
]
