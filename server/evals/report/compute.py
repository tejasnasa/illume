"""The report's tables as plain data: each function returns a JSON-ready mapping, or ``None`` when
the run has nothing for that section.

Every estimate carries its ``n`` and, where it is an estimate, a 95% interval: means by a cluster
bootstrap (repositories fixed, clusters resampled within them), rates by Wilson. Nothing here
formats text; :mod:`evals.report.render` does that from the result.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from statistics import median
from typing import Any

from evals.arms import ARMS, AUTO
from evals.gold.schema import GoldItem
from evals.gold.verify import gold_error_report
from evals.metrics.answer import scored_gold
from evals.metrics.cost import cost_summary, percentile
from evals.metrics.retrieval import KS
from evals.metrics.routing import ROUTABLE_ARMS, ArmOutcome, routing_summary
from evals.metrics.trajectory import (
    stop_reasons,
    tool_call_counts,
    wasted_reads,
    worker_overlap,
)
from evals.report.comparisons import (
    ComparisonSpec,
    ItemRef,
    StatConfig,
    compute_one,
    seed_for,
)
from evals.report.load import RunData
from evals.report.scores import CHANGESET, Score, Scores
from evals.run.judge_validation import judge_vs_human
from evals.stats import PairedObs, paired_bootstrap_ci, pareto_frontier, wilson_interval

CORRECT_RECALL = 1.0 - 1e-9
DRIFT_WIDTH = 25
JUDGED_FAMILIES = ("changeset", "rationale", "hand")
SANITY_FAMILY = "structural"
SINGLE_SHOT_PAIRS_RERANK = (
    ("hybrid_rerank", "hybrid"),
    ("hybrid_jev", "hybrid"),
    ("hybrid_jev", "hybrid_rerank"),
    ("structural_rerank", "structural"),
)
ABLATION_BASE = "structural"
STEP_CURVE_MAX = 30


def wilson(successes: int, n: int) -> dict[str, Any]:
    """A rate with its Wilson 95% interval and the ``n`` it rests on."""
    lo, hi = wilson_interval(successes, n)
    return {"k": successes, "n": n, "rate": successes / n if n else None, "lo": lo, "hi": hi}


def mean_ci(
    values: Iterable[tuple[ItemRef, float]], config: StatConfig, name: str
) -> dict[str, Any] | None:
    """The mean of per-item values with a cluster bootstrap interval, or ``None`` when empty."""
    obs = [PairedObs(ref.repo, ref.cluster, value, 0.0) for ref, value in values]
    if not obs:
        return None
    ci = paired_bootstrap_ci(obs, n_boot=config.n_boot_mean, seed=seed_for(name, config.seed))
    return {
        "mean": ci.estimate,
        "lo": ci.lo,
        "hi": ci.hi,
        "n": ci.n,
        "n_clusters": ci.n_clusters,
    }


def _present(values: Iterable[tuple[ItemRef, float | None]]) -> list[tuple[ItemRef, float]]:
    return [(ref, value) for ref, value in values if value is not None]


def _ref_map(scores: Scores) -> dict[str, ItemRef]:
    return {ref.id: ref for ref in scores.refs}


def _arm_values(
    scores: Scores, arm: str, metric: str, items: Iterable[str] | None = None
) -> list[tuple[ItemRef, float]]:
    refs = _ref_map(scores)
    wanted = set(items) if items is not None else None
    return _present(
        (refs[row.item_id], scores.get(arm, row.item_id, metric))
        for row in scores.rows.get(arm, {}).values()
        if wanted is None or row.item_id in wanted
    )


# --- corpus and scope ------------------------------------------------------------------


def corpus_section(data: RunData) -> dict[str, Any] | None:
    """Per-repository counts captured at run time, with the questions per family."""
    if not data.corpus:
        return None
    families: dict[str, Counter[str]] = {}
    for item in data.items.values():
        families.setdefault(item.repo, Counter())[item.family] += 1
    repos = {}
    for name in sorted(data.corpus):
        counts = dict(data.corpus[name])
        counts["questions"] = dict(sorted(families.get(name, Counter()).items()))
        repos[name] = counts
    return {"repos": repos}


def scope_section(data: RunData, scores: Scores, arms: Sequence[str], mode: str) -> dict[str, Any]:
    """What the run covers: repositories, questions, models, arms."""
    items = list(data.items.values())
    families = Counter(i.family for i in items)
    repos = sorted({i.repo for i in items})
    models = (data.manifest.get("models") or {}).get("generator", "")
    generators = [m for m in str(models).split(",") if m]
    languages = sorted({str(c["language"]) for c in data.corpus.values() if c.get("language")})
    return {
        "mode": mode,
        "slice": data.slice_name,
        "repositories": repos,
        "n_repositories": len(repos),
        "languages": languages,
        "n_languages": len(languages),
        "n_questions": len(items),
        "families": dict(sorted(families.items())),
        "n_changeset": len(scores.items),
        "n_changeset_clusters": len({(r.repo, r.cluster) for r in scores.refs}),
        "n_post_cutoff": sum(1 for i in scores.items if i.post_cutoff is True),
        "n_pre_cutoff": sum(1 for i in scores.items if i.post_cutoff is False),
        "repeat_records": data.repeat_records,
        "generator_models": generators,
        "n_generator_models": len(generators),
        "arms": list(arms),
        "n_arms": len(arms),
    }


# --- gold quality ----------------------------------------------------------------------


def gold_quality_section(data: RunData) -> dict[str, Any] | None:
    """The hand-check error rate per family and overall, with Wilson intervals."""
    if not data.gold_labels or not data.items:
        return None
    items = list(data.items.values())
    report = gold_error_report(items, data.gold_labels)
    families = {}
    for name, stats in report.families.items():
        families[name] = {
            "n_items": sum(1 for i in items if i.family == name),
            "n_labelled": stats.n_labelled,
            "n_ambiguous": stats.n_ambiguous,
            "n_wrong": stats.n_wrong,
            "n_scored": stats.n_scored,
            "rate": stats.rate,
            "lo": stats.lower,
            "hi": stats.upper,
            "dropped": stats.dropped,
        }
    wrong = sum(f["n_wrong"] for f in families.values())
    scored = sum(f["n_scored"] for f in families.values())
    labelled = sum(f["n_labelled"] for f in families.values())
    overall = wilson(wrong, scored)
    overall.update(n_labelled=labelled, n_items=len(items), all_checked=labelled == len(items))
    ambiguous = sorted(label.item_id for label in data.gold_labels if label.label == "ambiguous")
    return {"families": families, "overall": overall, "ambiguous_items": ambiguous}


# --- main results -----------------------------------------------------------------------


def _arm_counts(scores: Scores, arm: str) -> dict[str, Any]:
    rows = list(scores.rows.get(arm, {}).values())
    ok = [r for r in rows if r.ok]
    total = len(scores.items)
    errors = len(rows) - len(ok)
    return {
        "n_total": total,
        "n_records": len(rows),
        "n_ok": len(ok),
        "n_errors": errors,
        "n_not_reached": total - len(rows),
        "error_rate": wilson(errors, len(rows)),
        "flagged": sum(1 for r in rows if r.generation.flagged),
    }


def main_results_section(scores: Scores, arms: Sequence[str], config: StatConfig) -> dict[str, Any]:
    """Answer recall and precision per arm, with and without test files, and format failures."""
    by_arm: dict[str, Any] = {}
    for arm in arms:
        ok = scores.ok_rows(arm)
        precision = [
            (r, v)
            for r, v in ((x, x.answer.precision if x.answer else None) for x in ok)
            if v is not None
        ]
        refs = _ref_map(scores)
        precision_nt = [
            (x, x.answer_nt.precision)
            for x in ok
            if x.answer_nt and x.answer_nt.precision is not None
        ]
        failures = sum(1 for x in ok if x.answer and x.answer.format_failure)
        by_arm[arm] = {
            **_arm_counts(scores, arm),
            "recall": mean_ci(_arm_values(scores, arm, "recall"), config, f"main:{arm}:recall"),
            "recall_nt": mean_ci(
                _arm_values(scores, arm, "recall_nt"), config, f"main:{arm}:recall_nt"
            ),
            "precision": mean_ci(
                [(refs[r.item_id], v) for r, v in precision], config, f"main:{arm}:precision"
            ),
            "precision_nt": mean_ci(
                [(refs[r.item_id], v) for r, v in precision_nt], config, f"main:{arm}:precision_nt"
            ),
            "format_failures": wilson(failures, len(ok)),
        }
    templates = sorted({i.template for i in scores.items})
    by_template: dict[str, Any] = {}
    if len(templates) > 1:
        for template in templates:
            wanted = {i.id for i in scores.items if i.template == template}
            by_template[template] = {
                arm: mean_ci(
                    _arm_values(scores, arm, "recall", wanted),
                    config,
                    f"main:{arm}:{template}",
                )
                for arm in arms
            }
    return {"by_arm": by_arm, "by_template": by_template}


# --- retrieval --------------------------------------------------------------------------


def single_shot_arms(arms: Sequence[str]) -> list[str]:
    """Arms whose retrieval is a single pass: generated and not an agent."""
    return [a for a in arms if a in ARMS and not ARMS[a].composed and not ARMS[a].is_agent]


def retrieval_section(
    scores: Scores, arms: Sequence[str], config: StatConfig
) -> dict[str, Any] | None:
    """Recall at 5, 10 and 20, MRR and nDCG on each single-shot arm's retrieval pool."""
    chosen = single_shot_arms(arms)
    refs = _ref_map(scores)
    table: dict[str, Any] = {}
    for arm in chosen:
        ok = scores.ok_rows(arm)
        if not ok:
            continue
        entry: dict[str, Any] = {"recall": {}, "ndcg": {}}
        for k in KS:
            entry["recall"][str(k)] = mean_ci(
                _present((refs[r.item_id], r.recall_at.get(k)) for r in ok),
                config,
                f"retrieval:{arm}:recall{k}",
            )
            entry["ndcg"][str(k)] = mean_ci(
                _present((refs[r.item_id], r.ndcg_at.get(k)) for r in ok),
                config,
                f"retrieval:{arm}:ndcg{k}",
            )
        entry["mrr"] = mean_ci(
            _present((refs[r.item_id], r.mrr) for r in ok), config, f"retrieval:{arm}:mrr"
        )
        table[arm] = entry
    if not table:
        return None
    return {"ks": list(KS), "by_arm": table}


