"""A cluster bootstrap for a ratio of means, which the paired difference statistics do not cover.

Some pre-registered criteria are ratios (the agent costs more than five times the reranked
structural arm; ``auto`` keeps at least 90% of the agent's recall). The resampling is the one the
paired comparisons use: repositories are fixed strata, clusters are drawn with replacement within
each, and every item of a drawn cluster comes with it.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RatioObs:
    """One item's numerator and denominator.

    Attributes:
        repo: The repository (a stratum).
        cluster: The cluster within the repository.
        num: The numerator, or ``None`` when it is missing.
        den: The denominator, or ``None`` when it is missing.
    """

    repo: str
    cluster: str
    num: float | None
    den: float | None


@dataclass(frozen=True)
class RatioResult:
    """A ratio of means with a percentile interval.

    Attributes:
        estimate: ``sum(num) / sum(den)`` on the observed items.
        lo: Lower end of the interval.
        hi: Upper end of the interval.
        n: Complete items.
        n_clusters: Distinct ``(repo, cluster)`` pairs among them.
        n_excluded: Items dropped for a missing side.
        n_boot: Resamples drawn.
        alpha: The interval covers ``1 - alpha``.
    """

    estimate: float
    lo: float
    hi: float
    n: int
    n_clusters: int
    n_excluded: int
    n_boot: int
    alpha: float


def ratio_bootstrap(
    obs: Sequence[RatioObs], *, n_boot: int = 10_000, seed: int, alpha: float = 0.05
) -> RatioResult:
    """The ratio of the mean numerator to the mean denominator, with a cluster bootstrap interval.

    Args:
        obs: One entry per item.
        n_boot: How many resamples to draw.
        seed: The seed of the resampling.
        alpha: The interval covers ``1 - alpha``.

    Returns:
        The estimate and interval with the item counts. A resample whose denominators sum to
        zero is skipped.

    Raises:
        ValueError: If there are no complete pairs, the denominators sum to zero or ``n_boot``
            is below 1.
    """
    if n_boot < 1:
        raise ValueError("need at least one resample")
    clusters: dict[tuple[str, str], tuple[float, float, int]] = {}
    excluded = 0
    for item in obs:
        if item.num is None or item.den is None:
            excluded += 1
            continue
        total_num, total_den, count = clusters.get((item.repo, item.cluster), (0.0, 0.0, 0))
        clusters[(item.repo, item.cluster)] = (
            total_num + item.num,
            total_den + item.den,
            count + 1,
        )
    if not clusters:
        raise ValueError("no complete pairs to compare")
    sum_num = sum(v[0] for v in clusters.values())
    sum_den = sum(v[1] for v in clusters.values())
    if sum_den == 0:
        raise ValueError("the denominators sum to zero")
    by_repo: dict[str, list[tuple[float, float]]] = {}
    for (repo, _), (numerator, denominator, _) in sorted(clusters.items()):
        by_repo.setdefault(repo, []).append((numerator, denominator))
    draw = random.Random(seed).randrange
    values: list[float] = []
    for _ in range(n_boot):
        total_num = total_den = 0.0
        for pairs in by_repo.values():
            size = len(pairs)
            for _ in range(size):
                numerator, denominator = pairs[draw(size)]
                total_num += numerator
                total_den += denominator
        if total_den != 0:
            values.append(total_num / total_den)
    estimate = sum_num / sum_den
    values.sort()
    if not values:
        return RatioResult(
            estimate, estimate, estimate, _items(clusters), len(clusters), excluded, n_boot, alpha
        )
    lo = values[min(len(values) - 1, int(alpha / 2 * len(values)))]
    hi = values[max(0, min(len(values) - 1, math.ceil((1 - alpha / 2) * len(values)) - 1))]
    return RatioResult(
        estimate=estimate,
        lo=min(lo, estimate),
        hi=max(hi, estimate),
        n=_items(clusters),
        n_clusters=len(clusters),
        n_excluded=excluded,
        n_boot=n_boot,
        alpha=alpha,
    )


def _items(clusters: dict[tuple[str, str], tuple[float, float, int]]) -> int:
    return sum(v[2] for v in clusters.values())


__all__ = ["RatioObs", "RatioResult", "ratio_bootstrap"]
