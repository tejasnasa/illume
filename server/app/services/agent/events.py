"""The events a run emits while it works.

An event is a name and a JSON-serialisable payload, delivered to an
:data:`~app.services.retrieval.channels.base.Emit` callable. The runner knows
nothing about who is listening: a streaming route turns events into frames, the
evaluation ignores them, and a test collects them in an :class:`EventLog`.
Events describe progress and never carry the only copy of anything; the answer
and the step log are returned and recorded separately.

This module also owns the wire format the streaming endpoint sends and the
replay endpoint returns. A run's internal event names (:class:`Event`) are
translated into a smaller set of public types (:class:`EventType`), each with
one Pydantic model describing its ``data``. The translation lives in
:class:`EventTranslator` and nowhere else, so the live stream and a replay
cannot disagree about what a record means.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field, ValidationError

from app.services.retrieval.channels.base import Emit

logger = logging.getLogger(__name__)


class Event(StrEnum):
    """The names of the events a run emits.

    Attributes:
        RUN_STARTED: The run began. Carries the run id, model and limits.
        NODE: A graph node started or finished (``phase``).
        ROUTE: The routing decision that chose this graph.
        SEED: Retrieval results were put in front of the agent.
        PLAN: The question was split into sub-questions, or planning was
            skipped.
        THINKING: A piece of the model's interim text.
        MODEL_CALL: One model call finished, with its token usage.
        TOOL_CALL: A tool call is about to run.
        TOOL_RESULT: A tool call finished, with its status.
        NODES: Files a tool looked at, for highlighting in the graph.
        EVIDENCE: New citable evidence was gathered.
        COMPACTED: Older tool results were replaced with stubs so the next
            model call fits the context window.
        ANSWER_DELTA: A piece of the answer being written.
        ANSWER: The final answer.
        DEGRADED: Something worked with less than asked: a limit was reached or
            a model-backed stage fell back.
        ERROR: The run failed.
        WORKER_FAILED: One worker failed while the others carried on.
        RUN_FINISHED: The run ended, however it ended.
    """

    RUN_STARTED = "run_started"
    NODE = "node"
    ROUTE = "route"
    SEED = "seed"
    PLAN = "plan"
    THINKING = "thinking"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    NODES = "nodes"
    EVIDENCE = "evidence"
    COMPACTED = "compacted"
    ANSWER_DELTA = "answer_delta"
    ANSWER = "answer"
    DEGRADED = "degraded"
    ERROR = "error"
    WORKER_FAILED = "worker_failed"
    RUN_FINISHED = "run_finished"


async def safe_emit(emit: Emit, event: str, payload: dict[str, Any]) -> None:
    """Emits an event, absorbing a failing listener.

    A listener that raises, such as a closed connection, must not fail a run
    that is otherwise fine.
    """
    try:
        await emit(event, payload)
    except Exception:
        logger.warning("emitting %s failed", event, exc_info=True)


class EventLog:
    """An emitter that keeps every event in memory."""

    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event: str, payload: dict[str, Any]) -> None:
        self.items.append((event, payload))

    def named(self, event: str) -> list[dict[str, Any]]:
        """The payloads of one kind of event, in order."""
        return [payload for name, payload in self.items if name == event]

    def names(self) -> list[str]:
        """Every event name, in order."""
        return [name for name, _ in self.items]


# --- the wire format -----------------------------------------------------------------


class EventType(StrEnum):
    """The public event types, in the order a run usually produces them.

    Attributes:
        RUN_STARTED: The run began.
        ROUTE: The routing decision that chose the configuration.
        PLAN: The question was split into sub-questions, or planning was skipped.
        WORKER_STARTED: A parallel worker began a sub-question.
        WORKER_DONE: A parallel worker ended.
        RETRIEVAL: A retrieval ran: counts per channel and the keys it kept.
        THINKING: A piece of the model's interim text.
        TOOL_CALL: A tool call is about to run.
        TOOL_RESULT: A tool call finished.
        NODES: Files a tool looked at, for highlighting in the graph.
        EVIDENCE: New citable evidence was gathered.
        ANSWER_DELTA: A piece of the answer being written.
        DEGRADED: A limit was reached or a stage fell back.
        ERROR: The run failed.
        DONE: The run ended with an answer.
    """

    RUN_STARTED = "run_started"
    ROUTE = "route"
    PLAN = "plan"
    WORKER_STARTED = "worker_started"
    WORKER_DONE = "worker_done"
    RETRIEVAL = "retrieval"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    NODES = "nodes"
    EVIDENCE = "evidence"
    ANSWER_DELTA = "answer_delta"
    DEGRADED = "degraded"
    ERROR = "error"
    DONE = "done"


TERMINAL_TYPES: frozenset[EventType] = frozenset({EventType.DONE, EventType.ERROR})
"""The types that end a stream. Always recorded, whatever the step cap."""


class RunStartedData(BaseModel):
    """``run_started``: what is about to answer.

    Attributes:
        preset: The preset the request named.
        config_hash: Hash of the effective configuration, overrides included.
        model: The generation model.
        execution: ``single_shot``, ``agent`` or ``planner``.
    """

    preset: str
    config_hash: str
    model: str
    execution: str


class RouteData(BaseModel):
    """``route``: how the question was classified.

    Attributes:
        route: The class the router chose.
        probabilities: The probability of each class, when reported.
        confidence: The router's confidence, when reported.
        fell_back: Whether the router was not confident enough to be trusted, so
            the general path was taken.
        model: The model that answered.
    """

    route: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    fell_back: bool = False
    model: str | None = None


class SubQuestionData(BaseModel):
    """One sub-question of a plan."""

    id: str
    question: str
    focus: str = ""


class PlanData(BaseModel):
    """``plan``: the question split into investigations, or why it was not.

    Attributes:
        skipped: Whether planning was skipped.
        reason: Why it was skipped.
        probability: The pre-check's probability that the question needs a plan.
        threshold: The probability at which planning runs.
        model: The model that planned.
        subquestions: The investigations, in order.
        synthesis_hint: What the closing answer should emphasise.
    """

    skipped: bool = False
    reason: str | None = None
    probability: float | None = None
    threshold: float | None = None
    model: str | None = None
    subquestions: list[SubQuestionData] = Field(default_factory=list)
    synthesis_hint: str = ""


class WorkerStartedData(BaseModel):
    """``worker_started``: a worker began its sub-question."""

    worker_id: str
    question: str | None = None


class WorkerDoneData(BaseModel):
    """``worker_done``: a worker ended.

    Attributes:
        worker_id: The worker.
        question: Its sub-question.
        status: How it ended.
        stop_reason: Why its loop stopped.
    """

    worker_id: str
    question: str | None = None
    status: str | None = None
    stop_reason: str | None = None


class RetrievalData(BaseModel):
    """``retrieval``: a retrieval ran.

    Attributes:
        source: ``seed`` for the retrieval before an agent's first turn,
            ``pipeline`` for a single-shot answer's.
        standalone_question: The question the channels searched with.
        channels: Candidates returned per channel.
        keys: The citation keys kept after fusion and reranking, best first.
        reranker: The reranker that ran.
    """

    source: str = "pipeline"
    standalone_question: str | None = None
    channels: dict[str, int] = Field(default_factory=dict)
    keys: list[str] = Field(default_factory=list)
    reranker: str | None = None


class ThinkingData(BaseModel):
    """``thinking``: interim model text."""

    iteration: int | None = None
    text: str


class ToolCallData(BaseModel):
    """``tool_call``: a call about to run."""

    call_id: str | None = None
    tool: str
    arguments: str = ""


class ToolResultData(BaseModel):
    """``tool_result``: a call finished.

    Attributes:
        call_id: The call it answers.
        tool: The tool.
        status: ``ok``, or why the call produced no output.
        summary: A one-line description of the result, when the tool gives one.
        result_count: How many items the result held, when it is a list.
        truncated: Whether the output was cut to the size limit.
        latency_ms: Wall time of the call.
        error_type: The exception class, when the handler raised one.
        output: What the tool returned, cut to a readable length.
    """

    call_id: str | None = None
    tool: str
    status: str
    summary: str | None = None
    result_count: int | None = None
    truncated: bool = False
    latency_ms: float = 0.0
    error_type: str | None = None
    output: str | None = None


class NodesData(BaseModel):
    """``nodes``: files to highlight in the graph.

    Attributes:
        call_id: The call that looked at them.
        tool: The tool.
        paths: Repository-relative file paths.
        action: What to do with them, such as ``focus`` or ``path``.
    """

    call_id: str | None = None
    tool: str | None = None
    paths: list[str] = Field(default_factory=list)
    action: str | None = None


class EvidenceData(BaseModel):
    """``evidence``: citation keys the run just gathered."""

    keys: list[str]


class AnswerDeltaData(BaseModel):
    """``answer_delta``: a piece of the answer."""

    text: str


class DegradedData(BaseModel):
    """``degraded``: something worked with less than asked.

    Attributes:
        stage: Where: ``budget``, ``context``, ``seed``, ``planner``,
            ``worker``, ``decisions``, ``recording`` or a retrieval stage.
        limit: The limit reached, for budget stages.
        used: How much of it was used.
        allowed: How much was allowed.
        reason: Why, when a stage fell back.
        detail: Anything else the stage reported, such as a channel name.
    """

    stage: str
    limit: str | None = None
    used: float | None = None
    allowed: float | None = None
    reason: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ErrorData(BaseModel):
    """``error``: the run failed.

    Attributes:
        message: What to show the user.
        kind: ``auth``, ``unreachable``, ``provider`` or ``internal``.
        status: The HTTP status the chat endpoint answers the same failure with.
    """

    message: str
    kind: str = "internal"
    status: int = 500


class CitationData(BaseModel):
    """One piece of evidence behind an answer, in the shape chat history stores."""

    key: str | None = None
    source_type: str
    chunk_text: str = ""
    file_path: str | None = None
    symbol_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    commit_hash: str | None = None
    author_name: str | None = None
    pr_number: int | None = None
    pr_title: str | None = None


class UsageData(BaseModel):
    """What a run spent.

    Attributes:
        input_tokens: Input tokens the providers reported.
        output_tokens: Output tokens the providers reported.
        tool_calls: Tool calls started.
        iterations: Model turns taken.
        elapsed_seconds: Wall time of the run.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    iterations: int = 0
    elapsed_seconds: float = 0.0


