"""Live spend tracking against a hard cap, and the projection of a planned run.

A run is allowed to spend up to ``cap_usd`` and is stopped, cleanly and before the next pair of
item and arm, once its metered spend reaches ``stop_usd``. Spend is read from each record's
``cost_usd``, so a restarted run rebuilds it from what is already on disk instead of starting
again from zero.

:func:`project` turns the per-arm cost measured so far into the cost of a larger planned run.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from evals.arms import AUTO, get_arm
from evals.run.pricing import PriceTable, UnpricedUsage
from evals.run.records import Generation, Judgment, RouteRecord, Usage


class BudgetStop(Exception):
    """The run must stop before starting the next pair.

    Attributes:
        reason: Why: the stop threshold was reached, or the next pair would pass the cap.
        spent_usd: The spend when the decision was made.
    """

    def __init__(self, reason: str, spent_usd: float) -> None:
        self.reason = reason
        self.spent_usd = spent_usd
        super().__init__(reason)


class UnpricedSpend(RuntimeError):
    """Spend that could not be priced, so the budget can no longer be trusted.

    Attributes:
        models: The models the table has no price for.
        cost_usd: The part of the usage that was priced; it has been charged.
    """

    def __init__(self, models: Iterable[str], cost_usd: float) -> None:
        self.models = sorted(set(models))
        self.cost_usd = cost_usd
        super().__init__(f"no price for model(s) {', '.join(self.models)}")


@dataclass
class Budget:
    """Spend against a cap.

    Attributes:
        cap_usd: The most the run may spend.
        stop_usd: The spend at which the run stops cleanly; below the cap, so the pair in flight
            when the threshold is crossed still fits.
        spent_usd: The spend so far.
    """

    cap_usd: float
    stop_usd: float
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        if not 0 < self.stop_usd <= self.cap_usd:
            raise ValueError("the stop threshold must be above zero and at most the cap")

    @property
    def remaining_usd(self) -> float:
        """What is left before the cap."""
        return self.cap_usd - self.spent_usd

    def charge(self, usages: Sequence[Usage], table: PriceTable, now: datetime) -> float:
        """Adds the cost of metered calls to the spend.

        Args:
            usages: The calls.
            table: The price table.
            now: When the calls were made, for peak and off-peak rates.

        Returns:
            The cost that was added.

        Raises:
            UnpricedSpend: When some call could not be priced. The ones that could be have been
                charged already.
        """
        total = 0.0
        unpriced: list[str] = []
        for usage in usages:
            try:
                total += table.cost(usage, now)
            except UnpricedUsage as failure:
                unpriced.append(failure.model)
        self.spent_usd += total
        if unpriced:
            raise UnpricedSpend(unpriced, total)
        return total

    def would_exceed(self, next_estimate_usd: float | None) -> bool:
        """Whether spending ``next_estimate_usd`` more would pass the cap.

        Without an estimate the answer is no: only a measured cost can predict an overrun.
        """
        return next_estimate_usd is not None and self.spent_usd + next_estimate_usd > self.cap_usd

    def check_before_next(self) -> None:
        """Raises :class:`BudgetStop` once the spend has reached the stop threshold."""
        if self.spent_usd >= self.stop_usd:
            raise BudgetStop(
                f"spend ${self.spent_usd:.4f} reached the stop at ${self.stop_usd:.2f}",
                self.spent_usd,
            )

    def restore(
        self,
        generations: Iterable[Generation],
        routes: Iterable[RouteRecord] = (),
        *,
        judgments: Iterable[Judgment] = (),
    ) -> float:
        """Sets the spend to what existing records say was spent.

        Composed records are skipped: their cost is a copy of the target's, already counted.

        Returns:
            The reconstructed spend.
        """
        self.spent_usd = spent_in(generations, routes, judgments=judgments)
        return self.spent_usd


def spent_in(
    generations: Iterable[Generation],
    routes: Iterable[RouteRecord] = (),
    *,
    judgments: Iterable[Judgment] = (),
) -> float:
    """The total spend recorded on generation, routing and judgment records.

    Composed generations are excluded because their cost is a copy of their target's. A judgment
    reused from another record carries no cost of its own.
    """
    return (
        sum(g.cost_usd or 0.0 for g in generations if g.composed_from is None)
        + sum(r.cost_usd or 0.0 for r in routes)
        + sum(j.cost_usd or 0.0 for j in judgments)
    )


# --- projection ---------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionPlan:
    """A run to project.

    Attributes:
        arms: The arms to run, every one on every item.
        items: How many items.
        repeats: How many times each agent arm runs on the repeat subset.
        repeats_subset: How many items the repeats cover; the rest run once.
    """

    arms: tuple[str, ...]
    items: int
    repeats: int = 1
    repeats_subset: int = 0

    def runs(self, arm: str) -> int:
        """How many generations the plan makes with ``arm``."""
        extra = 0
        if self.repeats > 1 and not get_arm(arm).composed and get_arm(arm).is_agent:
            extra = (self.repeats - 1) * min(self.repeats_subset, self.items)
        return self.items + extra


@dataclass(frozen=True)
class ArmProjection:
    """The projected cost of one arm.

    Attributes:
        arm: The arm.
        measured: How many measured generations the mean and p95 come from.
        mean_usd: Mean cost per generation.
        p95_usd: The 95th percentile cost per generation.
        runs: How many generations the plan makes.
        expected_usd: ``mean_usd * runs``.
        high_usd: ``p95_usd * runs``, for a pessimistic total.
    """

    arm: str
    measured: int
    mean_usd: float
    p95_usd: float
    runs: int
    expected_usd: float
    high_usd: float


@dataclass
class Projection:
    """A projected run.

    Attributes:
        arms: One entry per arm that has measurements.
        unmeasured: Arms of the plan with no measured cost; they are not in the totals.
        expected_usd: The sum of the arms' expected costs.
        high_usd: The sum of the arms' high costs.
    """

    arms: list[ArmProjection] = field(default_factory=list)
    unmeasured: list[str] = field(default_factory=list)

    @property
    def expected_usd(self) -> float:
        """The projected total from mean costs."""
        return sum(arm.expected_usd for arm in self.arms)

    @property
    def high_usd(self) -> float:
        """The projected total from p95 costs."""
        return sum(arm.high_usd for arm in self.arms)


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def project(records: Iterable[Generation], plan: ProjectionPlan) -> Projection:
    """Projects a planned run from the per-item cost measured on existing records.

    The cost per generation of an arm is the mean and 95th percentile of its records' ``cost_usd``
    (every attempt included). The composed ``auto`` arm costs only its routing decision, because
    the arm it copies is already in the plan. When a pair was recorded more than once, only the
    last record counts.

    Args:
        records: Measured generations, normally from earlier runs.
        plan: The run to project.

    Returns:
        The projection; arms with no measured record are listed in ``unmeasured``.
    """
    latest: dict[str, Generation] = {}
    for record in records:
        latest[record.record_key] = record
    costs: dict[str, list[float]] = defaultdict(list)
    for record in latest.values():
        if record.composed_from is not None:
            cost = record.route.cost_usd if record.route is not None else None
        else:
            cost = record.cost_usd
        if cost is not None:
            costs[record.arm].append(cost)

    projection = Projection()
    for arm in plan.arms:
        measured = sorted(costs.get(arm, ()))
        if not measured:
            projection.unmeasured.append(arm)
            continue
        runs = plan.items if arm == AUTO else plan.runs(arm)
        mean = sum(measured) / len(measured)
        p95 = _percentile(measured, 0.95)
        projection.arms.append(
            ArmProjection(
                arm=arm,
                measured=len(measured),
                mean_usd=mean,
                p95_usd=p95,
                runs=runs,
                expected_usd=mean * runs,
                high_usd=p95 * runs,
            )
        )
    return projection


__all__ = [
    "ArmProjection",
    "Budget",
    "BudgetStop",
    "Projection",
    "ProjectionPlan",
    "UnpricedSpend",
    "project",
    "spent_in",
]
