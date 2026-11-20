"""Hand-computed checks of the paired statistics.

Importing this module registers the cases with :mod:`evals.selftest_registry`. Each expected
value is worked out by hand in the case. The coverage case draws seeded synthetic data with a
known mean difference and checks that the bootstrap interval contains it about 95% of the
time. Nothing here touches a database or the network.
"""

import math
import random

from evals.selftest_registry import register
from evals.stats import (
    PairedObs,
    direction_counts,
    holm,
    minimum_detectable_difference,
    paired_bootstrap_ci,
    paired_permutation_test,
    pareto_frontier,
    tost,
)


def _obs(rows: list[tuple[str, str, float, float]]) -> list[PairedObs]:
    return [PairedObs(repo, cluster, a, b) for repo, cluster, a, b in rows]


@register("stats: permutation test exact p on a hand-enumerable case")
def _permutation_exact() -> None:
    # Three clusters with differences +1, +2, +3. Of the 8 sign patterns only the all-positive
    # one reaches a mean of 2, so P(mean >= 2) = 1/8; two-sided, the all-negative pattern
    # joins it, so p = 2/8.
    obs = _obs([("r", "c1", 1.0, 0.0), ("r", "c2", 2.0, 0.0), ("r", "c3", 3.0, 0.0)])
    greater = paired_permutation_test(obs, seed=0, alternative="greater")
    assert greater.exact and greater.p_value == 0.125, greater
    two_sided = paired_permutation_test(obs, seed=0)
    assert two_sided.p_value == 0.25, two_sided
    less = paired_permutation_test(obs, seed=0, alternative="less")
    assert less.p_value == 1.0, less


@register("stats: Holm adjustment on a hand-computed set")
def _holm_hand() -> None:
    # Sorted: 0.01, 0.02, 0.04 with m = 3. Adjusted: 3*0.01 = 0.03, max(0.03, 2*0.02) = 0.04,
    # max(0.04, 1*0.04) = 0.04. At alpha 0.035 only the first is rejected.
    out = holm({"x": 0.04, "y": 0.01, "z": 0.02}, alpha=0.035)
    assert math.isclose(out["y"].adjusted, 0.03)
    assert math.isclose(out["z"].adjusted, 0.04)
    assert math.isclose(out["x"].adjusted, 0.04)
    assert (out["y"].reject, out["z"].reject, out["x"].reject) == (True, False, False)


@register("stats: Pareto frontier on a hand case")
def _pareto_hand() -> None:
    points = [
        ("cheap", 1.0, 0.5),
        ("mid", 2.0, 0.7),
        ("dominated", 3.0, 0.6),
        ("best", 4.0, 0.9),
        ("twin", 2.0, 0.7),
    ]
    names = [name for name, _, _ in pareto_frontier(points)]
    assert names == ["cheap", "mid", "twin", "best"], names


@register("stats: minimum detectable difference on a hand case")
def _mdd_hand() -> None:
    # Cluster means 0.1, 0.3, 0.2, 0.4: mean 0.25, squared deviations sum to 0.05, so
    # sd = sqrt(0.05 / 3) and SE = sd / 2. MDD = (1.959964 + 0.841621) * SE.
    obs = _obs([("r", f"c{i}", m, 0.0) for i, m in enumerate((0.1, 0.3, 0.2, 0.4))])
    result = minimum_detectable_difference(obs)
    se = math.sqrt(0.05 / 3) / 2
    assert math.isclose(result.se, se, rel_tol=1e-9)
    assert math.isclose(result.mdd, 2.801585 * se, rel_tol=1e-5), result


@register("stats: bootstrap interval covers the true difference about 95% of the time")
def _bootstrap_coverage() -> None:
    generator = random.Random(2024)
    true_diff = 0.1
    covered = 0
    datasets = 200
    for index in range(datasets):
        rows: list[tuple[str, str, float, float]] = []
        for repo in ("r1", "r2", "r3", "r4"):
            for cluster in range(10):
                shared = generator.gauss(0, 0.1)
                for _ in range(2):
                    diff = true_diff + shared + generator.gauss(0, 0.1)
                    rows.append((repo, f"{cluster}", 0.5 + diff, 0.5))
        result = paired_bootstrap_ci(_obs(rows), n_boot=500, seed=index)
        covered += result.lo <= true_diff <= result.hi
    rate = covered / datasets
    assert 0.90 <= rate <= 0.99, f"coverage {rate:.3f} outside 0.90-0.99"


@register("stats: direction counts and TOST agree with an obvious case")
def _direction_and_tost() -> None:
    rows = [("r1", f"c{i}", 0.5, 0.5) for i in range(10)]
    rows += [("r2", f"c{i}", 0.6, 0.5) for i in range(10)]
    counts = direction_counts(_obs(rows))
    assert (counts.a_ahead, counts.b_ahead, counts.tied) == (1, 0, 1)
    flat = _obs([("r", f"c{i}", 0.5, 0.5) for i in range(20)])
    assert tost(flat, margin=0.03, n_boot=500, seed=1).equivalent