# --- paired exploratory comparisons ------------------------------------------------------


def exploratory(
    scores: Scores, arm_a: str, arm_b: str, metric: str, config: StatConfig, label: str
) -> dict[str, Any] | None:
    """A paired comparison outside the pre-registered families: estimate, interval, p, n.

    The p-value is two-sided and not adjusted for multiplicity.
    """
    spec = ComparisonSpec(
        id=f"{label}:{arm_a}:{arm_b}:{metric}",
        hypothesis="exploratory",
        family="exploratory",
        arm_a=arm_a,
        arm_b=arm_b,
        metric=metric,
        alternative="two-sided",
    )
    outcome = compute_one(spec, scores.refs, scores.get, config)
    if outcome is None:
        return None
    r = outcome.record
    return {
        "arm_a": arm_a,
        "arm_b": arm_b,
        "metric": metric,
        "estimate": r["estimate"],
        "ci_lo": r["ci_lo"],
        "ci_hi": r["ci_hi"],
        "p_raw": r["p_raw"],
        "n": r["n"],
        "n_clusters": r["n_clusters"],
        "n_excluded": r["n_excluded"],
        "mdd": r.get("mdd"),
    }


def ablation_section(
    scores: Scores, arms: Sequence[str], config: StatConfig
) -> dict[str, Any] | None:
    """``structural`` against each ``structural_-x`` that was run, on two recall metrics."""
    if ABLATION_BASE not in arms:
        return None
    removed = [a for a in arms if a.startswith(f"{ABLATION_BASE}_-")]
    rows = []
    for arm in removed:
        for metric in ("recall", "recall10"):
            result = exploratory(scores, ABLATION_BASE, arm, metric, config, "ablation")
            if result is not None:
                result["channel"] = arm.split("_-", 1)[1]
                rows.append(result)
    return {"base": ABLATION_BASE, "rows": rows} if rows else None


