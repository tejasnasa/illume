"""Routing metrics for the composed ``auto`` arm.

``auto`` asks a decider which preset to run and then reports the generation of the arm that
preset maps to. These metrics say what it chose, how often it fell back, what that cost and
scored against always running one arm, and whether it picked the arm that did best on each
item or merely a cheap one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from evals.run.records import Generation

AGENT_ARM = "agent"
RERANK_ARM = "structural_rerank"
ROUTABLE_ARMS = ("classic", "hybrid_rerank", "structural_rerank", "agent")
"""The arms the product's router can end up running."""


@dataclass(frozen=True)
class ArmOutcome:
    """How one arm did on one item.

    Attributes:
        recall: Answer recall, or ``None`` when the item is not scored by recall.
        cost_usd: What the pair cost.
    """

    recall: float | None
    cost_usd: float


Outcomes = Mapping[str, Mapping[str, ArmOutcome]]
"""``arm -> item id -> outcome``."""


@dataclass(frozen=True)
class ArmComparison:
    """Mean recall and cost of one arm over the items all compared arms share.

    Attributes:
        arm: The arm.
        n: Items averaged.
        mean_recall: Mean recall over those items; ``None`` when ``n`` is 0.
        mean_cost_usd: Mean cost over those items; ``None`` when ``n`` is 0.
    """

    arm: str
    n: int
    mean_recall: float | None
    mean_cost_usd: float | None


@dataclass(frozen=True)
class RoutingSummary:
    """What the routing did.

    Attributes:
        n: Auto records summarised.
        route_distribution: Records per route the decision chose (``"none"`` when it made no
            decision).
        target_distribution: Records per arm actually run.
        fallbacks: Records that used the fallback, per reason.
        fallback_count: Total fallbacks.
        comparison: Auto against always-agent and always-structural-rerank, where present, on
            the items every one of them has a recall for.
        confusion: ``(picked arm, best arm) -> count``.
        agreement: Share of confusion items where the picked arm was the best one; ``None``
            without any.
    """

    n: int
    route_distribution: Mapping[str, int]
    target_distribution: Mapping[str, int]
    fallbacks: Mapping[str, int]
    fallback_count: int
    comparison: tuple[ArmComparison, ...]
    confusion: Mapping[tuple[str, str], int]
    agreement: float | None


def picked_arm(generation: Generation) -> str | None:
    """The arm an ``auto`` record ran: its route's target, else the arm it was composed from."""
    if generation.route is not None:
        return generation.route.target_arm
    return generation.composed_from


def best_arm(
    item_id: str, outcomes: Outcomes, candidates: Sequence[str] = ROUTABLE_ARMS
) -> str | None:
    """The candidate arm with the best recall on an item, ties going to the cheaper arm.

    Equal recall and cost fall back to the arm name, so the answer is deterministic. Arms with
    no outcome or no recall for the item are not considered.

    Returns:
        The arm, or ``None`` when no candidate has a recall.
    """
    scored = [
        (arm, outcomes[arm][item_id])
        for arm in candidates
        if arm in outcomes
        and item_id in outcomes[arm]
        and outcomes[arm][item_id].recall is not None
    ]
    if not scored:
        return None
    return min(scored, key=lambda pair: (-(pair[1].recall or 0.0), pair[1].cost_usd, pair[0]))[0]


def route_confusion(
    auto: Iterable[Generation], outcomes: Outcomes, candidates: Sequence[str] = ROUTABLE_ARMS
) -> dict[tuple[str, str], int]:
    """Count (arm picked, arm that did best) over auto records.

    Records that picked no arm, or items where no candidate has a recall, are left out.
    """
    table: Counter[tuple[str, str]] = Counter()
    for generation in auto:
        picked = picked_arm(generation)
        if picked is None:
            continue
        best = best_arm(generation.item_id, outcomes, candidates)
        if best is not None:
            table[(picked, best)] += 1
    return dict(table)


def compare_arms(arms: Sequence[str], outcomes: Outcomes) -> tuple[ArmComparison, ...]:
    """Mean recall and cost of each arm over the items every listed arm has a recall for.

    Arms with no outcomes at all are dropped from the comparison before intersecting, so a run
    without ``structural_rerank`` still compares ``auto`` with ``agent``.
    """
    present = [arm for arm in arms if outcomes.get(arm)]
    if not present:
        return ()
    shared = set.intersection(
        *(
            {item for item, outcome in outcomes[arm].items() if outcome.recall is not None}
            for arm in present
        )
    )
    rows = []
    for arm in present:
        picked = [outcomes[arm][item] for item in sorted(shared)]
        n = len(picked)
        rows.append(
            ArmComparison(
                arm=arm,
                n=n,
                mean_recall=sum(o.recall or 0.0 for o in picked) / n if n else None,
                mean_cost_usd=sum(o.cost_usd for o in picked) / n if n else None,
            )
        )
    return tuple(rows)


def routing_summary(
    auto: Sequence[Generation],
    outcomes: Outcomes,
    *,
    auto_arm: str = "auto",
    candidates: Sequence[str] = ROUTABLE_ARMS,
) -> RoutingSummary:
    """Summarise a set of ``auto`` records.

    Args:
        auto: The composed records.
        outcomes: Recall and cost of every arm per item, ``auto`` included under ``auto_arm``.
        auto_arm: The key ``auto`` is stored under in ``outcomes``.
        candidates: The arms the router can pick, for the confusion table.

    Returns:
        The summary. Error records are counted in the distributions (a fallback is a fact about
        the router) but carry no recall, so they drop out of the comparison and confusion table.
    """
    routes = Counter((g.route.route if g.route and g.route.route else "none") for g in auto)
    targets = Counter(picked_arm(g) or "none" for g in auto)
    fallbacks = Counter(
        g.route.fallback_reason for g in auto if g.route is not None and g.route.fallback_reason
    )
    confusion = route_confusion(auto, outcomes, candidates)
    total = sum(confusion.values())
    agree = sum(count for (picked, best), count in confusion.items() if picked == best)
    return RoutingSummary(
        n=len(auto),
        route_distribution=dict(routes),
        target_distribution=dict(targets),
        fallbacks=dict(fallbacks),
        fallback_count=sum(fallbacks.values()),
        comparison=compare_arms([auto_arm, AGENT_ARM, RERANK_ARM], outcomes),
        confusion=confusion,
        agreement=agree / total if total else None,
    )


__all__ = [
    "AGENT_ARM",
    "RERANK_ARM",
    "ROUTABLE_ARMS",
    "ArmComparison",
    "ArmOutcome",
    "Outcomes",
    "RoutingSummary",
    "best_arm",
    "compare_arms",
    "picked_arm",
    "route_confusion",
    "routing_summary",
]
