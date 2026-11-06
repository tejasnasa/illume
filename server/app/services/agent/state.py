"""The state one agent run carries through the graph, and the values inside it.

The state holds only what a node needs to decide the next step: the
conversation as Responses input items, the evidence gathered so far, and a few
counters. Run-wide limits are deliberately not here. State from concurrent
branches is merged only when a step ends, while a limit has to be enforced the
moment it is crossed, so those counters live in
:class:`~app.services.agent.budgets.RunBudget` instead.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, TypedDict

from app.services.decisions import RouteDecision
from app.services.retrieval.citations import CitationKey, find_keys, normalize_path, parse_key


class StopReason(StrEnum):
    """Why a run stopped looping and produced its answer.

    Attributes:
        FINISHED: The agent called ``finish`` and the evidence was judged enough.
        TEXT_REPLY: The agent answered in plain text instead of calling ``finish``.
        GATE_EXHAUSTED: The sufficiency check rejected the evidence as often as
            it is allowed to.
        MAX_ITERATIONS: The agent used all its model turns.
        MAX_TOOL_CALLS: The run used all its tool calls.
        MAX_SECONDS: The run used its wall-clock allowance.
        MAX_INPUT_TOKENS: The run used its input token allowance.
        CONTEXT_WINDOW: The conversation no longer fits the context window,
            even with older tool results compacted.
        TOOL_ERRORS: Three turns in a row produced only failed tool calls.
        RECURSION: The graph hit its step limit.
        HARD_TIMEOUT: The run was cancelled at the hard wall-clock limit.
        CANCELLED: The caller cancelled the run.
        ERROR: A model call failed.
    """

    FINISHED = "finished"
    TEXT_REPLY = "text_reply"
    GATE_EXHAUSTED = "gate_exhausted"
    MAX_ITERATIONS = "max_iterations"
    MAX_TOOL_CALLS = "max_tool_calls"
    MAX_SECONDS = "max_seconds"
    MAX_INPUT_TOKENS = "max_input_tokens"
    CONTEXT_WINDOW = "context_window"
    TOOL_ERRORS = "tool_errors"
    RECURSION = "recursion"
    HARD_TIMEOUT = "hard_timeout"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class ChatTurn:
    """One earlier message of the conversation.

    Attributes:
        role: ``user`` or ``assistant``.
        content: The message text.
    """

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Evidence:
    """A piece of repository text the agent has seen, under its citation key.

    Attributes:
        key: The citation key, such as ``F:app/main.py:3-9``.
        text: What the agent was shown for that key.
        label: The kind of text, such as ``code`` or ``commit``.
        provenance: ``history`` for commits and pull requests, ``repo`` otherwise.
        first_step: The step that first produced it.
        found_by: Every tool that produced it, in the order they did.
    """

    key: str
    text: str
    label: str = "code"
    provenance: str = "repo"
    first_step: int = 0
    found_by: tuple[str, ...] = ()


def _merge_one(old: Evidence, new: Evidence) -> Evidence:
    """The union of two sightings of the same key.

    The earliest discovery step and every finder are kept. The longer text wins,
    since a search excerpt and a full read share one key.
    """
    first, second = (old, new) if old.first_step <= new.first_step else (new, old)
    found_by = tuple(dict.fromkeys((*first.found_by, *second.found_by)))
    longest = old if len(old.text) >= len(new.text) else new
    return Evidence(
        key=first.key,
        text=longest.text,
        label=longest.label,
        provenance=first.provenance,
        first_step=first.first_step,
        found_by=found_by,
    )


def merge_evidence(
    left: Mapping[str, Evidence] | None, right: Mapping[str, Evidence] | None
) -> dict[str, Evidence]:
    """Reducer for ``AgentState.evidence``: union by key.

    Keeps the earliest discovery step and every tool that found a key, so
    branches that write evidence at the same time do not overwrite each other.
    Key order follows first appearance.
    """
    merged = dict(left or {})
    for key, evidence in (right or {}).items():
        merged[key] = _merge_one(merged[key], evidence) if key in merged else evidence
    return merged


@dataclass(frozen=True)
class ReplaceItems:
    """A state update that replaces the conversation instead of extending it.

    Attributes:
        items: The whole conversation to continue from.
    """

    items: list[dict[str, Any]]


def merge_items(
    left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | ReplaceItems | None
) -> list[dict[str, Any]]:
    """Reducer for ``AgentState.items``: appends, unless the update replaces.

    The conversation only grows, except when compaction rewrites it to fit the
    context window, which it signals with :class:`ReplaceItems`.
    """
    if isinstance(right, ReplaceItems):
        return list(right.items)
    return [*(left or []), *(right or [])]


@dataclass(frozen=True)
class VerificationReport:
    """What a verifier found wrong with a draft answer.

    Attributes:
        unsupported: The claims, as sentences, that their citations do not support.
    """

    unsupported: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        """Whether any claim needs repair."""
        return bool(self.unsupported)


# --- splitting one question across workers -------------------------------------

Focus = Literal["code", "graph", "history"]

WorkerStatus = Literal["completed", "partial", "failed", "timed_out"]


@dataclass(frozen=True)
class SubQuestion:
    """One independent investigation a question was split into.

    Attributes:
        id: A short identifier, unique within the plan.
        question: The part of the original question this investigation answers.
        focus: Where the investigation should concentrate: source text, the
            import graph, or history.
    """

    id: str
    question: str
    focus: Focus = "code"

    def to_dict(self) -> dict[str, str]:
        """The sub-question as JSON-serialisable data."""
        return {"id": self.id, "question": self.question, "focus": self.focus}


@dataclass(frozen=True)
class Plan:
    """A question split into the investigations that answer it.

    Attributes:
        subquestions: The investigations, in the order they were planned.
        synthesis_hint: What the closing answer should emphasise, when the
            planner said anything about it.
        model: The model that produced the plan.
    """

    subquestions: tuple[SubQuestion, ...]
    synthesis_hint: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The plan as JSON-serialisable data."""
        return {
            "subquestions": [sub.to_dict() for sub in self.subquestions],
            "synthesis_hint": self.synthesis_hint,
            "model": self.model,
        }