def rerankers_section(
    scores: Scores,
    arms: Sequence[str],
    config: StatConfig,
    preregistered: dict[tuple[str, str], str],
) -> dict[str, Any] | None:
    """Reranked arms against the arm they differ from by the reranker alone."""
    rows = []
    for arm_a, arm_b in SINGLE_SHOT_PAIRS_RERANK:
        if arm_a in arms and arm_b in arms:
            result = exploratory(scores, arm_a, arm_b, "recall", config, "rerank")
            if result is not None:
                result["preregistered_id"] = preregistered.get((arm_a, arm_b))
                rows.append(result)
    return {"rows": rows} if rows else None


# --- trajectory -------------------------------------------------------------------------


def agent_arms(arms: Sequence[str]) -> list[str]:
    """Arms that run the tool-calling agent."""
    return [a for a in arms if a in ARMS and ARMS[a].is_agent]


def trajectory_section(
    data: RunData, scores: Scores, arms: Sequence[str], config: StatConfig
) -> dict[str, Any] | None:
    """Tool use, steps to the first gold file, wasted reads and stop reasons for agent arms."""
    chosen = agent_arms(arms)
    if not chosen:
        return None
    by_id = {i.id: i for i in scores.items}
    refs = _ref_map(scores)
    out: dict[str, Any] = {}
    curves: dict[str, Any] = {}
    for arm in chosen:
        ok = [r for r in scores.ok_rows(arm) if r.generation.steps]
        if not ok:
            continue
        reached = [r for r in ok if r.reached]
        never = len(ok) - len(reached)
        entry: dict[str, Any] = {
            "n_runs": len(ok),
            "n_items": len(scores.items),
            "ran_on_subset": len(scores.rows.get(arm, {})) < len(scores.items),
            "steps": mean_ci(
                [(refs[r.item_id], r.steps) for r in ok if r.steps is not None],
                config,
                f"trajectory:{arm}:steps",
            ),
            "steps_reached_median": median([r.steps for r in reached if r.steps is not None])
            if reached
            else None,
            "n_reached": len(reached),
            "never_reached": wilson(never, len(ok)),
        }
        generations = [r.generation for r in ok]
        entry["tool_calls"] = dict(
            sorted(sum((tool_call_counts(g.steps) for g in generations), Counter()).items())
        )
        entry["stop_reasons"] = dict(sorted(stop_reasons(generations).items()))
        wasted = []
        for r in ok:
            item = by_id[r.item_id]
            adjacency = data.graph.get(item.repo)
            if adjacency is None:
                continue
            result = wasted_reads(r.generation.steps, scored_gold(item), adjacency)
            if result.rate is not None:
                wasted.append((refs[r.item_id], result.rate))
        entry["wasted_reads"] = mean_ci(wasted, config, f"trajectory:{arm}:wasted")
        if any(step.worker_id for g in generations for step in g.steps):
            overlaps = [worker_overlap(g.steps) for g in generations]
            jaccards = [o.mean_jaccard for o in overlaps if o.mean_jaccard is not None]
            entry["worker_overlap"] = {
                "n": len(jaccards),
                "mean_jaccard": sum(jaccards) / len(jaccards) if jaccards else None,
            }
        out[arm] = entry
        horizon = min(STEP_CURVE_MAX, int(max(r.steps or 0 for r in ok)))
        curves[arm] = [
            [s, sum(1 for r in reached if r.steps is not None and r.steps <= s) / len(ok)]
            for s in range(horizon + 1)
        ]
    if not out:
        return None
    return {"by_arm": out, "steps_to_gold_curve": curves}


