"""Paired statistics: resampling, permutation, equivalence, MDD, Pareto and the drafts."""

import math
import random
import re
from pathlib import Path

import pytest

import evals.stats_selftest  # noqa: F401
from evals import selftest_registry
from evals.gold.split import PREREG_FILES
from evals.report.comparisons import SIMPLE_COMPARISONS
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

pytestmark = pytest.mark.unit

PREREG_DIR = Path(__file__).resolve().parents[2] / "evals" / "prereg"


def _noisy(n_per_repo: int, shift: float, seed: int = 1) -> list[PairedObs]:
    rng = random.Random(seed)
    rows = []
    for repo in ("r1", "r2"):
        for i in range(n_per_repo):
            base = rng.random()
            rows.append(PairedObs(repo, str(i), base + shift + rng.gauss(0, 0.01), base))
    return rows


def test_resampling_keeps_cluster_items_together():
    # Cluster "x" has a constant difference of 1 across 3 items; all other clusters 0. If items
    # moved independently, means such as 1/6 would be reachable; with clusters together every
    # resample's mean equals 3j / total, j whole copies of "x".
    seen = set()
    rows = [PairedObs("r", "x", 1.0, 0.0) for _ in range(3)]
    rows += [PairedObs("r", "y", 0.0, 0.0) for _ in range(3)]
    for seed in range(20):
        result = paired_bootstrap_ci(rows, n_boot=50, seed=seed, alpha=0.0)
        seen.update({round(result.lo, 6), round(result.hi, 6)})
    assert seen <= {0.0, 0.5, 1.0}


def test_incomplete_items_are_excluded_and_counted():
    rows = [PairedObs("r", "a", 1.0, 0.0), PairedObs("r", "b", None, 0.5)]
    result = paired_bootstrap_ci(rows, n_boot=20, seed=0)
    assert (result.n, result.n_excluded) == (1, 1)


def test_no_complete_pairs_is_an_error():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([PairedObs("r", "a", None, 1.0)], n_boot=10, seed=0)


def test_identical_arms_give_p_of_one():
    rows = [PairedObs("r", str(i), 0.4, 0.4) for i in range(30)]
    for alternative in ("two-sided", "greater", "less"):
        result = paired_permutation_test(rows, n_perm=500, seed=1, alternative=alternative)
        assert result.p_value == 1.0 and not result.exact


def test_a_clear_difference_has_a_small_p():
    result = paired_permutation_test(_noisy(20, 0.2), n_perm=2000, seed=2, alternative="greater")
    assert result.p_value < 0.01
    assert result.p_value >= 1 / 2001
    assert result.n == 40 and result.n_clusters == 40


def test_the_permutation_test_is_seeded():
    rows = _noisy(20, 0.05)
    first = paired_permutation_test(rows, n_perm=1000, seed=9)
    again = paired_permutation_test(rows, n_perm=1000, seed=9)
    assert first == again


def test_unknown_alternative_is_rejected():
    with pytest.raises(ValueError):
        paired_permutation_test([PairedObs("r", "a", 1.0, 0.0)], seed=0, alternative="up")  # type: ignore[arg-type]


def test_tost_accepts_clear_equivalence_and_rejects_a_clear_difference():
    equal = tost(_noisy(30, 0.0), margin=0.03, n_boot=1000, seed=1)
    assert equal.equivalent and equal.p_value < 0.05
    different = tost(_noisy(30, 0.2), margin=0.03, n_boot=1000, seed=1)
    assert not different.equivalent and different.p_upper > 0.5


def test_tost_needs_a_positive_margin():
    with pytest.raises(ValueError):
        tost(_noisy(5, 0.0), margin=0.0, seed=0)


def test_mdd_matches_a_hand_computation():
    # Cluster means 1, 2, 3: sd = 1, SE = 1 / sqrt(3), MDD = 2.801585 * SE.
    rows = [PairedObs("r", str(i), float(i + 1), 0.0) for i in range(3)]
    result = minimum_detectable_difference(rows)
    assert result.se == pytest.approx(1 / math.sqrt(3))
    assert result.mdd == pytest.approx(2.801585 / math.sqrt(3), rel=1e-5)
    assert (result.n, result.n_clusters) == (3, 3)


def test_mdd_averages_items_inside_a_cluster_first():
    rows = [PairedObs("r", "a", 1.0, 0.0), PairedObs("r", "a", 3.0, 0.0)]
    rows += [PairedObs("r", "b", 4.0, 0.0)]
    # Cluster means 2 and 4: sd = sqrt(2), SE = 1.
    assert minimum_detectable_difference(rows).se == pytest.approx(1.0)


def test_mdd_needs_two_clusters():
    with pytest.raises(ValueError):
        minimum_detectable_difference([PairedObs("r", "a", 1.0, 0.0)])


def test_holm_is_monotone_and_capped():
    out = holm({"a": 0.2, "b": 0.001, "c": 0.9})
    assert out["b"].adjusted == pytest.approx(0.003)
    assert out["a"].adjusted == pytest.approx(0.4)
    assert out["c"].adjusted == 0.9
    with pytest.raises(ValueError):
        holm({"a": 1.5})


def test_pareto_keeps_ties_and_drops_dominated_points():
    points = [("a", 1.0, 0.5), ("b", 1.0, 0.5), ("c", 2.0, 0.4), ("d", 1.0, 0.6)]
    assert [p[0] for p in pareto_frontier(points)] == ["d"]
    tied = [("a", 1.0, 0.5), ("b", 1.0, 0.5), ("c", 2.0, 0.9)]
    assert [p[0] for p in pareto_frontier(tied)] == ["a", "b", "c"]
    assert pareto_frontier([]) == []


def test_direction_counts_describe_each_repository():
    rows = [PairedObs("r1", "a", 1.0, 0.0), PairedObs("r2", "a", 0.0, 1.0)]
    rows += [PairedObs("r3", "a", 0.5, 0.5)]
    counts = direction_counts(rows)
    assert counts.per_repo == {"r1": "a", "r2": "b", "r3": "tie"}
    assert (counts.a_ahead, counts.b_ahead, counts.tied) == (1, 1, 1)


def test_the_new_statistics_cases_are_registered_and_pass():
    passed, failed = selftest_registry.run_all()
    assert failed == []
    assert sum(name.startswith("stats:") for name in passed) >= 6


@pytest.mark.parametrize("slice_name", sorted(PREREG_FILES))
def test_each_prereg_draft_exists_under_the_name_the_guard_expects(slice_name):
    path = PREREG_DIR / PREREG_FILES[slice_name]
    text = path.read_text(encoding="utf-8")
    assert re.search(
        r"Status: DRAFT(?:\.| —) ?[Cc]ommit this file unchanged before the first paid run", text
    )
    assert "the commit is the timestamp." in text
    assert "TBD" not in text and "TODO" not in text


def test_the_pilot_draft_names_every_comparison_in_order():
    text = (PREREG_DIR / "pilot.md").read_text(encoding="utf-8")
    stated = re.findall(r"`([^`]+)` vs `([^`]+)`", text)
    assert stated == list(SIMPLE_COMPARISONS)
    for metric in ("File recall", "Correctness", "Faithfulness", "Answer relevancy"):
        assert metric in text, metric
    assert "not resolved at this sample size" in text


def test_the_full_draft_names_every_hypothesis():
    text = (PREREG_DIR / "v1.md").read_text(encoding="utf-8")
    for hypothesis in ("H1a", "H1b", "H2", "H3", "H4", "H5", "H6", "H7"):
        assert f"| {hypothesis} |" in text, hypothesis
    assert "0.03" in text and "TOST" in text and "tuning" in text
