"""The decision-maker contract, the result types, and the fallback between deciders.

A decider answers one narrow question at a time and returns the answer with the
probability it attaches to it, never prose. Two implementations exist:
:class:`~app.services.decisions.jev.JevDecider`, which asks a decision model, and
:class:`~app.services.decisions.llm.LlmDecider`, which asks the user's own model
for its impression of a probability. The interface is the same, so every
decision point is built twice and the two can be compared on equal terms.

Three primitives cover every decision the pipeline makes:

* :meth:`Decider.choice` picks one option from a set, with a probability per
  option and a confidence.
* :meth:`Decider.score` places something on an ordered rubric, returning the
  probability-weighted position.
* :meth:`Decider.noul` reports the probability that a yes/no statement is true.

:meth:`Decider.batch` sends several questions in one request, which is the
intended use: a verifier checking ten claims, or a guard screening every tool
result of one round, should cost one decision request, not ten.

Every result carries the model that answered, the latency, the reported cost and
the raw response, because the evaluation reads back exactly these fields to
compute calibration and cost. :func:`record_decision` turns a result into a
:class:`DecisionRecord` for the run's step log; the state itself is represented
by its hash, so repository text is not duplicated into the log.

:class:`FallbackDecider` is what keeps the product working when the decision
model does not: it prefers Jev and answers with the LLM when Jev is missing,
unreachable, out of credit or malformed. It emits **one** ``degraded`` event per
run rather than one per decision, so a systemic outage is visible without
flooding the stream.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

from app.services.decisions.openrouter import DecisionError, Question
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import Emit

logger = logging.getLogger(__name__)

Primitive = Literal["choice", "score", "noul"]

# The criteria a ``noul`` question carries when the caller does not supply its
# own. Both deciders use the same wording, so their answers describe the same
# statement.
NOUL_TRUE = "The statement is true."
NOUL_FALSE = "The statement is false."


class DeciderUnavailable(RuntimeError):
    """No decider of the requested kind can be built.

    Raised when the kind has no implementation, when Jev is asked for and
    ``OPENROUTER_API_KEY`` is empty, or when the LLM stand-in is asked for and
    there is no credential to call it with.
    """


# --- results ----------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DecisionResult:
    """The bookkeeping every result carries.

    Attributes:
        latency_ms: Wall time of the request, in milliseconds.
        model: The model that answered. For Jev this is the exact snapshot the
            response reported, which can be more specific than the pinned id
            that was requested.
        provider: Who answered, such as ``typesafe`` or ``llm``.
        cost: The reported cost of the request in dollars, when available.
        request_id: The provider's request id, when reported. Results from one
            batched request share it, and with it the same ``cost``; summing
            per decision therefore over-counts a batch and should be done per
            request id instead.
        tokens_in: Input tokens the provider reported, when reported.
        tokens_out: Output tokens the provider reported, when reported.
        raw: The provider's response as received, for the step log.
        defaulted: Whether the answer is a placeholder because the model's
            output was unusable. Each decision point then takes its own safe
            side instead of trusting the placeholder.
    """

    latency_ms: float
    model: str
    provider: str
    cost: float | None = None
    request_id: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw: Any = None
    defaulted: bool = False


@dataclass(frozen=True, kw_only=True)
class ChoiceResult(DecisionResult):
    """One option from a set.

    Attributes:
        choice: The winning option, always one of the options asked about.
        probabilities: The probability of each option, when the provider
            reports them. The LLM stand-in reports only its chosen option.
        confidence: The model's confidence in its answer, when reported.
    """

    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


@dataclass(frozen=True, kw_only=True)
class ScoreResult(DecisionResult):
    """A position on an ordered rubric.

    Attributes:
        score: The probability-weighted position, ``0`` to ``n - 1``.
        probabilities: The probability of each level index, when reported.
        confidence: The model's confidence in its answer, when reported.
    """

    score: float
    probabilities: dict[int, float] = field(default_factory=dict)
    confidence: float | None = None


@dataclass(frozen=True, kw_only=True)
class NoulResult(DecisionResult):
    """The probability that a yes/no statement is true.

    Attributes:
        noul: The probability, from ``0`` to ``1``.
        confidence: The model's confidence in that probability, when reported.
    """

    noul: float
    confidence: float | None = None


Result = ChoiceResult | ScoreResult | NoulResult


# --- records ----------------------------------------------------------------


def state_hash(state: Any) -> str:
    """A stable SHA-256 of the state sent to the decider.

    The hash is what goes into the step log instead of the repository text, so
    a decision can be matched to the evidence it was made about without the log
    holding a second copy of that evidence. A string hashes as itself; anything
    else hashes as its canonical JSON.
    """
    if isinstance(state, str):
        payload = state
    else:
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def state_bytes(state: Any) -> int:
    """The UTF-8 size of what is sent as the state."""
    if isinstance(state, str):
        return len(state.encode("utf-8"))
    return len(json.dumps(state, default=str).encode("utf-8"))


@dataclass(frozen=True)
class DecisionRecord:
    """One decision, as the step log and the evaluation read it back.

    Attributes:
        point: What the decision was for, such as ``route`` or
            ``sufficiency``.
        primitive: Which of the three primitives answered it.
        state_hash: :func:`state_hash` of the state sent.
        state_bytes: The size of that state, for cost analysis.
        answer: The chosen option, the score, or the probability.
        probabilities: Every probability the provider reported, keyed by
            option or by level index.
        confidence: The reported confidence, when there was one.
        model: The model that answered.
        provider: Who answered.
        latency_ms: Wall time of the request.
        cost: The request's reported cost, when reported.
        request_id: The provider's request id, when reported.
        tokens_in: Input tokens the provider reported, when reported.
        tokens_out: Output tokens the provider reported, when reported.
        defaulted: Whether the answer was a placeholder for unusable output.
    """

    point: str
    primitive: Primitive
    state_hash: str
    state_bytes: int
    answer: str | float
    probabilities: dict[str, float]
    confidence: float | None
    model: str
    provider: str
    latency_ms: float
    cost: float | None
    request_id: str | None
    tokens_in: int | None
    tokens_out: int | None
    defaulted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """The record as a JSON-serialisable dict for a step payload."""
        return {
            "point": self.point,
            "primitive": self.primitive,
            "state_hash": self.state_hash,
            "state_bytes": self.state_bytes,
            "answer": self.answer,
            "probabilities": self.probabilities,
            "confidence": self.confidence,
            "model": self.model,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "cost": self.cost,
            "request_id": self.request_id,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "defaulted": self.defaulted,
        }


RecordDecision = Callable[[DecisionRecord], Awaitable[None]]
"""Where a decision record goes. A run's step writer is the production sink."""