# --- cost and Pareto --------------------------------------------------------------------


def cost_section(
    scores: Scores, arms: Sequence[str], config: StatConfig, total_spend: float
) -> dict[str, Any] | None:
    """Dollars per question and per correct answer, tokens and latency percentiles."""
    refs = _ref_map(scores)
    table: dict[str, Any] = {}
    for arm in arms:
        ok = scores.ok_rows(arm)
        if not ok:
            continue
        summary = cost_summary(r.generation for r in ok)
        correct = sum(1 for r in ok if r.answer and (r.answer.recall or 0.0) >= CORRECT_RECALL)
        latencies = [r.latency_ms for r in ok]
        table[arm] = {
            "n": summary.n,
            "total_usd": summary.total_usd,
            "per_question": mean_ci(
                [(refs[r.item_id], r.cost) for r in ok], config, f"cost:{arm}:per_question"
            ),
            "n_correct": correct,
            "per_correct_usd": summary.total_usd / correct if correct else None,
            "tokens": {
                "input": summary.tokens.input,
                "cached": summary.tokens.cached,
                "output": summary.tokens.output,
                "input_per_question": summary.tokens.input / summary.n,
                "output_per_question": summary.tokens.output / summary.n,
            },
            "latency_p50_s": (percentile(latencies, 50) or 0.0) / 1000,
            "latency_p95_s": (percentile(latencies, 95) or 0.0) / 1000,
        }
    if not table:
        return None
    return {"by_arm": table, "run_spend_usd": total_spend}


