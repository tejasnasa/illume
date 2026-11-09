"""The decisions the pipeline makes, with the wording and thresholds each one uses.

Each function here is one decision point: it assembles the state, asks the
decider, applies the threshold from the configuration, and records what it
decided. Keeping the prompts in one module means the decision model and the LLM
stand-in are asked the same question, which is what makes their answers
comparable, and it keeps every threshold visible instead of buried in a node.

Thresholds are passed in rather than read from a global. The planning
threshold is a field on :class:`~app.services.retrieval.config.PlannerConfig`,
so an evaluation arm can vary it; the default here is read from that field, so
the two cannot drift apart.

When the decider's answer is a placeholder for unusable output (``defaulted``),
each point takes its own safe side rather than trusting it: the route is not
accepted and planning does not run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.services.decisions.base import (
    ChoiceResult,
    Decider,
    RecordDecision,
    Result,
    record_decision,
)
from app.services.retrieval.config import PlannerConfig
from app.services.retrieval.query import HistoryMessage

_PLANNER = PlannerConfig()

# --- bounds -----------------------------------------------------------------

MAX_QUESTION_CHARS = 4_000
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_MESSAGE_CHARS = 500
MAX_STATE_CHARS = 12_000

MAX_PASSAGE_CHARS = 1_500
MAX_RELEVANCE_QUESTION_CHARS = 1_000


def _clip(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` characters with a visible marker."""
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"


def _bounded(text: str) -> str:
    """The state bounded to :data:`MAX_STATE_CHARS`."""
    return _clip(text, MAX_STATE_CHARS)


async def _record(recorder: RecordDecision | None, point: str, state: Any, result: Result) -> None:
    """Writes the decision record, when the caller keeps one."""
    if recorder is not None:
        await record_decision(recorder, point, state, result)


# --- routing ----------------------------------------------------------------

ROUTE_CONFIDENCE = 0.6
"""How sure the route decision must be before it is trusted."""


class Route(StrEnum):
    """What kind of question was asked."""

    LOCAL = "local"
    RELATIONAL = "relational"
    GLOBAL = "global"
    HISTORY = "history"
    OUT_OF_SCOPE = "out_of_scope"


ROUTE_OPTIONS: dict[str, str] = {
    Route.LOCAL.value: "one place in the code: a single function, class, file or module",
    Route.RELATIONAL.value: (
        "how files or modules connect: imports, dependents, or a path between two files"
    ),
    Route.GLOBAL.value: (
        "the architecture, the stack, the entry points, or the repository as a whole"
    ),
    Route.HISTORY.value: "why or when something changed, or who changed it",
    Route.OUT_OF_SCOPE.value: (
        "not a question about this repository's code, or not answerable from it"
    ),
}

_ROUTE_INSTRUCTIONS = (
    "Classify the question by what answering it needs. Choose 'local' when one place in "
    "the code holds the answer. Choose 'relational' when the answer is about how files or "
    "modules connect: what imports what, what breaks, or a path from one file to another. "
    "Choose 'global' for architecture, the technology stack, entry points, or a summary of "
    "the whole repository. Choose 'history' for why or when something changed, or who "
    "changed it. Choose 'out_of_scope' when the question is not about this repository's "
    "code, or cannot be answered from it."
)


@dataclass(frozen=True)
class RouteDecision:
    """What kind of question this is, and whether to trust the answer.

    Attributes:
        route: The route the decider chose.
        accepted: Whether the decider was confident enough to trust it. When
            ``False`` the caller should take the expensive, general path rather
            than act on a guess.
        confidence: The decider's confidence, when reported.
        probabilities: The probability of each route, when reported.
        model: The model that answered.
        defaulted: Whether the decider's output was unusable.
    """

    route: Route
    accepted: bool
    confidence: float | None
    probabilities: dict[str, float]
    model: str
    defaulted: bool = False


def _route_state(question: str, history: Sequence[HistoryMessage]) -> str:
    """The question plus the recent conversation, bounded."""
    parts = [f"Question:\n{_clip(question.strip(), MAX_QUESTION_CHARS)}"]
    recent = [message for message in history if message.content.strip()][-MAX_HISTORY_MESSAGES:]
    if recent:
        lines = "\n".join(
            f"{message.role}: {_clip(message.content.strip(), MAX_HISTORY_MESSAGE_CHARS)}"
            for message in recent
        )
        parts.append(f"Recent conversation:\n{lines}")
    return _bounded("\n\n".join(parts))


