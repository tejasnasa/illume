"""The pre-registered comparisons, as data, and the code that runs them.

``PILOT_COMPARISONS`` mirrors the two tables of ``prereg/pilot.md`` and ``FULL_COMPARISONS`` the
hypothesis table of ``prereg/v1.md``; a test parses both markdown tables and checks the ids and
arms here against them. Every comparison is paired on the same items. Differences use
:mod:`evals.stats` (cluster bootstrap interval, cluster permutation test, Holm correction,
minimum detectable difference, per-repository direction); ratio criteria use
:mod:`evals.report.ratio`.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from evals.report.ratio import RatioObs, ratio_bootstrap
from evals.report.wording import METRICS, comparison_sentence
from evals.stats import (
    PairedObs,
    direction_counts,
    holm,
    minimum_detectable_difference,
    paired_bootstrap_ci,
    paired_permutation_test,
    tost,
)

Alternative = Literal["two-sided", "greater", "less"]
Kind = Literal["diff", "tost", "cost_multiple", "ratio_floor", "ratio_ceiling"]

ALPHA = 0.05
TOST_MARGIN = 0.03


@dataclass(frozen=True)
class ComparisonSpec:
    """One pre-registered comparison.

    Attributes:
        id: The id as the pre-registration states it (``P1a``, ``H6-hyde``).
        hypothesis: The hypothesis it belongs to (``H6`` for ``H6-hyde``); the id itself for
            single tests and the pilot.
        family: The Holm family: ``primary``, ``secondary`` or ``main``; ``equivalence`` is
            outside Holm.
        arm_a: The first arm.
        arm_b: The second arm.
        metric: A key of :data:`evals.report.wording.METRICS`.
        alternative: The test's alternative; ``greater`` means ``arm_a`` higher.
        kind: ``diff``, ``tost``, or one of the ratio criteria.
        criterion: The ratio a ratio criterion is held against.
        headline: Whether the comparison is the headline of its family.
        description: One line on the comparison.
        reference: For H6, the arm whose gap to ``arm_b`` is closed.
    """

    id: str
    hypothesis: str
    family: str
    arm_a: str
    arm_b: str
    metric: str
    alternative: Alternative
    kind: Kind = "diff"
    criterion: float | None = None
    headline: bool = False
    description: str = ""
    reference: str | None = None

    @property
    def arms(self) -> tuple[str, ...]:
        """Every arm the comparison needs."""
        return tuple(a for a in (self.arm_a, self.arm_b, self.reference) if a)


PILOT_COMPARISONS: tuple[ComparisonSpec, ...] = (
    ComparisonSpec(
        "P1a", "P1a", "primary", "agent", "structural_rerank", "recall", "greater",
        description="the agent finds more of the changed files",
    ),
    ComparisonSpec(
        "P1b", "P1b", "primary", "agent", "structural_rerank", "cost", "greater",
        description="the agent costs more per question",
    ),
    ComparisonSpec(
        "P2", "P2", "primary", "structural", "classic", "recall", "greater",
        description="structural retrieval beats dense-only retrieval",
    ),
    ComparisonSpec(
        "P3", "P3", "primary", "structural", "structural_-cochange", "recall", "greater",
        headline=True, description="removing the co-change channel lowers recall",
    ),
    ComparisonSpec(
        "P4a", "P4a", "primary", "auto", "agent", "recall", "two-sided",
        description="auto keeps the agent's recall",
    ),
    ComparisonSpec(
        "P4b", "P4b", "primary", "auto", "agent", "cost", "less",
        description="auto costs less per question than the agent",
    ),
    ComparisonSpec(
        "S1", "S1", "secondary", "hybrid_rerank", "hybrid", "recall", "greater",
        description="the Cohere reranker helps hybrid retrieval",
    ),
    ComparisonSpec(
        "S2", "S2", "secondary", "structural_rerank", "structural", "recall", "greater",
        description="the Cohere reranker helps structural retrieval",
    ),
    ComparisonSpec(
        "S3", "S3", "secondary", "hybrid_hyde", "hybrid", "recall", "greater",
        description="a hypothetical snippet helps hybrid retrieval",
    ),
    ComparisonSpec(
        "S4", "S4", "secondary", "hybrid_multiquery", "hybrid", "recall", "greater",
        description="query rewrites help hybrid retrieval",
    ),
)  # fmt: skip

FULL_COMPARISONS: tuple[ComparisonSpec, ...] = (
    ComparisonSpec(
        "H1a", "H1a", "main", "agent", "structural_rerank", "recall", "greater",
        description="the agent beats reranked structural retrieval",
    ),
    ComparisonSpec(
        "H1b", "H1b", "main", "agent", "structural_rerank", "cost", "greater",
        kind="cost_multiple", criterion=5.0,
        description="the agent costs more than five times as much per question",
    ),
    ComparisonSpec(
        "H2", "H2", "main", "structural", "hybrid", "recall10", "greater",
        description="structural retrieval beats hybrid retrieval",
    ),
    ComparisonSpec(
        "H3", "H3", "main", "structural", "structural_-cochange", "recall10", "greater",
        headline=True, description="removing co-change lowers recall",
    ),
    ComparisonSpec(
        "H4", "H4", "main", "agent", "agent_text_tools", "steps", "less",
        description="graph tools reach the first changed file in fewer steps",
    ),
    ComparisonSpec(
        "H5", "H5", "equivalence", "agent_workers", "agent", "recall", "two-sided",
        kind="tost", criterion=TOST_MARGIN,
        description="workers are equivalent to the single agent within three points",
    ),
    ComparisonSpec(
        "H6-multiquery", "H6", "main", "hybrid_multiquery", "hybrid", "recall", "greater",
        reference="agent",
        description="multi-query closes part of the gap to the agent at a small fraction of cost",
    ),
    ComparisonSpec(
        "H6-hyde", "H6", "main", "hybrid_hyde", "hybrid", "recall", "greater",
        reference="agent",
        description="HyDE closes part of the gap to the agent at a small fraction of cost",
    ),
    ComparisonSpec(
        "H7-recall", "H7", "main", "auto", "agent", "recall", "greater",
        kind="ratio_floor", criterion=0.9,
        description="auto keeps at least 90% of the agent's recall",
    ),
    ComparisonSpec(
        "H7-cost", "H7", "main", "auto", "agent", "cost", "less",
        kind="ratio_ceiling", criterion=0.5,
        description="auto costs less than half as much per question",
    ),
)  # fmt: skip

H6_COST_FRACTION = 0.25
"""H6's cost criterion: the arm costs under this share of the agent's cost."""

PILOT_FAMILIES = ("primary", "secondary")


def specs_for(mode: str) -> tuple[ComparisonSpec, ...]:
    """The comparisons of a report mode (``pilot`` or ``full``)."""
    return PILOT_COMPARISONS if mode == "pilot" else FULL_COMPARISONS


MetricGetter = Callable[[str, str, str], float | None]
"""``(arm, item_id, metric) -> value``; ``None`` when the arm has no usable result for the item."""


@dataclass(frozen=True)
class ItemRef:
    """The identity an item is paired and resampled by."""

    id: str
    repo: str
    cluster: str


@dataclass(frozen=True)
class StatConfig:
    """Resampling sizes and the seed base.

    Attributes:
        n_boot: Bootstrap resamples for comparisons.
        n_perm: Permutation patterns for comparisons.
        n_boot_mean: Bootstrap resamples for descriptive means.
        seed: Added to each comparison's own seed.
    """

    n_boot: int = 10_000
    n_perm: int = 10_000
    n_boot_mean: int = 2_000
    seed: int = 0


def seed_for(name: str, base: int = 0) -> int:
    """A stable seed for a named computation."""
    return zlib.crc32(name.encode("utf-8")) + base


def paired(
    items: Sequence[ItemRef], get: MetricGetter, arm_a: str, arm_b: str, metric: str
) -> list[PairedObs]:
    """One :class:`PairedObs` per item for two arms on a metric."""
    return [
        PairedObs(i.repo, i.cluster, get(arm_a, i.id, metric), get(arm_b, i.id, metric))
        for i in items
    ]


@dataclass
class Outcome:
    """A computed comparison before Holm correction.

    Attributes:
        record: The JSON-ready record.
        p_raw: The raw p-value used in its family, if it has one.
    """

    record: dict[str, Any]
    p_raw: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def compute_one(
    spec: ComparisonSpec,
    items: Sequence[ItemRef],
    get: MetricGetter,
    config: StatConfig,
) -> Outcome | None:
    """Run one comparison on the items; ``None`` when it cannot be computed.

    A comparison is skipped (``None``) when either arm has no usable result on any item.

    Args:
        spec: The comparison.
        items: Every item the comparison may use.
        get: Reads a metric of an arm on an item.
        config: Resampling sizes and seed.

    Returns:
        The outcome, with the raw p-value that enters its Holm family.
    """
    seed = seed_for(spec.id, config.seed)
    metric = spec.metric
    obs = paired(items, get, spec.arm_a, spec.arm_b, metric)
    if not any(o.a is not None and o.b is not None for o in obs):
        return None
    record: dict[str, Any] = {
        "id": spec.id,
        "hypothesis": spec.hypothesis,
        "family": spec.family,
        "arm_a": spec.arm_a,
        "arm_b": spec.arm_b,
        "metric": metric,
        "metric_title": METRICS[metric].title,
        "alternative": spec.alternative,
        "kind": spec.kind,
        "headline": spec.headline,
        "description": spec.description,
    }
    p_raw: float | None = None

    if spec.kind in ("cost_multiple", "ratio_floor", "ratio_ceiling"):
        assert spec.criterion is not None
        p_raw = _ratio_comparison(spec, items, get, config, seed, record)
        if p_raw is None:
            return None
    else:
        ci = paired_bootstrap_ci(obs, n_boot=config.n_boot, seed=seed)
        complete = [o for o in obs if o.a is not None and o.b is not None]
        record.update(
            mean_a=sum(o.a for o in complete if o.a is not None) / len(complete),
            mean_b=sum(o.b for o in complete if o.b is not None) / len(complete),
            estimate=ci.estimate,
            ci_lo=ci.lo,
            ci_hi=ci.hi,
            n=ci.n,
            n_clusters=ci.n_clusters,
            n_excluded=ci.n_excluded,
            n_boot=ci.n_boot,
        )
        if spec.kind == "tost":
            result = tost(
                obs, margin=spec.criterion or TOST_MARGIN, n_boot=config.n_boot, seed=seed
            )
            record["tost"] = {
                "margin": result.margin,
                "p_lower": result.p_lower,
                "p_upper": result.p_upper,
                "p_value": result.p_value,
                "equivalent": result.equivalent,
                "alpha": result.alpha,
            }
            p_raw = None
        else:
            perm = paired_permutation_test(
                obs, n_perm=config.n_perm, seed=seed, alternative=spec.alternative
            )
            p_raw = perm.p_value
            record.update(n_perm=perm.n_perm, exact=perm.exact)
        try:
            mdd = minimum_detectable_difference(obs)
            record.update(mdd=mdd.mdd, se=mdd.se)
        except ValueError:
            record.update(mdd=None, se=None)
        counts = direction_counts(obs)
        record["direction"] = {
            "per_repo": dict(counts.per_repo),
            "a_ahead": counts.a_ahead,
            "b_ahead": counts.b_ahead,
            "tied": counts.tied,
        }
        if spec.reference:
            record["gap"] = _gap_share(spec, items, get, config, seed)
    record["p_raw"] = p_raw
    return Outcome(record, p_raw)


def _ratio_comparison(
    spec: ComparisonSpec,
    items: Sequence[ItemRef],
    get: MetricGetter,
    config: StatConfig,
    seed: int,
    record: dict[str, Any],
) -> float | None:
    """Fill a ratio criterion's record; return the raw p-value of its one-sided test."""
    assert spec.criterion is not None
    k = spec.criterion

    def value(arm: str, i: ItemRef) -> float | None:
        return get(arm, i.id, spec.metric)

    rows = [RatioObs(i.repo, i.cluster, value(spec.arm_a, i), value(spec.arm_b, i)) for i in items]
    if spec.kind == "ratio_ceiling":
        # The cost ratio is below k when mean(k * b - a) is above zero.
        test = [
            PairedObs(i.repo, i.cluster, _scaled(value(spec.arm_b, i), k), value(spec.arm_a, i))
            for i in items
        ]
    else:
        # The ratio of means is above k when mean(a - k * b) is above zero.
        test = [
            PairedObs(i.repo, i.cluster, value(spec.arm_a, i), _scaled(value(spec.arm_b, i), k))
            for i in items
        ]
    try:
        ratio = ratio_bootstrap(rows, n_boot=config.n_boot, seed=seed)
        permutation = paired_permutation_test(
            test, n_perm=config.n_perm, seed=seed, alternative="greater"
        )
    except ValueError:
        return None
    record.update(
        estimate=ratio.estimate,
        ci_lo=ratio.lo,
        ci_hi=ratio.hi,
        n=ratio.n,
        n_clusters=ratio.n_clusters,
        n_excluded=ratio.n_excluded,
        n_boot=ratio.n_boot,
        criterion=k,
        mdd=None,
        n_perm=permutation.n_perm,
        exact=permutation.exact,
    )
    return permutation.p_value


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _gap_share(
    spec: ComparisonSpec,
    items: Sequence[ItemRef],
    get: MetricGetter,
    config: StatConfig,
    seed: int,
) -> dict[str, Any] | None:
    """H6's extras: the share of the baseline-to-reference gap closed, and the cost fraction."""
    assert spec.reference
    gap_rows: list[RatioObs] = []
    cost_rows: list[RatioObs] = []
    for i in items:
        arm, base, ref = (get(a, i.id, "recall") for a in (spec.arm_a, spec.arm_b, spec.reference))
        if arm is None or base is None or ref is None:
            gap_rows.append(RatioObs(i.repo, i.cluster, None, None))
        else:
            gap_rows.append(RatioObs(i.repo, i.cluster, arm - base, ref - base))
        cost_rows.append(
            RatioObs(
                i.repo,
                i.cluster,
                get(spec.arm_a, i.id, "cost"),
                get(spec.reference, i.id, "cost"),
            )
        )
    out: dict[str, Any] = {"reference": spec.reference, "baseline": spec.arm_b}
    try:
        share = ratio_bootstrap(gap_rows, n_boot=config.n_boot, seed=seed)
        out["share_closed"] = {"estimate": share.estimate, "lo": share.lo, "hi": share.hi}
        out["share_n"] = share.n
    except ValueError:
        out["share_closed"] = None
    try:
        cost = ratio_bootstrap(cost_rows, n_boot=config.n_boot, seed=seed + 1)
        out["cost_fraction"] = {
            "estimate": cost.estimate,
            "lo": cost.lo,
            "hi": cost.hi,
            "criterion": H6_COST_FRACTION,
            "met": cost.estimate < H6_COST_FRACTION,
        }
        out["cost_n"] = cost.n
    except ValueError:
        out["cost_fraction"] = None
    return out