def pareto_section(
    scores: Scores, arms: Sequence[str], cost: dict[str, Any] | None, main: dict[str, Any]
) -> dict[str, Any] | None:
    """Dollars per question against answer recall over every arm, with the frontier."""
    if cost is None:
        return None
    points = []
    for arm in arms:
        recall = main["by_arm"].get(arm, {}).get("recall")
        spend = cost["by_arm"].get(arm, {}).get("per_question")
        if recall and spend:
            points.append((arm, spend["mean"], recall["mean"]))
    if len(points) < 2:
        return None
    frontier = {name for name, _, _ in pareto_frontier(points)}
    return {
        "points": [
            {
                "arm": name,
                "cost_per_question": cost_value,
                "recall": recall,
                "n": main["by_arm"][name]["recall"]["n"],
                "on_frontier": name in frontier,
            }
            for name, cost_value, recall in points
        ],
        "frontier": [n for n, _, _ in pareto_frontier(points)],
        "auto_on_frontier": AUTO in frontier if any(p[0] == AUTO for p in points) else None,
    }


# --- routing ----------------------------------------------------------------------------


def routing_section(data: RunData, scores: Scores) -> dict[str, Any] | None:
    """What ``auto`` chose, how often it fell back, and whether it picked the best arm."""
    auto = [
        scores.rows[AUTO][i.id].generation
        for i in scores.items
        if i.id in scores.rows.get(AUTO, {})
    ]
    if not auto:
        return None
    outcomes: dict[str, dict[str, ArmOutcome]] = {}
    for arm, rows in scores.rows.items():
        outcomes[arm] = {
            item_id: ArmOutcome(recall=row.answer.recall, cost_usd=row.cost)
            for item_id, row in rows.items()
            if row.ok and row.answer is not None and row.answer.recall is not None
        }
    summary = routing_summary(auto, outcomes)
    n = summary.n
    confusion_total = sum(summary.confusion.values())
    agree = sum(c for (picked, best), c in summary.confusion.items() if picked == best)
    candidates = [a for a in ROUTABLE_ARMS if a in outcomes]
    decision_cost = sum(r.cost_usd or 0.0 for r in data.routes.values())
    return {
        "n": n,
        "routes": {k: wilson(v, n) for k, v in sorted(summary.route_distribution.items())},
        "targets": {k: wilson(v, n) for k, v in sorted(summary.target_distribution.items())},
        "fallbacks": {k: wilson(v, n) for k, v in sorted(summary.fallbacks.items())},
        "fallback_count": summary.fallback_count,
        "fallback_rate": wilson(summary.fallback_count, n),
        "comparison": [
            {
                "arm": c.arm,
                "n": c.n,
                "mean_recall": c.mean_recall,
                "mean_cost_usd": c.mean_cost_usd,
            }
            for c in summary.comparison
        ],
        "confusion": [
            {"picked": picked, "best": best, "count": count}
            for (picked, best), count in sorted(summary.confusion.items())
        ],
        "confusion_arms": candidates,
        "agreement": wilson(agree, confusion_total),
        "decision_cost_usd": decision_cost,
    }


