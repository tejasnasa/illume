"""Small statistics used across the eval: confidence intervals and agreement."""

import math
import random
import statistics
from collections import Counter
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval for a binomial proportion.

    Args:
        successes: How many trials had the outcome.
        n: How many trials there were.
        z: The normal quantile; 1.96 gives a 95% interval.

    Returns:
        ``(lower, upper)``, both within ``[0, 1]``. ``(0.0, 1.0)`` when ``n`` is 0.

    Raises:
        ValueError: If ``successes`` is outside ``0..n`` or ``n`` is negative.
    """
    if n < 0 or not 0 <= successes <= n:
        raise ValueError(f"need 0 <= successes <= n, got {successes} of {n}")
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def cohen_kappa(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> float:
    """Cohen's kappa for two raters over the same items (unweighted, categorical).

    Args:
        labels_a: The first rater's labels.
        labels_b: The second rater's labels, in the same item order.

    Returns:
        Agreement beyond chance, from -1 to 1. When both raters used one identical single
        label, chance agreement is 1 and the result is defined as 1.0.

    Raises:
        ValueError: If the sequences differ in length or are empty.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("both raters must label the same items")
    total = len(labels_a)
    if total == 0:
        raise ValueError("no labels to compare")
    observed = sum(a == b for a, b in zip(labels_a, labels_b, strict=True)) / total
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum(counts_a[label] * counts_b[label] for label in counts_a) / (total * total)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def weighted_kappa(
    labels_a: Sequence[Hashable],
    labels_b: Sequence[Hashable],
    categories: Sequence[Hashable] = (0, 1, 2, 3),
    weights: Literal["quadratic", "linear"] = "quadratic",
) -> float:
    """Weighted kappa for two raters over the same items and an ordered scale.

    A disagreement is penalised by how far apart the two labels are on the scale: with
    quadratic weights by the square of the distance, with linear weights by the distance.
    Kappa is ``1 - observed weighted disagreement / expected weighted disagreement``, the
    expectation taken from each rater's own label frequencies.

    Args:
        labels_a: The first rater's labels.
        labels_b: The second rater's labels, in the same item order.
        categories: The scale, in order; a label outside it is an error.
        weights: ``quadratic`` or ``linear``.

    Returns:
        Agreement beyond chance, from -1 to 1. When chance disagreement is zero (both raters
        used one identical single category) the result is defined as 1.0.

    Raises:
        ValueError: If the sequences differ in length or are empty, a label is not in
            ``categories``, there are fewer than two categories or ``weights`` is unknown.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("both raters must label the same items")
    total = len(labels_a)
    if total == 0:
        raise ValueError("no labels to compare")
    if len(categories) < 2:
        raise ValueError("a scale needs at least two categories")
    if weights not in ("quadratic", "linear"):
        raise ValueError(f"unknown weights {weights!r}")
    position = {category: index for index, category in enumerate(categories)}
    try:
        first = [position[label] for label in labels_a]
        second = [position[label] for label in labels_b]
    except KeyError as failure:
        raise ValueError(f"label {failure.args[0]!r} is not in the scale") from None

    span = len(categories) - 1

    def penalty(i: int, j: int) -> float:
        distance = abs(i - j) / span
        return distance * distance if weights == "quadratic" else distance

    counts_a = Counter(first)
    counts_b = Counter(second)
    observed = sum(penalty(a, b) for a, b in zip(first, second, strict=True)) / total
    expected = sum(
        counts_a[i] * counts_b[j] * penalty(i, j)
        for i in range(len(categories))
        for j in range(len(categories))
    ) / (total * total)
    if expected == 0:
        return 1.0
    return 1 - observed / expected


def weighted_kappa_interval(
    labels_a: Sequence[Hashable],
    labels_b: Sequence[Hashable],
    categories: Sequence[Hashable] = (0, 1, 2, 3),
    weights: Literal["quadratic", "linear"] = "quadratic",
    *,
    resamples: int = 2000,
    seed: int = 0,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """A bootstrap percentile interval for :func:`weighted_kappa`.

    Labelled pairs are resampled with replacement; the interval is the central ``confidence``
    share of the resampled kappas. It is seeded, so the same labels give the same interval.

    Args:
        labels_a: The first rater's labels.
        labels_b: The second rater's labels, in the same item order.
        categories: The scale, in order.
        weights: ``quadratic`` or ``linear``.
        resamples: How many bootstrap samples to draw.
        seed: The seed of the resampling.
        confidence: The share of resampled kappas the interval covers.

    Returns:
        ``(lower, upper)``.

    Raises:
        ValueError: On the conditions of :func:`weighted_kappa`, or ``resamples`` below 1.
    """
    point = weighted_kappa(labels_a, labels_b, categories, weights)
    if resamples < 1:
        raise ValueError("need at least one resample")
    generator = random.Random(seed)
    size = len(labels_a)
    kappas: list[float] = []
    for _ in range(resamples):
        chosen = [generator.randrange(size) for _ in range(size)]
        kappas.append(
            weighted_kappa(
                [labels_a[i] for i in chosen], [labels_b[i] for i in chosen], categories, weights
            )
        )
    kappas.sort()
    tail = (1 - confidence) / 2
    lower = kappas[min(len(kappas) - 1, int(tail * len(kappas)))]
    upper = kappas[max(0, min(len(kappas) - 1, math.ceil((1 - tail) * len(kappas)) - 1))]
    # A percentile interval can miss the point estimate on tiny, lopsided samples.
    return min(lower, point), max(upper, point)


# ---------------------------------------------------------------------------------------------
# Paired comparisons. Repositories are fixed (claims are scoped to them), and the unit that is
# resampled or permuted is the cluster: every item of one cluster (for example both variants of
# one pull request) moves together, because they are not independent observations.
# ---------------------------------------------------------------------------------------------

Statistic = Callable[[Sequence[float]], float]
Alternative = Literal["two-sided", "greater", "less"]

_EPSILON = 1e-12


@dataclass(frozen=True)
class PairedObs:
    """One item's metric under two arms.

    Attributes:
        repo: The repository the item belongs to; repositories are strata.
        cluster: The cluster id within the repository; items sharing it move together.
        a: The metric under arm A, or ``None`` when the arm has no usable result.
        b: The metric under arm B, or ``None`` when the arm has no usable result.
    """

    repo: str
    cluster: str
    a: float | None
    b: float | None


@dataclass(frozen=True)
class PairedSummary:
    """Counts shared by every paired result.

    Attributes:
        n: Items with both sides present.
        n_clusters: Distinct ``(repo, cluster)`` pairs among those items.
        n_excluded: Items dropped because either side was missing.
    """

    n: int
    n_clusters: int
    n_excluded: int


@dataclass(frozen=True)
class BootstrapResult(PairedSummary):
    """A paired point estimate with a percentile interval.

    Attributes:
        estimate: The statistic on the observed data (by default the mean of ``a - b``).
        lo: Lower end of the interval.
        hi: Upper end of the interval.
        n_boot: Resamples drawn.
        alpha: The interval covers ``1 - alpha``.
    """

    estimate: float
    lo: float
    hi: float
    n_boot: int
    alpha: float


@dataclass(frozen=True)
class PermutationResult(PairedSummary):
    """A cluster-level sign-flip test.

    Attributes:
        estimate: The observed mean of ``a - b``.
        p_value: The p-value for ``alternative``.
        alternative: The alternative the p-value is for.
        exact: True when all ``2 ** n_clusters`` sign patterns were enumerated.
        n_perm: Sign patterns evaluated.
    """

    estimate: float
    p_value: float
    alternative: str
    exact: bool
    n_perm: int


@dataclass(frozen=True)
class HolmOutcome:
    """One hypothesis after Holm correction.

    Attributes:
        raw: The unadjusted p-value.
        adjusted: The Holm-adjusted p-value, capped at 1 and monotone in the raw order.
        reject: Whether ``adjusted <= alpha``.
    """

    raw: float
    adjusted: float
    reject: bool


@dataclass(frozen=True)
class TostResult(PairedSummary):
    """Two one-sided tests for equivalence within ``+/- margin``.

    Attributes:
        estimate: The observed mean of ``a - b``.
        margin: The equivalence margin.
        p_lower: p-value of the one-sided test of ``difference <= -margin``.
        p_upper: p-value of the one-sided test of ``difference >= +margin``.
        p_value: ``max(p_lower, p_upper)``, the TOST p-value.
        equivalent: Whether ``p_value < alpha``.
        alpha: The level each one-sided test is run at.
    """

    estimate: float
    margin: float
    p_lower: float
    p_upper: float
    p_value: float
    equivalent: bool
    alpha: float


@dataclass(frozen=True)
class DirectionCounts(PairedSummary):
    """Which arm is ahead in each repository (description only).

    Attributes:
        per_repo: ``"a"``, ``"b"`` or ``"tie"`` for each repository, by its mean of ``a - b``.
        a_ahead: Repositories where A leads.
        b_ahead: Repositories where B leads.
        tied: Repositories with equal means.
    """

    per_repo: dict[str, str]
    a_ahead: int
    b_ahead: int
    tied: int


@dataclass(frozen=True)
class MinimumDetectable(PairedSummary):
    """The smallest true difference the data could have resolved.

    Attributes:
        mdd: ``(z_{1-alpha/2} + z_{power}) * se``.
        se: ``sd(cluster mean differences) / sqrt(n_clusters)``.
        alpha: The two-sided level.
        power: The target power.
    """

    mdd: float
    se: float
    alpha: float
    power: float


def mean_diff(diffs: Sequence[float]) -> float:
    """The mean of paired differences, the default statistic.

    Args:
        diffs: ``a - b`` for each item.

    Returns:
        The arithmetic mean.
    """
    return sum(diffs) / len(diffs)


_Clusters = dict[tuple[str, str], list[float]]


def _cluster_diffs(obs: Sequence[PairedObs]) -> tuple[_Clusters, int]:
    """Group complete pairs by ``(repo, cluster)``; count the incomplete ones."""
    clusters: _Clusters = {}
    excluded = 0
    for item in obs:
        if item.a is None or item.b is None:
            excluded += 1
            continue
        clusters.setdefault((item.repo, item.cluster), []).append(item.a - item.b)
    if not clusters:
        raise ValueError("no complete pairs to compare")
    return dict(sorted(clusters.items())), excluded


def _summary(clusters: _Clusters, excluded: int) -> PairedSummary:
    return PairedSummary(
        n=sum(len(v) for v in clusters.values()),
        n_clusters=len(clusters),
        n_excluded=excluded,
    )


def _by_repo(clusters: _Clusters) -> dict[str, list[list[float]]]:
    grouped: dict[str, list[list[float]]] = {}
    for (repo, _), diffs in clusters.items():
        grouped.setdefault(repo, []).append(diffs)
    return grouped


def _bootstrap_stats(clusters: _Clusters, stat: Statistic, n_boot: int, seed: int) -> list[float]:
    """The statistic over ``n_boot`` stratified cluster resamples."""
    if n_boot < 1:
        raise ValueError("need at least one resample")
    grouped = _by_repo(clusters)
    draw = random.Random(seed).randrange
    values: list[float] = []
    if stat is mean_diff:
        totals = {repo: [(sum(c), len(c)) for c in cs] for repo, cs in grouped.items()}
        for _ in range(n_boot):
            total = 0.0
            count = 0
            for pairs in totals.values():
                size = len(pairs)
                for _ in range(size):
                    cluster_sum, cluster_count = pairs[draw(size)]
                    total += cluster_sum
                    count += cluster_count
            values.append(total / count)
        return values
    for _ in range(n_boot):
        sample: list[float] = []
        for cs in grouped.values():
            size = len(cs)
            for _ in range(size):
                sample.extend(cs[draw(size)])
        values.append(stat(sample))
    return values


def _flat(clusters: _Clusters) -> list[float]:
    return [d for diffs in clusters.values() for d in diffs]


def paired_bootstrap_ci(
    obs: Sequence[PairedObs],
    *,
    stat: Statistic = mean_diff,
    n_boot: int = 10_000,
    seed: int,
    alpha: float = 0.05,
) -> BootstrapResult:
    """A percentile bootstrap interval for a paired statistic, resampling clusters.

    Repositories are fixed strata: within each repository, as many clusters as it has are
    drawn with replacement, and every item of a drawn cluster comes with it. Items missing
    either side are excluded and counted.

    Args:
        obs: One entry per item.
        stat: Maps the ``a - b`` differences of a sample to the statistic; the mean by default.
        n_boot: How many resamples to draw.
        seed: The seed of the resampling.
        alpha: The interval covers ``1 - alpha``.

    Returns:
        The estimate, the percentile interval, and ``n``, ``n_clusters`` and ``n_excluded``.

    Raises:
        ValueError: If there are no complete pairs or ``n_boot`` is below 1.
    """
    clusters, excluded = _cluster_diffs(obs)
    estimate = stat(_flat(clusters))
    values = sorted(_bootstrap_stats(clusters, stat, n_boot, seed))
    lo = values[min(len(values) - 1, int(alpha / 2 * len(values)))]
    hi = values[max(0, min(len(values) - 1, math.ceil((1 - alpha / 2) * len(values)) - 1))]
    return BootstrapResult(
        **vars(_summary(clusters, excluded)),
        estimate=estimate,
        lo=min(lo, estimate),
        hi=max(hi, estimate),
        n_boot=n_boot,
        alpha=alpha,
    )


def _as_extreme(value: float, observed: float, alternative: str) -> bool:
    if alternative == "greater":
        return value >= observed - _EPSILON
    if alternative == "less":
        return value <= observed + _EPSILON
    return abs(value) >= abs(observed) - _EPSILON


def paired_permutation_test(
    obs: Sequence[PairedObs],
    *,
    n_perm: int = 10_000,
    seed: int,
    alternative: Alternative = "two-sided",
) -> PermutationResult:
    """A paired sign-flip permutation test on the mean of ``a - b``, at the cluster level.

    Under the null the arms are exchangeable, so each cluster's A and B labels are swapped
    together, which negates every difference in that cluster. When ``2 ** n_clusters`` is at
    most ``n_perm`` every pattern is enumerated and ``p`` is the exact share at least as
    extreme. Otherwise ``n_perm`` random patterns are drawn and
    ``p = (extreme + 1) / (n_perm + 1)``, the add-one smoothing that keeps ``p`` above zero.

    Args:
        obs: One entry per item.
        n_perm: The enumeration limit and the number of random patterns.
        seed: The seed of the random patterns.
        alternative: ``two-sided``, ``greater`` (A above B) or ``less``.

    Returns:
        The p-value with ``n``, ``n_clusters`` and ``n_excluded``.

    Raises:
        ValueError: If there are no complete pairs, ``n_perm`` is below 1 or the alternative
            is unknown.
    """
    if alternative not in ("two-sided", "greater", "less"):
        raise ValueError(f"unknown alternative {alternative!r}")
    if n_perm < 1:
        raise ValueError("need at least one permutation")
    clusters, excluded = _cluster_diffs(obs)
    summary = _summary(clusters, excluded)
    sums = [sum(diffs) for diffs in clusters.values()]
    observed = sum(sums) / summary.n
    k = len(sums)
    if 2**k <= n_perm:
        extreme = 0
        for mask in range(2**k):
            total = sum(s if (mask >> i) & 1 else -s for i, s in enumerate(sums))
            extreme += _as_extreme(total / summary.n, observed, alternative)
        return PermutationResult(
            **vars(summary),
            estimate=observed,
            p_value=extreme / 2**k,
            alternative=alternative,
            exact=True,
            n_perm=2**k,
        )
    generator = random.Random(seed)
    extreme = 0
    for _ in range(n_perm):
        total = sum(s if generator.getrandbits(1) else -s for s in sums)
        extreme += _as_extreme(total / summary.n, observed, alternative)
    return PermutationResult(
        **vars(summary),
        estimate=observed,
        p_value=(extreme + 1) / (n_perm + 1),
        alternative=alternative,
        exact=False,
        n_perm=n_perm,
    )


def holm(pvalues: Mapping[str, float], alpha: float = 0.05) -> dict[str, HolmOutcome]:
    """Holm's step-down correction over one family of hypotheses.

    With the ``m`` raw p-values sorted ascending, the adjusted value at rank ``j``
    (1-based) is ``max over i <= j of min(1, (m - i + 1) * p_(i))``, which is monotone.

    Args:
        pvalues: Raw p-value by hypothesis name.
        alpha: The family-wise level.

    Returns:
        Raw p, adjusted p and the reject flag by name, in the input's order.

    Raises:
        ValueError: If a p-value is outside ``[0, 1]``.
    """
    for name, p in pvalues.items():
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"p-value for {name!r} is outside [0, 1]: {p}")
    ordered = sorted(pvalues.items(), key=lambda pair: pair[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[name] = running
    return {
        name: HolmOutcome(raw=p, adjusted=adjusted[name], reject=adjusted[name] <= alpha)
        for name, p in pvalues.items()
    }


def tost(
    obs: Sequence[PairedObs],
    *,
    margin: float,
    alpha: float = 0.05,
    n_boot: int = 10_000,
    seed: int,
) -> TostResult:
    """Two one-sided tests for equivalence of the mean of ``a - b`` within ``+/- margin``.

    Both tests use the same stratified cluster bootstrap as :func:`paired_bootstrap_ci`, so
    the equivalence verdict and the interval resample identically. The resampled estimates
    are re-centred on the observed one and shifted to each null boundary: with ``e*`` the
    centred resamples and ``d`` the observed mean, ``p_lower = (1 + #{-margin + e* >= d}) /
    (n_boot + 1)`` tests ``difference <= -margin`` and ``p_upper = (1 + #{margin + e* <= d})
    / (n_boot + 1)`` tests ``difference >= +margin``. Equivalence is declared when both are
    below ``alpha``. A non-significant difference test does not establish equivalence; this
    does.

    Args:
        obs: One entry per item.
        margin: The equivalence margin, in the metric's units; positive.
        alpha: The level of each one-sided test.
        n_boot: Resamples drawn.
        seed: The seed of the resampling.

    Returns:
        Both one-sided p-values, their maximum and the verdict.

    Raises:
        ValueError: If ``margin`` is not positive, or on the conditions of
            :func:`paired_bootstrap_ci`.
    """
    if margin <= 0:
        raise ValueError("the equivalence margin must be positive")
    clusters, excluded = _cluster_diffs(obs)
    estimate = mean_diff(_flat(clusters))
    centred = [v - estimate for v in _bootstrap_stats(clusters, mean_diff, n_boot, seed)]
    lower = sum(-margin + e >= estimate - _EPSILON for e in centred)
    upper = sum(margin + e <= estimate + _EPSILON for e in centred)
    p_lower = (1 + lower) / (n_boot + 1)
    p_upper = (1 + upper) / (n_boot + 1)
    p_value = max(p_lower, p_upper)
    return TostResult(
        **vars(_summary(clusters, excluded)),
        estimate=estimate,
        margin=margin,
        p_lower=p_lower,
        p_upper=p_upper,
        p_value=p_value,
        equivalent=p_value < alpha,
        alpha=alpha,
    )


def direction_counts(obs: Sequence[PairedObs]) -> DirectionCounts:
    """Which arm is ahead in each repository.

    This is a description, not a test: with a handful of repositories even a unanimous
    result is weak evidence (5 of 5 is p of about 0.06 two-sided under a coin flip), so it
    carries no significance and should be reported as a count beside the real test.

    Args:
        obs: One entry per item.

    Returns:
        The leader per repository (by mean ``a - b``) and the tallies.

    Raises:
        ValueError: If there are no complete pairs.
    """
    clusters, excluded = _cluster_diffs(obs)
    per_repo: dict[str, str] = {}
    for repo, groups in _by_repo(clusters).items():
        flat = [d for diffs in groups for d in diffs]
        mean = sum(flat) / len(flat)
        per_repo[repo] = "tie" if abs(mean) <= _EPSILON else ("a" if mean > 0 else "b")
    tallies = Counter(per_repo.values())
    return DirectionCounts(
        **vars(_summary(clusters, excluded)),
        per_repo=per_repo,
        a_ahead=tallies["a"],
        b_ahead=tallies["b"],
        tied=tallies["tie"],
    )


def pareto_frontier(
    points: Sequence[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    """The non-dominated points when lower cost and higher quality are better.

    A point is dominated when another is at least as cheap and at least as good and strictly
    better on one of the two. Points with identical cost and quality do not dominate each
    other, so all of them stay.

    Args:
        points: ``(name, cost, quality)`` triples.

    Returns:
        The frontier, sorted by cost then name.
    """
    frontier = [
        point
        for point in points
        if not any(
            other[1] <= point[1]
            and other[2] >= point[2]
            and (other[1] < point[1] or other[2] > point[2])
            for other in points
        )
    ]
    return sorted(frontier, key=lambda point: (point[1], point[0]))


def minimum_detectable_difference(
    obs: Sequence[PairedObs], *, alpha: float = 0.05, power: float = 0.8
) -> MinimumDetectable:
    """The smallest true mean difference this data could have detected.

    Hand-computable: take each cluster's mean of ``a - b``, let ``s`` be their sample
    standard deviation (divisor ``K - 1``) and ``K`` the number of clusters, then
    ``SE = s / sqrt(K)`` and ``MDD = (z_{1 - alpha/2} + z_{power}) * SE``, with the normal
    quantiles from :class:`statistics.NormalDist`.

    Args:
        obs: One entry per item.
        alpha: The two-sided level.
        power: The target power.

    Returns:
        The MDD and its standard error, in the metric's units.

    Raises:
        ValueError: If there are fewer than two clusters or alpha or power is outside (0, 1).
    """
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be in (0, 1)")
    clusters, excluded = _cluster_diffs(obs)
    if len(clusters) < 2:
        raise ValueError("a minimum detectable difference needs at least two clusters")
    means = [sum(diffs) / len(diffs) for diffs in clusters.values()]
    se = statistics.stdev(means) / math.sqrt(len(means))
    normal = statistics.NormalDist()
    mdd = (normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)) * se
    return MinimumDetectable(
        **vars(_summary(clusters, excluded)), mdd=mdd, se=se, alpha=alpha, power=power
    )