class DoneData(BaseModel):
    """``done``: the run ended with an answer.

    Attributes:
        run_id: The run.
        status: ``done``.
        answer: The final answer.
        citations: The evidence the answer cites.
        unresolved: Cited keys, as written, that match nothing the run saw.
        stop_reason: Why the run stopped.
        usage: What the run spent.
        chat_message_id: The saved chat turn, when it was saved.
        steps_dropped: Records past the per-run cap that were not stored.
        limits_reached: The limits the run hit, in order.
    """

    run_id: str
    status: str = "done"
    answer: str
    citations: list[CitationData] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    stop_reason: str
    usage: UsageData = Field(default_factory=UsageData)
    chat_message_id: str | None = None
    steps_dropped: int = 0
    limits_reached: list[str] = Field(default_factory=list)


EVENT_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.RUN_STARTED: RunStartedData,
    EventType.ROUTE: RouteData,
    EventType.PLAN: PlanData,
    EventType.WORKER_STARTED: WorkerStartedData,
    EventType.WORKER_DONE: WorkerDoneData,
    EventType.RETRIEVAL: RetrievalData,
    EventType.THINKING: ThinkingData,
    EventType.TOOL_CALL: ToolCallData,
    EventType.TOOL_RESULT: ToolResultData,
    EventType.NODES: NodesData,
    EventType.EVIDENCE: EvidenceData,
    EventType.ANSWER_DELTA: AnswerDeltaData,
    EventType.DEGRADED: DegradedData,
    EventType.ERROR: ErrorData,
    EventType.DONE: DoneData,
}
"""The data model of every public event type."""