# --- drift and cutoff ------------------------------------------------------------------


def drift_section(scores: Scores, arms: Sequence[str], config: StatConfig) -> dict[str, Any] | None:
    """Answer recall by how many merges after the base commit the pull request landed."""
    merges = {i.id: i.merges_since_base for i in scores.items if i.merges_since_base is not None}
    if not merges:
        return None
    buckets: dict[int, list[str]] = {}
    for item_id, count in merges.items():
        buckets.setdefault(count // DRIFT_WIDTH, []).append(item_id)
    if len(buckets) < 2:
        return None
    out = []
    for index in sorted(buckets):
        ids = buckets[index]
        out.append(
            {
                "lo": index * DRIFT_WIDTH,
                "hi": index * DRIFT_WIDTH + DRIFT_WIDTH - 1,
                "n_items": len(ids),
                "by_arm": {
                    arm: mean_ci(
                        _arm_values(scores, arm, "recall", ids), config, f"drift:{arm}:{index}"
                    )
                    for arm in arms
                },
            }
        )
    return {"width": DRIFT_WIDTH, "buckets": out}


def cutoff_section(
    scores: Scores, arms: Sequence[str], config: StatConfig
) -> dict[str, Any] | None:
    """Answer recall for pull requests merged before and after the generator's cutoff."""
    groups = {
        "pre_cutoff": [i.id for i in scores.items if i.post_cutoff is False],
        "post_cutoff": [i.id for i in scores.items if i.post_cutoff is True],
    }
    groups = {k: v for k, v in groups.items() if v}
    if not groups:
        return None
    return {
        "groups": {
            name: {
                "n_items": len(ids),
                "by_arm": {
                    arm: mean_ci(
                        _arm_values(scores, arm, "recall", ids), config, f"cutoff:{arm}:{name}"
                    )
                    for arm in arms
                },
            }
            for name, ids in groups.items()
        }
    }


# --- the judge --------------------------------------------------------------------------


def judge_results_section(
    data: RunData, arms: Sequence[str], config: StatConfig, exploratory_families: set[str]
) -> dict[str, Any] | None:
    """Judge grades per arm for rationale and hand items; structural items are a separate class."""
    if not data.judgments:
        return None
    final_keys = {g.record_key for g in data.generations}
    graded = [
        j
        for j in data.judgments
        if j.status == "ok" and j.generation_key in final_keys and j.item_id in data.items
    ]
    errors = Counter(
        j.family for j in data.judgments if j.status == "error" and j.generation_key in final_keys
    )

    def table(families: Sequence[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for family in families:
            rows = [j for j in graded if j.family == family]
            if not rows:
                continue
            per_arm: dict[str, Any] = {}
            for arm in arms:
                mine = [j for j in rows if j.arm == arm]
                if not mine:
                    continue
                refs = [ItemRef(j.item_id, data.items[j.item_id].repo, j.item_id) for j in mine]
                per_arm[arm] = {
                    "n": len(mine),
                    "correct": mean_ci(
                        zip(refs, (float(j.correct or 0) for j in mine), strict=True),
                        config,
                        f"judge:{family}:{arm}:correct",
                    ),
                    "faithful": mean_ci(
                        zip(refs, (float(j.faithful or 0) for j in mine), strict=True),
                        config,
                        f"judge:{family}:{arm}:faithful",
                    ),
                }
            result[family] = {
                "by_arm": per_arm,
                "n_judged": len(rows),
                "n_judge_errors": errors.get(family, 0),
                "exploratory": family in exploratory_families,
            }
        return result

    descriptive = table(JUDGED_FAMILIES)
    sanity = table((SANITY_FAMILY,))
    if not descriptive and not sanity:
        return None
    return {
        "judge": data.judge_slug,
        "descriptive": descriptive,
        "structural_sanity": sanity,
    }


def judge_agreement_section(data: RunData, config: StatConfig) -> dict[str, Any] | None:
    """Weighted kappa between the judge and the hand labels, per family, with intervals."""
    if not data.judgments or not data.judge_labels:
        return None
    report = judge_vs_human(
        data.judgments, data.judge_labels, resamples=config.n_boot_mean, seed=config.seed
    )
    if report.n == 0:
        return None
    return {
        "n": report.n,
        "minimum": report.minimum,
        "meets_minimum": report.meets_minimum,
        "entries": [
            {
                "family": e.family,
                "dimension": e.dimension,
                "n": e.n,
                "agreement": e.agreement,
                "kappa": e.kappa,
                "lo": e.lower,
                "hi": e.upper,
                "exploratory": e.exploratory,
            }
            for e in report.entries
        ],
        "exploratory_families": sorted(report.exploratory_families),
    }


# --- exclusions ------------------------------------------------------------------------


def exclusions_section(scores: Scores, arms: Sequence[str]) -> dict[str, Any] | None:
    """Every error record and every item an arm did not reach."""
    errors = []
    not_reached: dict[str, list[str]] = {}
    degraded = {}
    for arm in arms:
        rows = scores.rows.get(arm, {})
        for item in scores.items:
            row = rows.get(item.id)
            if row is None:
                not_reached.setdefault(arm, []).append(item.id)
            elif not row.ok:
                errors.append({"arm": arm, "item_id": item.id, "reason": row.error or ""})
        flagged = sum(1 for r in rows.values() if r.generation.flagged)
        unavailable = sum(r.generation.unavailable_tool_results for r in rows.values())
        if flagged or unavailable:
            degraded[arm] = {"flagged": flagged, "unavailable_tool_results": unavailable}
    if not errors and not not_reached and not degraded:
        return None
    return {"errors": errors, "not_reached": not_reached, "flagged": degraded}


def total_spend(data: RunData) -> float:
    """The run's recorded spend on generations and routing decisions."""
    from evals.run.budget import spent_in

    return spent_in(data.generations, data.routes.values())


def items_with(items: Iterable[GoldItem], family: str) -> list[GoldItem]:
    """The items of one family."""
    return [i for i in items if i.family == family]


__all__ = [
    "CHANGESET",
    "Score",
    "ablation_section",
    "agent_arms",
    "corpus_section",
    "cost_section",
    "cutoff_section",
    "drift_section",
    "exclusions_section",
    "exploratory",
    "gold_quality_section",
    "judge_agreement_section",
    "judge_results_section",
    "main_results_section",
    "mean_ci",
    "pareto_section",
    "rerankers_section",
    "retrieval_section",
    "routing_section",
    "scope_section",
    "single_shot_arms",
    "total_spend",
    "trajectory_section",
    "wilson",
]
