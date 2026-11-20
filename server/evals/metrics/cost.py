"""Cost metrics: dollars per question, tokens, latency percentiles, dollars per correct answer.

Dollars come from each record's own ``cost_usd``, which the runner sets to everything the pair
cost including retries (for a composed ``auto`` record, its target's cost plus the routing
decision). Summing a composed record's copied usages on top of its target's would count the
target twice, so token totals and costs are only ever taken per record, and a composed record
and its target are not added together by anything here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from evals.metrics.answer import AnswerScores
from evals.run.pricing import PriceTable
from evals.run.records import Generation

DEFAULT_CORRECT_THRESHOLD = 1.0
"""Recall at which a change-set answer counts as correct: every scored gold file listed."""

_EPSILON = 1e-9


@dataclass(frozen=True)
class Tokens:
    """Metered token totals.

    Attributes:
        input: Input tokens, cached ones included.
        cached: Input tokens served from the provider's cache.
        output: Output tokens.
    """

    input: int = 0
    cached: int = 0
    output: int = 0


@dataclass(frozen=True)
class CostSummary:
    """Cost and latency over a set of generations.

    Attributes:
        n: Generations summarised.
        total_usd: Their summed cost.
        per_question_usd: ``total_usd / n``; ``None`` when ``n`` is 0.
        tokens: Summed tokens.
        latency_p50_ms: Median latency; ``None`` when ``n`` is 0.
        latency_p95_ms: 95th percentile latency; ``None`` when ``n`` is 0.
    """

    n: int
    total_usd: float
    per_question_usd: float | None
    tokens: Tokens
    latency_p50_ms: float | None
    latency_p95_ms: float | None


def generation_cost(
    generation: Generation, table: PriceTable | None = None, now: datetime | None = None
) -> float:
    """What one generation cost, in dollars.

    The recorded ``cost_usd`` wins. Without one, a given price table prices the usages at
    ``now``; with neither, the costs the providers reported are summed (calls that reported
    none add nothing).

    Args:
        generation: The record.
        table: A price table, for records the runner has not priced.
        now: When the calls were made; required with ``table``.

    Raises:
        ValueError: If a table is given without ``now``.
    """
    if generation.cost_usd is not None:
        return generation.cost_usd
    if table is None:
        return generation.reported_cost()
    if now is None:
        raise ValueError("pricing usages needs the time they were made")
    return sum(table.cost(usage, now) for usage in generation.usages)


def token_totals(generation: Generation) -> Tokens:
    """Input, cached and output tokens over a record's own usages."""
    return Tokens(
        input=sum(u.input_tokens for u in generation.usages),
        cached=sum(u.cached_input_tokens for u in generation.usages),
        output=sum(u.output_tokens for u in generation.usages),
    )


def percentile(values: Sequence[float], q: float) -> float | None:
    """The ``q`` percentile (0 to 100) by linear interpolation between order statistics.

    Edge cases: ``None`` for no values; one value is every percentile of itself.
    """
    if not values:
        return None
    if not 0 <= q <= 100:
        raise ValueError("q must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def cost_summary(
    generations: Iterable[Generation],
    table: PriceTable | None = None,
    now: datetime | None = None,
) -> CostSummary:
    """Summarise cost, tokens and latency over generations.

    Callers decide which records belong: include error records to count what failed attempts
    cost, leave them out for the cost of answers that were scored.
    """
    rows = list(generations)
    costs = [generation_cost(g, table, now) for g in rows]
    tokens = [token_totals(g) for g in rows]
    latencies = [g.latency_ms for g in rows]
    total = sum(costs)
    return CostSummary(
        n=len(rows),
        total_usd=total,
        per_question_usd=total / len(rows) if rows else None,
        tokens=Tokens(
            input=sum(t.input for t in tokens),
            cached=sum(t.cached for t in tokens),
            output=sum(t.output for t in tokens),
        ),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
    )


def correct_count(
    scores: Iterable[AnswerScores | None], threshold: float = DEFAULT_CORRECT_THRESHOLD
) -> int:
    """How many answers are correct: recall at or above ``threshold``.

    For change-set items "correct" is recall of 1.0 on the scored gold: every required file
    listed, however many extra were listed (precision is reported separately). Unscored items
    (``None``, or recall ``None`` for an empty gold) are never correct.
    """
    return sum(
        1
        for score in scores
        if score is not None and score.recall is not None and score.recall >= threshold - _EPSILON
    )


def dollars_per_correct(
    total_usd: float,
    scores: Iterable[AnswerScores | None],
    threshold: float = DEFAULT_CORRECT_THRESHOLD,
) -> float | None:
    """Total cost divided by the number of correct answers; ``None`` when none is correct.

    The total should cover every question asked, wrong answers included, which is what makes
    this the price of one right answer.
    """
    correct = correct_count(scores, threshold)
    return total_usd / correct if correct else None


__all__ = [
    "DEFAULT_CORRECT_THRESHOLD",
    "CostSummary",
    "Tokens",
    "correct_count",
    "cost_summary",
    "dollars_per_correct",
    "generation_cost",
    "percentile",
    "token_totals",
]