def make_record(point: str, state: Any, result: Result) -> DecisionRecord:
    """The record for one answered decision."""
    if isinstance(result, ChoiceResult):
        primitive: Primitive = "choice"
        answer: str | float = result.choice
        probabilities = dict(result.probabilities)
    elif isinstance(result, ScoreResult):
        primitive = "score"
        answer = result.score
        probabilities = {str(level): value for level, value in result.probabilities.items()}
    else:
        primitive = "noul"
        answer = result.noul
        probabilities = {}
    return DecisionRecord(
        point=point,
        primitive=primitive,
        state_hash=state_hash(state),
        state_bytes=state_bytes(state),
        answer=answer,
        probabilities=probabilities,
        confidence=result.confidence,
        model=result.model,
        provider=result.provider,
        latency_ms=result.latency_ms,
        cost=result.cost,
        request_id=result.request_id,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        defaulted=result.defaulted,
    )


async def record_decision(record: RecordDecision, point: str, state: Any, result: Result) -> None:
    """Writes one decision record, never letting a failing sink break the decision."""
    try:
        await record(make_record(point, state, result))
    except Exception:
        logger.warning("recording decision %r failed", point, exc_info=True)


# --- the contract -----------------------------------------------------------


class Decider(Protocol):
    """Answers the narrow questions a run's control flow depends on.

    Attributes:
        kind: ``jev`` or ``llm``.
        model_id: The model the decider asks. For Jev this is the pinned id; the
            exact snapshot that answered is on each result's ``model``.
    """

    kind: str

    @property
    def model_id(self) -> str:
        """The model the decider asks."""
        ...

    async def choice(
        self, state: Any, instructions: str, options: Mapping[str, str]
    ) -> ChoiceResult:
        """Picks one of ``options`` (name to description).

        The returned choice is always one of the offered names.
        """
        ...

    async def score(self, state: Any, instructions: str, levels: Sequence[str]) -> ScoreResult:
        """Places the subject of ``instructions`` on ``levels``, lowest first.

        The returned score is always between ``0`` and ``len(levels) - 1``.
        """
        ...

    async def noul(self, state: Any, instructions: str) -> NoulResult:
        """The probability that the statement in ``instructions`` is true."""
        ...

    async def batch(self, state: Any, questions: Mapping[str, Question]) -> dict[str, Result]:
        """Answers several questions about one state, keyed by question name."""
        ...


# --- fallback ---------------------------------------------------------------

_T = TypeVar("_T")

# Failures of the decision API that will not clear within one run.
_RUN_ENDING_REASONS = frozenset({"unauthorized", "out_of_credit", "timeout", "server", "transport"})


async def _discard(event: str, payload: dict[str, Any]) -> None:
    """The default emitter, for callers that do not stream progress."""