@dataclass(frozen=True)
class WorkerResult:
    """What one worker found, however it ended.

    Attributes:
        worker_id: The worker's id within the run, which its events carry too.
        subquestion_id: The plan entry this worker investigated.
        question: The sub-question as planned.
        focus: Where the worker concentrated.
        status: ``completed`` when it wrote findings, ``partial`` when a limit
            stopped it, ``failed`` when a model call failed, ``timed_out`` when
            its work was cut off.
        stop_reason: Why the worker's loop ended.
        answer: Its findings, which may be a summary of what it saw when it
            never wrote one.
        evidence_keys: The citation keys it gathered.
        iterations: Model turns it took.
        error: Why it failed, when it did.
    """

    worker_id: str
    subquestion_id: str
    question: str
    focus: str
    status: WorkerStatus
    stop_reason: StopReason
    answer: str
    evidence_keys: tuple[str, ...] = ()
    iterations: int = 0
    error: str | None = None

    @property
    def failed(self) -> bool:
        """Whether the worker produced no findings at all."""
        return self.status in ("failed", "timed_out")

    def to_dict(self) -> dict[str, Any]:
        """The result as JSON-serialisable data, for the step log."""
        return {
            "worker_id": self.worker_id,
            "subquestion_id": self.subquestion_id,
            "question": self.question,
            "focus": self.focus,
            "status": self.status,
            "stop_reason": self.stop_reason.value,
            "answer_chars": len(self.answer),
            "evidence_keys": list(self.evidence_keys),
            "iterations": self.iterations,
            "error": self.error,
        }


def unanswered(results: Sequence[WorkerResult]) -> tuple[str, ...]:
    """The sub-questions no worker produced findings for."""
    return tuple(result.question for result in results if result.failed)


class AgentState(TypedDict):
    """Everything the nodes read and write.

    Attributes:
        question: The question as typed.
        standalone_question: The question with follow-up references resolved;
            equal to ``question`` until retrieval has condensed it.
        history: Earlier turns, oldest first.
        route: The routing decision that chose this graph, when there was one.
        items: The Responses API input so far, sent whole on every model call;
            model output is appended verbatim. It only grows, except when
            compaction replaces older tool results with stubs.
        evidence: Repository text seen so far, by citation key.
        iteration: Model turns taken.
        gate_feedback: The reviewer's last objection, when the gate rejected.
        gate_rejections: Times the sufficiency check sent the agent back.
        draft: The answer the agent wrote with ``finish``, until it is accepted.
        confidence_note: What the agent said was uncertain, from ``finish``.
        plan: The sub-questions the question was split into, when it was.
        worker_results: What each worker found, however it ended.
        turn_end: How the last model turn ended: ``tools``, ``finish``,
            ``text`` or ``limit``.
        pending_calls: Function calls of the last turn that have no output yet.
        consecutive_errors: Turns in a row whose tool calls all failed, reset
            by any successful call.
        last_input_tokens: Input tokens the provider reported for the last
            model call, which calibrates the estimate of the next one.
        last_input_chars: The size of the conversation that call was sent.
        compactions: Times the conversation was compacted to fit the window.
        verification: What the verifier found, when one ran.
        repair_rounds: Times a failed verification sent the agent back.
        stop_reason: Why the loop ended, once it has.
        answer: The final answer text.
    """

    question: str
    standalone_question: str
    history: list[ChatTurn]
    route: RouteDecision | None
    items: Annotated[list[dict[str, Any]], merge_items]
    evidence: Annotated[dict[str, Evidence], merge_evidence]
    iteration: int
    gate_feedback: str | None
    gate_rejections: int
    draft: str | None
    confidence_note: str | None
    plan: Plan | None
    worker_results: Annotated[list[WorkerResult], operator.add]
    turn_end: str | None
    pending_calls: list[dict[str, Any]]
    consecutive_errors: int
    last_input_tokens: int
    last_input_chars: int
    compactions: int
    verification: VerificationReport | None
    repair_rounds: int
    stop_reason: StopReason | None
    answer: str | None