def run_comparisons(
    mode: str,
    items: Sequence[ItemRef],
    get: MetricGetter,
    arms_present: Sequence[str],
    config: StatConfig,
    *,
    repositories: int,
) -> list[dict[str, Any]]:
    """Compute every comparison of a mode whose arms were run, with Holm correction.

    Comparisons whose arms are missing are left out. Holm is applied within each family over
    the comparisons that could be computed; the planned and computed family sizes are recorded
    so a reader can see when a family shrank.

    Args:
        mode: ``pilot`` or ``full``.
        items: The change-set items.
        get: Reads a metric of an arm on an item.
        arms_present: The arms with records.
        config: Resampling sizes and seed.
        repositories: How many repositories the run covers, for the sentences.

    Returns:
        One record per computed comparison, in the pre-registration's order.
    """
    present = set(arms_present)
    specs = specs_for(mode)
    planned: dict[str, int] = {}
    for spec in specs:
        planned[spec.family] = planned.get(spec.family, 0) + 1
    outcomes: list[tuple[ComparisonSpec, Outcome]] = []
    for spec in specs:
        if not all(arm in present for arm in spec.arms):
            continue
        outcome = compute_one(spec, items, get, config)
        if outcome is not None:
            outcomes.append((spec, outcome))

    adjusted: dict[str, Any] = {}
    sizes: dict[str, int] = {}
    for family in {spec.family for spec, _ in outcomes}:
        members = {
            spec.id: outcome.p_raw
            for spec, outcome in outcomes
            if spec.family == family and outcome.p_raw is not None
        }
        sizes[family] = len(members)
        if family != "equivalence" and members:
            adjusted.update(holm(members, ALPHA))

    records: list[dict[str, Any]] = []
    for spec, outcome in outcomes:
        record = outcome.record
        outcome_holm = adjusted.get(spec.id)
        record["p_adjusted"] = outcome_holm.adjusted if outcome_holm else None
        record["reject"] = outcome_holm.reject if outcome_holm else None
        record["family_size_planned"] = planned[spec.family]
        record["family_size_run"] = sizes.get(spec.family, 0)
        records.append(record)
    _verdicts(records)
    for record in records:
        record["resolved"] = _resolved(record)
        record["sentence"] = comparison_sentence(record, repositories)
    return records


