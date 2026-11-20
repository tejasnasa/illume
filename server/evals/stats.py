"""Small statistics used across the eval: confidence intervals and agreement."""

import math
from collections import Counter
from collections.abc import Hashable, Sequence


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
