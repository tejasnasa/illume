"""The low-level client for OpenRouter's Decisions API.

A decision model returns typed answers with calibrated probabilities rather than
text, so chat SDKs do not work with it. One request carries a ``state`` (the
context) and any number of named questions; the response carries one answer per
question. Three question types exist:

* ``score``: a level on an ordered rubric. The answer's ``score`` is the
  probability-weighted position on that rubric, from ``0`` to ``n - 1``.
* ``choice``: one option from a set, with a probability per option.
* ``noul``: the probability that a statement is true.

The endpoint is an alpha path, so the URL is a module constant. Every failure
surfaces as a :class:`DecisionError` whose message says what went wrong; callers
decide whether that degrades or fails.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

# The model asked for. Pinned, never the ``-latest`` alias: a silent model change
# would make results from different dates incomparable. Each response names the
# exact snapshot that answered, and that is what callers log.
JEV_MODEL = "typesafe/jev-1.14"

# Text sent in one request, in UTF-8 bytes. Above this Jev switches to a slower,
# less accurate long-context mode, so callers split a large fan-out instead.
MAX_REQUEST_BYTES = 32_000

REQUEST_TIMEOUT_SECONDS = 30.0

QuestionType = Literal["score", "choice", "noul"]


class DecisionError(RuntimeError):
    """A decision request that did not produce usable answers.

    Attributes:
        reason: A short machine-readable category: ``bad_request``,
            ``unauthorized``, ``out_of_credit``, ``too_large``, ``rate_limited``,
            ``server``, ``timeout``, ``transport``, ``unexpected_status`` or
            ``malformed``.
        status_code: The HTTP status, when a response was received.
    """

    def __init__(
        self, message: str, *, reason: str = "unexpected_status", status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


class DecisionUnavailable(DecisionError):
    """No OpenRouter key is configured, so no request was made."""


# --- questions --------------------------------------------------------------


@dataclass(frozen=True)
class ScoreQuestion:
    """How well something fits an ordered rubric.

    Attributes:
        instructions: What is being scored.
        criteria: The levels, lowest first.
    """

    instructions: str
    criteria: Sequence[str]
    type: QuestionType = field(default="score", init=False)

    def to_payload(self) -> dict[str, Any]:
        """The question as the API's JSON object."""
        return {
            "type": "score",
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


@dataclass(frozen=True)
class ChoiceQuestion:
    """Which one of several options applies.

    Attributes:
        instructions: What is being decided.
        criteria: Each option's name mapped to its description.
    """

    instructions: str
    criteria: Mapping[str, str]
    type: QuestionType = field(default="choice", init=False)

    def to_payload(self) -> dict[str, Any]:
        """The question as the API's JSON object."""
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


@dataclass(frozen=True)
class NoulQuestion:
    """How likely a statement is to be true.

    Attributes:
        instructions: The statement, and what to weigh.
        true: What it means for the statement to hold.
        false: What it means for it not to.
    """

    instructions: str
    true: str
    false: str
    type: QuestionType = field(default="noul", init=False)

    def to_payload(self) -> dict[str, Any]:
        """The question as the API's JSON object."""
        return {
            "type": "noul",
            "instructions": self.instructions,
            "criteria": {"true": self.true, "false": self.false},
        }


Question = ScoreQuestion | ChoiceQuestion | NoulQuestion


# --- answers ----------------------------------------------------------------


@dataclass(frozen=True)
class ScoreAnswer:
    """A level on the rubric.

    Attributes:
        score: The probability-weighted position, ``0`` to ``n - 1``.
        probabilities: Probability of each level index.
        confidence: The model's confidence, when reported.
        legend: The rubric as the API echoed it, when reported.
    """

    score: float
    probabilities: dict[int, float] = field(default_factory=dict)
    confidence: float | None = None
    legend: Any = None


@dataclass(frozen=True)
class ChoiceAnswer:
    """The chosen option.

    Attributes:
        choice: The winning option's name.
        probabilities: Probability of each option.
        confidence: The model's confidence, when reported.
    """

    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


@dataclass(frozen=True)
class NoulAnswer:
    """The probability that the statement is true."""

    noul: float


Answer = ScoreAnswer | ChoiceAnswer | NoulAnswer


@dataclass(frozen=True)
class DecisionResponse:
    """The parsed response to one request.

    Attributes:
        answers: One typed answer per question name.
        model: The exact snapshot that answered, which can be more specific
            than the model asked for.
        provider: The upstream provider, when reported.
        cost: ``usage.cost`` for this request, when reported.
        input_tokens: ``usage.input_tokens``, when reported.
        output_tokens: ``usage.output_tokens``, when reported.
        id: The response id, when reported.
        raw: The response body as received, for the log.
    """

    answers: dict[str, Answer]
    model: str
    provider: str | None
    cost: float | None
    input_tokens: int | None
    output_tokens: int | None
    id: str | None
    raw: dict[str, Any]


# --- parsing ----------------------------------------------------------------


def _number(value: Any, what: str) -> float:
    """A JSON number as a float.

    Raises:
        DecisionError: When the value is not a number (booleans are not numbers here).
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DecisionError(f"the response's {what} was not a number", reason="malformed")
    return float(value)


def _optional_number(value: Any) -> float | None:
    """A JSON number as a float, or ``None`` when it is absent or not a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _parse_answer(name: str, question: Question, data: Any) -> Answer:
    """Builds the typed answer for one question from its JSON object."""
    if not isinstance(data, dict):
        raise DecisionError(f"the answer to {name!r} was not an object", reason="malformed")

    if isinstance(question, ScoreQuestion):
        levels: dict[int, float] = {}
        raw_levels = data.get("probabilities")
        if isinstance(raw_levels, dict):
            for level, probability in raw_levels.items():
                try:
                    levels[int(level)] = _number(probability, "level probability")
                except ValueError:
                    raise DecisionError(
                        f"the answer to {name!r} had a non-numeric level {level!r}",
                        reason="malformed",
                    ) from None
        return ScoreAnswer(
            score=_number(data.get("score"), f"score for {name!r}"),
            probabilities=levels,
            confidence=_optional_number(data.get("confidence")),
            legend=data.get("legend"),
        )

    if isinstance(question, ChoiceQuestion):
        choice = data.get("choice")
        if not isinstance(choice, str):
            raise DecisionError(f"the answer to {name!r} had no choice", reason="malformed")
        raw_options = data.get("probabilities")
        options = (
            {
                str(option): _number(probability, "option probability")
                for option, probability in raw_options.items()
            }
            if isinstance(raw_options, dict)
            else {}
        )
        return ChoiceAnswer(
            choice=choice,
            probabilities=options,
            confidence=_optional_number(data.get("confidence")),
        )

    return NoulAnswer(noul=_number(data.get("noul"), f"noul for {name!r}"))


def _parse_response(body: Any, questions: Mapping[str, Question]) -> DecisionResponse:
    """Parses a response body against the questions that were asked.

    Raises:
        DecisionError: When the body is not an object, an answer is missing or
            malformed, or the snapshot is not named.
    """
    if not isinstance(body, dict):
        raise DecisionError("the decisions response was not a JSON object", reason="malformed")
    raw_answers = body.get("answers")
    if not isinstance(raw_answers, dict):
        raise DecisionError("the decisions response had no 'answers' object", reason="malformed")

    answers: dict[str, Answer] = {}
    for name, question in questions.items():
        if name not in raw_answers:
            raise DecisionError(
                f"the decisions response had no answer for {name!r}", reason="malformed"
            )
        answers[name] = _parse_answer(name, question, raw_answers[name])

    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise DecisionError("the decisions response did not name the model", reason="malformed")
    raw_usage = body.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    provider = body.get("provider")
    identifier = body.get("id")
    return DecisionResponse(
        answers=answers,
        model=model,
        provider=provider if isinstance(provider, str) else None,
        cost=_optional_number(usage.get("cost")),
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        id=identifier if isinstance(identifier, str) else None,
        raw=body,
    )


# --- errors -----------------------------------------------------------------

_STATUS_MESSAGES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "the decisions request was rejected as malformed (400)"),
    401: ("unauthorized", "OpenRouter rejected the API key (401)"),
    402: ("out_of_credit", "the OpenRouter account is out of credit (402)"),
    413: ("too_large", "the decisions request was too large (413)"),
    429: ("rate_limited", "OpenRouter rate-limited the decisions request (429)"),
}