class StreamEvent(BaseModel):
    """The envelope every streamed or replayed event travels in.

    Attributes:
        seq: Position in the run; strictly increasing, not necessarily gapless.
        ts: When the event was recorded, ISO 8601 in UTC.
        run_id: The run.
        worker_id: The worker that produced it, or ``None`` for the main agent.
        type: The event type; also the SSE ``event:`` name.
        data: The type's payload, described by :data:`EVENT_MODELS`.
    """

    seq: int
    ts: str
    run_id: str
    worker_id: str | None = None
    type: EventType
    data: dict[str, Any]


def event_schema() -> dict[str, Any]:
    """The JSON schema of the envelope and of every event type's data.

    A snapshot of this is what the client's types are checked against.
    """
    return {
        "envelope": StreamEvent.model_json_schema(),
        "events": {
            event_type.value: EVENT_MODELS[event_type].model_json_schema()
            for event_type in EventType
        },
    }


class Translated(NamedTuple):
    """One public event produced from an internal one."""

    type: EventType
    data: dict[str, Any]
    worker_id: str | None


def _clean(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The payload without its worker tag, which moves to the envelope."""
    return {key: value for key, value in payload.items() if key != "worker_id"}


def _degraded(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A ``degraded`` payload with everything beyond the known fields under ``detail``."""
    known = {"stage", "limit", "used", "allowed", "reason"}
    detail = {key: value for key, value in payload.items() if key not in known | {"worker_id"}}
    return {**{key: payload[key] for key in known if key in payload}, "detail": detail}


class EventTranslator:
    """Turns a run's internal events into public ones.

    This is the only place the two vocabularies meet. The mapping:

    ======================= ==================================================
    internal                public
    ======================= ==================================================
    ``route``               ``route`` (``accepted`` becomes ``fell_back``)
    ``seed``, ``retrieval`` ``retrieval``
    ``plan``                ``plan``
    ``node`` (a worker)     ``worker_started`` / ``worker_done``
    ``worker_failed``       ``degraded`` (stage ``worker``)
    ``thinking``            ``thinking``
    ``tool_call``           ``tool_call``
    ``tool_result``         ``tool_result`` (``elapsed_ms`` is ``latency_ms``)
    ``nodes``               ``nodes``
    ``evidence``            ``evidence``
    ``answer_delta``        ``answer_delta``
    ``compacted``           ``degraded`` (stage ``context``)
    ``degraded``            ``degraded``
    ``error``               ``error``
    ======================= ==================================================

    Not translated, because another record already says it: ``run_started``
    (the route announces the run with the preset), ``node`` for the main
    agent's graph nodes, ``model_call`` (kept as a step; usage arrives in
    ``done``), ``answer`` and ``run_finished`` (superseded by ``done``).

    The translator is stateful in one respect: a worker's question is learnt
    from the plan, so ``worker_started`` can carry it.
    """

    def __init__(self) -> None:
        self._questions: dict[str, str] = {}

    def translate(self, name: str, payload: Mapping[str, Any]) -> list[Translated]:
        """The public events one internal event becomes; empty when it is not public.

        A payload that does not fit its type's model is dropped with a warning
        rather than sent in a shape the client cannot read.
        """
        try:
            return self._translate(name, payload)
        except ValidationError, KeyError, TypeError, ValueError:
            logger.warning("dropping a malformed %s event", name, exc_info=True)
            return []

    def _translate(self, name: str, payload: Mapping[str, Any]) -> list[Translated]:
        worker = payload.get("worker_id")
        worker_id = str(worker) if worker is not None else None
        data = _clean(payload)

        def one(kind: EventType, shaped: Mapping[str, Any]) -> list[Translated]:
            validated = EVENT_MODELS[kind].model_validate(dict(shaped))
            return [Translated(kind, validated.model_dump(mode="json"), worker_id)]

        match name:
            case "route":
                return one(
                    EventType.ROUTE,
                    {
                        "route": data.get("route"),
                        "probabilities": data.get("probabilities") or {},
                        "confidence": data.get("confidence"),
                        "fell_back": not data.get("accepted", True),
                        "model": data.get("model"),
                    },
                )
            case "seed":
                return one(EventType.RETRIEVAL, {"source": "seed", **data})
            case "retrieval":
                return one(EventType.RETRIEVAL, data)
            case "plan":
                translated = one(EventType.PLAN, data)
                for position, sub in enumerate(translated[0].data["subquestions"], start=1):
                    self._questions[f"w{position}"] = sub["question"]
                return translated
            case "node":
                if data.get("node") != "worker" or worker_id is None:
                    return []
                question = self._questions.get(worker_id)
                if data.get("phase") == "started":
                    return one(
                        EventType.WORKER_STARTED, {"worker_id": worker_id, "question": question}
                    )
                return one(
                    EventType.WORKER_DONE,
                    {
                        "worker_id": worker_id,
                        "question": question,
                        "status": data.get("status"),
                        "stop_reason": data.get("stop_reason"),
                    },
                )
            case "worker_failed":
                return one(
                    EventType.DEGRADED,
                    {
                        "stage": "worker",
                        "reason": data.get("message"),
                        "detail": {
                            "kind": data.get("kind"),
                            "subquestion": data.get("subquestion"),
                        },
                    },
                )
            case "thinking":
                return one(EventType.THINKING, data)
            case "tool_call":
                return one(EventType.TOOL_CALL, data)
            case "tool_result":
                return one(
                    EventType.TOOL_RESULT,
                    {**data, "latency_ms": data.get("elapsed_ms", data.get("latency_ms", 0.0))},
                )
            case "nodes":
                return one(EventType.NODES, data)
            case "evidence":
                return one(EventType.EVIDENCE, data)
            case "answer_delta":
                return one(EventType.ANSWER_DELTA, data)
            case "compacted":
                return one(
                    EventType.DEGRADED,
                    {
                        "stage": "context",
                        "limit": "compacted",
                        "used": data.get("estimated_tokens_after"),
                        "allowed": data.get("context_window"),
                        "reason": "older tool results were replaced with short stubs",
                        "detail": {
                            "replaced": data.get("replaced"),
                            "trigger": data.get("trigger"),
                            "estimated_tokens_before": data.get("estimated_tokens_before"),
                        },
                    },
                )
            case "degraded":
                return one(EventType.DEGRADED, _degraded(payload))
            case "error":
                return one(EventType.ERROR, data)
            case _:
                return []