def initial_state(
    question: str,
    history: list[ChatTurn],
    items: list[dict[str, Any]],
    *,
    route: RouteDecision | None = None,
) -> AgentState:
    """The state a run starts from.

    Args:
        question: The question as typed.
        history: Earlier turns, oldest first.
        items: The opening input items: the system prompt, the replayed
            history and the question.
        route: The routing decision, when one was made.
    """
    return AgentState(
        question=question,
        standalone_question=question,
        history=history,
        route=route,
        items=items,
        evidence={},
        iteration=0,
        gate_feedback=None,
        gate_rejections=0,
        draft=None,
        confidence_note=None,
        plan=None,
        worker_results=[],
        turn_end=None,
        pending_calls=[],
        consecutive_errors=0,
        last_input_tokens=0,
        last_input_chars=0,
        compactions=0,
        verification=None,
        repair_rounds=0,
        stop_reason=None,
        answer=None,
    )


# --- reading evidence out of tool results ---------------------------------------

_BLOCK = re.compile(
    r'<source key="(?P<key>[^"]*)" type="(?P<label>[^"]*)" provenance="(?P<provenance>[^"]*)">'
    r"\n(?P<body>.*?)(?:\n</source>|\Z)",
    re.DOTALL,
)

# Listings carry a ``tool:`` key because they are not something to cite.
_UNCITABLE_PREFIX = "tool:"


def _unescape(value: str) -> str:
    return value.replace("&lt;", "<").replace("&quot;", '"')


def extract_evidence(text: str, *, tool: str, step: int) -> dict[str, Evidence]:
    """The citable ``<source>`` blocks of a tool result.

    Args:
        text: The text the model was shown.
        tool: The tool that produced it.
        step: The step that produced it.

    Returns:
        Evidence by key, in order of appearance. Blocks keyed ``tool:<name>``
        are listings, not evidence, and are skipped.
    """
    found: dict[str, Evidence] = {}
    for match in _BLOCK.finditer(text):
        key = _unescape(match.group("key"))
        if key.startswith(_UNCITABLE_PREFIX):
            continue
        evidence = Evidence(
            key=key,
            text=match.group("body"),
            label=_unescape(match.group("label")),
            provenance=match.group("provenance"),
            first_step=step,
            found_by=(tool,),
        )
        found[key] = _merge_one(found[key], evidence) if key in found else evidence
    return found


# --- matching the keys an answer cites ---------------------------------------------


@dataclass(frozen=True)
class CitedEvidence:
    """The keys an answer cites, split by whether the run saw them.

    Attributes:
        cited: Evidence keys the answer cites, in order of first citation,
            each once.
        unresolved: Cited keys, as written, that match nothing the run saw.
    """

    cited: tuple[str, ...]
    unresolved: tuple[str, ...]


def _covers(evidence_key: CitationKey, wanted: CitationKey) -> bool:
    """Whether a piece of evidence is the thing a code key refers to."""
    if evidence_key.kind != "F" or wanted.kind != "F":
        return False
    if normalize_path(evidence_key.path or "") != normalize_path(wanted.path or ""):
        return False
    if (
        wanted.start is None
        or wanted.end is None
        or evidence_key.start is None
        or evidence_key.end is None
    ):
        return True
    return min(evidence_key.end, wanted.end) >= max(evidence_key.start, wanted.start)


def match_evidence(wanted: CitationKey, evidence: Mapping[str, Evidence]) -> str | None:
    """The evidence key a parsed citation refers to, or ``None``.

    An exact key wins. A code key without a range matches any range of that
    file, and one with a range matches evidence that overlaps it, which is how
    a whole-file read backs a cited range. A commit key matches by hash prefix.
    """
    rendered = wanted.render()
    if rendered in evidence:
        return rendered
    for key in evidence:
        parsed = parse_key(key)
        if parsed is None:
            continue
        if wanted.kind == "F" and _covers(parsed, wanted):
            return key
        if wanted.kind == "C" and parsed.kind == "C":
            have, asked = parsed.commit or "", wanted.commit or ""
            if have.startswith(asked) or asked.startswith(have):
                return key
    return None


def resolve_citations(answer: str, evidence: Mapping[str, Evidence]) -> CitedEvidence:
    """Matches the keys written in ``answer`` against the evidence the run saw."""
    cited: list[str] = []
    unresolved: list[str] = []
    for raw, parsed in find_keys(answer):
        match = match_evidence(parsed, evidence) if parsed is not None else None
        if match is None:
            if raw not in unresolved:
                unresolved.append(raw)
        elif match not in cited:
            cited.append(match)
    return CitedEvidence(cited=tuple(cited), unresolved=tuple(unresolved))