class FallbackDecider:
    """Prefers ``primary`` and answers with ``fallback`` whenever it fails.

    It covers both the deployment without a TypeSafe key and a transient Jev
    outage: when Jev cannot answer, the user's own model does, and the run says
    so once. ``primary=None`` represents a decider that could not be built at
    all, such as Jev with no key.

    Attributes:
        kind: Always ``jev``: the kind that was asked for, not the one that
            answered.
        degraded: Whether a fallback has happened. The ``degraded`` event is
            emitted on the first failure only.

    One instance serves one run: the event and the retired primary are both
    per-run state.
    """

    kind = "jev"

    def __init__(
        self,
        primary: Decider | None,
        fallback: Decider,
        *,
        emit: Emit = _discard,
        unavailable: str | None = None,
    ) -> None:
        """
        Args:
            primary: The decider to prefer, or ``None`` when it is unavailable.
            fallback: The decider that answers when the primary cannot.
            emit: Receives the one ``degraded`` event.
            unavailable: Why ``primary`` is ``None``, for that event.
        """
        self._primary = primary
        self._fallback = fallback
        self._emit = emit
        self._unavailable = unavailable
        self.degraded = False

    @property
    def model_id(self) -> str:
        """The preferred model, or the fallback's when there is no primary."""
        if self._primary is not None:
            return self._primary.model_id
        return self._fallback.model_id

    async def _try(self, call: Callable[[Decider], Awaitable[_T]]) -> _T:
        """Runs ``call`` on the primary, falling back after any failure.

        A failure that will not clear within a run (a rejected key, no credit,
        a timeout, a server or connection error) retires the primary for the
        rest of the run, so every later decision does not wait out the same
        outage before falling back. A per-request failure, such as a rate limit
        or a malformed answer, falls back for that call only.
        """
        if self._primary is None:
            await self._degrade(self._unavailable or "the primary decider is unavailable")
            return await call(self._fallback)
        try:
            return await call(self._primary)
        except Exception as error:
            if isinstance(error, DecisionError) and error.reason in _RUN_ENDING_REASONS:
                self._primary = None
                self._unavailable = f"{type(error).__name__}: {error}"[:300]
            await self._degrade(f"{type(error).__name__}: {error}"[:300])
            return await call(self._fallback)

    async def _degrade(self, reason: str) -> None:
        """Emits the run's one ``degraded`` event, the first time only."""
        if self.degraded:
            return
        logger.warning("decisions degraded to the LLM: %s", reason)
        self.degraded = True
        try:
            await self._emit(
                "degraded",
                {
                    "stage": "decisions",
                    "decider": "jev",
                    "fallback": self._fallback.kind,
                    "reason": reason,
                },
            )
        except Exception:
            logger.warning("emitting the decisions degradation failed", exc_info=True)

    async def choice(
        self, state: Any, instructions: str, options: Mapping[str, str]
    ) -> ChoiceResult:
        """The primary's choice, or the fallback's."""
        return await self._try(lambda decider: decider.choice(state, instructions, options))

    async def score(self, state: Any, instructions: str, levels: Sequence[str]) -> ScoreResult:
        """The primary's score, or the fallback's."""
        return await self._try(lambda decider: decider.score(state, instructions, levels))

    async def noul(self, state: Any, instructions: str) -> NoulResult:
        """The primary's probability, or the fallback's."""
        return await self._try(lambda decider: decider.noul(state, instructions))

    async def batch(self, state: Any, questions: Mapping[str, Question]) -> dict[str, Result]:
        """The primary's answers, or the fallback's."""
        return await self._try(lambda decider: decider.batch(state, questions))


# --- construction -----------------------------------------------------------


def get_decider(
    kind: str,
    *,
    llm: LLMConfig | None = None,
    emit: Emit | None = None,
    session_id: str | None = None,
) -> Decider:
    """The decider for ``kind``.

    ``jev`` returns a :class:`FallbackDecider` whenever an LLM credential is
    available, so a missing key or a Jev outage degrades instead of failing.
    ``llm`` returns the stand-in directly. Implementations are imported inside
    the branches because they import this module.

    Args:
        kind: ``jev`` or ``llm``, as in ``PipelineConfig.decider``.
        llm: The credential the stand-in uses. ``None`` falls back to the
            server's free-tier credential.
        emit: Receives the ``degraded`` event. ``None`` discards it.
        session_id: Groups the ``jev`` requests in OpenRouter's logs. Sent only
            when given.

    Raises:
        DeciderUnavailable: When the kind has no implementation, when Jev is
            asked for with no key and no LLM can stand in, or when the fallback
            is asked for with no credential.
    """
    if kind not in ("jev", "llm"):
        raise DeciderUnavailable(f"decider {kind!r} is not available")

    resolved = llm if llm is not None else LLMConfig.server_default()
    if kind == "llm":
        if resolved is None:
            raise DeciderUnavailable("decider 'llm' is not available: no model credential")
        from app.services.decisions.llm import LlmDecider

        return LlmDecider(resolved)

    from app.services.decisions.jev import JevDecider

    primary: Decider | None
    unavailable: str | None = None
    try:
        primary = JevDecider(session_id=session_id)
    except DeciderUnavailable as error:
        primary = None
        unavailable = str(error)

    if resolved is None:
        if primary is None:
            raise DeciderUnavailable(
                "decider 'jev' is not available: no OPENROUTER_API_KEY and no model credential"
            )
        # No LLM can stand in, but Jev itself works: use it without a fallback.
        return primary

    from app.services.decisions.llm import LlmDecider

    return FallbackDecider(
        primary, LlmDecider(resolved), emit=emit or _discard, unavailable=unavailable
    )
