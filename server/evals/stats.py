"""Small statistics used across the eval: confidence intervals and agreement."""

import math
import random
from collections import Counter
from collections.abc import Hashable, Sequence
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