def _error_detail(response: httpx.Response) -> str:
    """The provider's own error message, when the body has one, bounded."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200].strip()
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"][:200]
    if isinstance(error, str):
        return error[:200]
    return ""


def _status_error(response: httpx.Response) -> DecisionError:
    """The error for a non-success status, with the provider's explanation appended."""
    status = response.status_code
    if status in _STATUS_MESSAGES:
        reason, message = _STATUS_MESSAGES[status]
    elif status >= 500:
        reason, message = "server", f"OpenRouter failed to answer the decisions request ({status})"
    else:
        reason, message = "unexpected_status", f"unexpected status {status} from the decisions API"
    detail = _error_detail(response)
    if detail:
        message = f"{message}: {detail}"
    return DecisionError(message, reason=reason, status_code=status)


# --- the request ------------------------------------------------------------


def build_body(
    state: Any,
    questions: Mapping[str, Question],
    *,
    model: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """The request body. ``session_id`` is included only when given."""
    body: dict[str, Any] = {
        "model": model,
        "state": state,
        "questions": {name: question.to_payload() for name, question in questions.items()},
    }
    if session_id is not None:
        body["session_id"] = session_id
    return body


async def submit(
    state: Any,
    questions: Mapping[str, Question],
    *,
    model: str,
    session_id: str | None = None,
) -> DecisionResponse:
    """Sends one decisions request and parses the answers.

    Args:
        state: The context: a string, a JSON object or an array.
        questions: Question name to question. Many questions in one request is
            the intended use; each is answered independently.
        model: The model id. Callers pin a versioned id so results stay comparable.
        session_id: Groups requests in OpenRouter's logs; never sent to the
            provider. Omitted from the body when ``None``.

    Returns:
        The typed answers, the exact model snapshot, the cost and the raw body.

    Raises:
        DecisionUnavailable: When ``OPENROUTER_API_KEY`` is empty.
        DecisionError: On a non-success status, a timeout, a transport failure
            or a body that does not match the questions.
        ValueError: When ``questions`` is empty.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        raise DecisionUnavailable("OPENROUTER_API_KEY is not configured", reason="unauthorized")
    if not questions:
        raise ValueError("a decisions request needs at least one question")

    body = build_body(state, questions, model=model, session_id=session_id)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                DECISIONS_URL,
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        raise DecisionError(
            f"the decisions request timed out after {REQUEST_TIMEOUT_SECONDS:g} seconds",
            reason="timeout",
        ) from None
    except httpx.HTTPError as error:
        raise DecisionError(
            f"the decisions request failed: {type(error).__name__}: {error}"[:300],
            reason="transport",
        ) from None

    if response.status_code >= 400:
        raise _status_error(response)

    try:
        parsed = response.json()
    except ValueError:
        raise DecisionError(
            "the decisions response was not valid JSON", reason="malformed"
        ) from None
    return _parse_response(parsed, questions)
