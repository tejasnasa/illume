"""The decision model behind the :class:`~app.services.decisions.base.Decider` contract.

Each primitive becomes one named question: a ``choice`` for picking among options,
a ``score`` for placing something on a rubric, and a ``noul`` for the probability
that a statement is true. :meth:`JevDecider.batch` sends many questions in one
request, which is what keeps a verifier checking ten claims or a guard screening
every tool result of a round at one request apiece.

A batch whose text would push a request over :data:`MAX_REQUEST_BYTES` is split
into several requests, because Jev switches to a slower, less accurate
long-context mode above that size. Scores and probabilities come back as
reported; the score's weighted position is clamped to the rubric and every
probability to ``0`` to ``1``, so a malformed number can never escape the
contract.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import settings
from app.services.decisions.base import (
    NOUL_FALSE,
    NOUL_TRUE,
    ChoiceResult,
    DeciderUnavailable,
    NoulResult,
    Result,
    ScoreResult,
    state_bytes,
)
from app.services.decisions.openrouter import (
    JEV_MODEL,
    MAX_REQUEST_BYTES,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionError,
    DecisionResponse,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    submit,
)

# Batches are sent concurrently; a large verifier fan-out should not open an
# unbounded number of connections.
MAX_PARALLEL_REQUESTS = 4


def _clamp(value: float, low: float, high: float) -> float:
    """``value`` inside ``[low, high]``."""
    return min(max(value, low), high)


def _probability(value: float) -> float:
    """A probability inside ``[0, 1]``."""
    return _clamp(value, 0.0, 1.0)


def _optional_probability(value: float | None) -> float | None:
    """A reported confidence inside ``[0, 1]``, or ``None`` when absent."""
    return None if value is None else _probability(value)


def _offered_choice(
    answer: ChoiceAnswer, options: Mapping[str, str]
) -> tuple[str, dict[str, float], bool]:
    """The chosen option, the probabilities, and whether the choice is a placeholder.

    A choice the caller did not offer is replaced by the offered option with the
    highest reported probability. With no usable probability either, the first
    option stands in and is flagged as a placeholder, so the caller can take its
    safe side rather than act on it.
    """
    probabilities = {
        option: _probability(value)
        for option, value in answer.probabilities.items()
        if option in options
    }
    if answer.choice in options:
        return answer.choice, probabilities, False
    if probabilities:
        order = {option: position for position, option in enumerate(options)}
        best = max(probabilities, key=lambda option: (probabilities[option], -order.get(option, 0)))
        return best, probabilities, False
    return next(iter(options)), {}, True


def _result(
    name: str,
    question: Question,
    response: DecisionResponse,
    latency_ms: float,
) -> Result:
    """The typed result for one answer of a response.

    Raises:
        DecisionError: When the answer's shape does not match the question's primitive.
    """
    answer = response.answers[name]
    common: dict[str, Any] = {
        "latency_ms": latency_ms,
        "model": response.model,
        "provider": response.provider or "openrouter",
        "cost": response.cost,
        "request_id": response.id,
        "tokens_in": response.input_tokens,
        "tokens_out": response.output_tokens,
        "raw": response.raw,
    }

    if isinstance(question, ChoiceQuestion) and isinstance(answer, ChoiceAnswer):
        choice, probabilities, defaulted = _offered_choice(answer, question.criteria)
        return ChoiceResult(
            choice=choice,
            probabilities=probabilities,
            confidence=0.0 if defaulted else _optional_probability(answer.confidence),
            defaulted=defaulted,
            **common,
        )
    if isinstance(question, ScoreQuestion) and isinstance(answer, ScoreAnswer):
        highest = float(max(len(question.criteria) - 1, 0))
        return ScoreResult(
            score=_clamp(answer.score, 0.0, highest),
            probabilities={
                level: _probability(value)
                for level, value in answer.probabilities.items()
                if 0 <= level < len(question.criteria)
            },
            confidence=_optional_probability(answer.confidence),
            **common,
        )
    if isinstance(question, NoulQuestion) and isinstance(answer, NoulAnswer):
        return NoulResult(noul=_probability(answer.noul), **common)
    raise DecisionError(
        f"the answer to {name!r} was not the primitive that was asked for", reason="malformed"
    )


def _pack(state: Any, questions: Mapping[str, Question]) -> list[dict[str, Question]]:
    """Splits questions into requests whose state and question text fit the byte budget.

    A single question larger than the budget still gets a request of its own,
    since there is nothing left to split; bounding the text is the caller's job.
    """
    base = state_bytes(state)
    batches: list[dict[str, Question]] = []
    current: dict[str, Question] = {}
    used = base
    for name, question in questions.items():
        size = len(name.encode("utf-8")) + len(
            json.dumps(question.to_payload(), default=str).encode("utf-8")
        )
        if current and used + size > MAX_REQUEST_BYTES:
            batches.append(current)
            current, used = {}, base
        current[name] = question
        used += size
    if current:
        batches.append(current)
    return batches


class JevDecider:
    """Answers decisions with OpenRouter's Decisions API.

    The model id is the pinned :data:`~app.services.decisions.openrouter.JEV_MODEL`;
    each result's ``model`` carries the exact snapshot that answered.

    Args:
        session_id: Groups this run's requests in OpenRouter's logs. Sent only
            when given.

    Raises:
        DeciderUnavailable: At construction, when ``OPENROUTER_API_KEY`` is empty.
    """

    kind = "jev"

    def __init__(self, session_id: str | None = None) -> None:
        if not settings.OPENROUTER_API_KEY:
            raise DeciderUnavailable(
                "decider 'jev' is not available: OPENROUTER_API_KEY is not set"
            )
        self._session_id = session_id

    @property
    def model_id(self) -> str:
        """The pinned model id that is asked."""
        return JEV_MODEL

    async def choice(
        self, state: Any, instructions: str, options: Mapping[str, str]
    ) -> ChoiceResult:
        """The option Jev picks, with the probability of each option offered."""
        if not options:
            raise ValueError("a choice needs at least one option")
        result = await self._ask(
            state, {"choice": ChoiceQuestion(instructions=instructions, criteria=options)}
        )
        if not isinstance(result["choice"], ChoiceResult):
            raise DecisionError("the answer to 'choice' was not a choice", reason="malformed")
        return result["choice"]

    async def score(self, state: Any, instructions: str, levels: Sequence[str]) -> ScoreResult:
        """The probability-weighted position on ``levels``, lowest first."""
        if not levels:
            raise ValueError("a score needs at least one level")
        result = await self._ask(
            state, {"score": ScoreQuestion(instructions=instructions, criteria=levels)}
        )
        if not isinstance(result["score"], ScoreResult):
            raise DecisionError("the answer to 'score' was not a score", reason="malformed")
        return result["score"]

    async def noul(self, state: Any, instructions: str) -> NoulResult:
        """The probability that the statement in ``instructions`` is true."""
        result = await self._ask(
            state,
            {"noul": NoulQuestion(instructions=instructions, true=NOUL_TRUE, false=NOUL_FALSE)},
        )
        if not isinstance(result["noul"], NoulResult):
            raise DecisionError("the answer to 'noul' was not a probability", reason="malformed")
        return result["noul"]

    async def batch(self, state: Any, questions: Mapping[str, Question]) -> dict[str, Result]:
        """Answers every question, splitting the fan-out across requests when it is large."""
        if not questions:
            return {}

        semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

        async def send(
            batch: dict[str, Question],
        ) -> tuple[dict[str, Question], DecisionResponse, float]:
            async with semaphore:
                started = time.perf_counter()
                response = await submit(state, batch, model=JEV_MODEL, session_id=self._session_id)
                elapsed = round((time.perf_counter() - started) * 1000, 2)
            return batch, response, elapsed

        responses = await asyncio.gather(*(send(batch) for batch in _pack(state, questions)))

        results: dict[str, Result] = {}
        for batch, response, elapsed in responses:
            for name in batch:
                results[name] = _result(name, batch[name], response, elapsed)
        return results

    async def _ask(self, state: Any, questions: Mapping[str, Question]) -> dict[str, Result]:
        """One request with one question, for the non-batched primitives."""
        started = time.perf_counter()
        response = await submit(state, questions, model=JEV_MODEL, session_id=self._session_id)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return {
            name: _result(name, question, response, elapsed) for name, question in questions.items()
        }