async def decide_route(
    decider: Decider,
    question: str,
    *,
    history: Sequence[HistoryMessage] = (),
    confidence_floor: float = ROUTE_CONFIDENCE,
    record: RecordDecision | None = None,
) -> RouteDecision:
    """Chooses the route for a question.

    Args:
        decider: Who makes the decision.
        question: The standalone question.
        history: Recent conversation, for follow-ups that only make sense with it.
        confidence_floor: The confidence at or above which the route is trusted.
        record: Where the decision record goes.

    Returns:
        The route, whether it cleared the confidence floor, and the probabilities.
    """
    state = _route_state(question, history)
    result: ChoiceResult = await decider.choice(state, _ROUTE_INSTRUCTIONS, ROUTE_OPTIONS)
    await _record(record, "route", state, result)
    try:
        route = Route(result.choice)
    except ValueError:
        route = Route.RELATIONAL
    return RouteDecision(
        route=route,
        accepted=(
            not result.defaulted
            and result.confidence is not None
            and result.confidence >= confidence_floor
        ),
        confidence=result.confidence,
        probabilities=dict(result.probabilities),
        model=result.model,
        defaulted=result.defaulted,
    )


# --- planning ---------------------------------------------------------------

_PLAN_INSTRUCTIONS = (
    "The statement to judge: answering the question needs several independent "
    "investigations, such as separate searches into different modules or into the "
    "repository's history, which can be done in parallel. A question that one search "
    "and a few reads can answer does not need several."
)


@dataclass(frozen=True)
class PlanDecision:
    """Whether a question is worth splitting across workers.

    Attributes:
        plan: Whether the probability cleared the threshold.
        probability: The probability that several investigations are needed.
        threshold: The probability the caller required.
        model: The model that answered.
        defaulted: Whether the decider's output was unusable.
    """

    plan: bool
    probability: float
    threshold: float
    model: str
    defaulted: bool = False


async def decide_plan(
    decider: Decider,
    question: str,
    *,
    threshold: float = _PLANNER.plan_threshold,
    record: RecordDecision | None = None,
) -> PlanDecision:
    """Decides whether the question needs parallel investigation.

    Args:
        decider: Who makes the decision.
        question: The standalone question.
        threshold: The probability at or above which planning runs.
        record: Where the decision record goes.
    """
    state = _bounded(f"Question:\n{_clip(question.strip(), MAX_QUESTION_CHARS)}")
    result = await decider.noul(state, _PLAN_INSTRUCTIONS)
    await _record(record, "plan", state, result)
    return PlanDecision(
        plan=not result.defaulted and result.noul >= threshold,
        probability=result.noul,
        threshold=threshold,
        model=result.model,
        defaulted=result.defaulted,
    )


# --- relevance --------------------------------------------------------------

RELEVANCE_LEVELS: tuple[str, ...] = (
    "unrelated",
    "mentions the topic",
    "partially answers",
    "directly answers",
)

_RELEVANCE_INSTRUCTIONS = (
    "Rate how well the passage below answers the question in the state. The passage "
    "comes from a code repository. A passage that shares vocabulary with the question "
    "but does not help answer it belongs near 'mentions the topic', not higher."
    "\n\nPassage ({key}):\n{text}"
)


def relevance_state(question: str) -> str:
    """The state of a relevance question: the question alone.

    The passage goes in the instructions instead, so one request can score many
    passages against the same state. The Jev reranker builds its requests from
    this and :func:`relevance_instructions`, so the reranker and this decision
    point ask exactly the same question.
    """
    return f"Question about a code repository:\n{_clip(question, MAX_RELEVANCE_QUESTION_CHARS)}"


def relevance_instructions(key: str, passage: str) -> str:
    """The instructions of a relevance question, carrying one bounded passage."""
    return _RELEVANCE_INSTRUCTIONS.format(
        key=key or "unknown", text=_clip(passage, MAX_PASSAGE_CHARS)
    )


@dataclass(frozen=True)
class RelevanceDecision:
    """How relevant one passage is to the question.

    Attributes:
        score: The probability-weighted position on the rubric, ``0`` to ``3``.
        level: The rubric level nearest to the score.
        confidence: The decider's confidence, when reported.
        model: The model that answered.
        defaulted: Whether the decider's output was unusable, in which case the
            score is the lowest level.
    """

    score: float
    level: str
    confidence: float | None
    model: str
    defaulted: bool = False


async def decide_relevance(
    decider: Decider,
    question: str,
    passage: str,
    *,
    key: str = "",
    record: RecordDecision | None = None,
) -> RelevanceDecision:
    """Scores one passage's relevance to the question.

    Args:
        decider: Who makes the decision.
        question: The standalone question.
        passage: The candidate text, bounded.
        key: The passage's citation key, for the state and the log.
        record: Where the decision record goes.
    """
    state = relevance_state(question.strip())
    result = await decider.score(state, relevance_instructions(key, passage), RELEVANCE_LEVELS)
    await _record(record, "relevance", state, result)
    # Half-up rather than ``round``: a score exactly between two levels should
    # not be pulled to the even one, which would read as an accident of Python's
    # banker's rounding rather than a rule.
    score = 0.0 if result.defaulted else result.score
    position = min(max(int(score + 0.5), 0), len(RELEVANCE_LEVELS) - 1)
    return RelevanceDecision(
        score=score,
        level=RELEVANCE_LEVELS[position],
        confidence=result.confidence,
        model=result.model,
        defaulted=result.defaulted,
    )