def _resolved(record: Mapping[str, Any]) -> bool:
    low, high = record["ci_lo"], record["ci_hi"]
    criterion = record.get("criterion")
    if record["kind"] in ("cost_multiple", "ratio_floor", "ratio_ceiling"):
        assert criterion is not None
        return not (low <= criterion <= high)
    return low > 0 or high < 0


def _verdicts(records: list[dict[str, Any]]) -> None:
    """Set each record's verdict from its pre-registered criterion."""
    by_id = {r["id"]: r for r in records}
    h7 = _h7(by_id.get("H7-recall"), by_id.get("H7-cost"))
    for record in records:
        if record["kind"] == "tost":
            record["verdict"] = "equivalent" if record["tost"]["equivalent"] else "not_equivalent"
        elif record["hypothesis"] == "H7":
            record["verdict"] = h7
        elif record.get("gap") is not None:
            cost = record["gap"].get("cost_fraction")
            met = bool(cost and cost["met"])
            record["verdict"] = "supported" if record["reject"] and met else "not_supported"
        elif record["alternative"] == "two-sided":
            record["verdict"] = "difference" if record["reject"] else "no_difference"
        else:
            record["verdict"] = "supported" if record["reject"] else "not_supported"


def _h7(recall: dict[str, Any] | None, cost: dict[str, Any] | None) -> str:
    """H7 holds when both interval criteria hold: recall ratio floor and cost ratio ceiling."""
    if recall is None or cost is None:
        return "not_supported"
    floor_met = recall["ci_lo"] >= recall["criterion"]
    ceiling_met = cost["ci_hi"] < cost["criterion"]
    return "supported" if floor_met and ceiling_met else "not_supported"


__all__ = [
    "ALPHA",
    "FULL_COMPARISONS",
    "H6_COST_FRACTION",
    "PILOT_COMPARISONS",
    "TOST_MARGIN",
    "ComparisonSpec",
    "ItemRef",
    "MetricGetter",
    "Outcome",
    "StatConfig",
    "compute_one",
    "paired",
    "run_comparisons",
    "seed_for",
    "specs_for",
]
