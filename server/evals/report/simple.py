"""The default report's numbers: arm tables, paired comparisons, codebase style and limitations.

Everything is a plain JSON-ready mapping. A cell is a mean with a 95% bootstrap interval that
resamples questions (pull request clusters) within each repository, the repositories being fixed
strata, and carries the ``n`` it rests on. A comparison is the mean per-question difference between
two arms answering the same questions, with the same kind of interval, and a verdict that only
says which arm is higher when the interval excludes zero. Nothing is tested for significance and no
sentence reaches beyond the repositories of the run.

:mod:`evals.report.render_simple` turns the result into ``report.md``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from evals.gold.mix import UNANSWERABLE_TAG
from evals.gold.schema import GoldItem
from evals.report import compute
from evals.report.comparisons import (
    SIMPLE_COMPARISONS,
    SIMPLE_METRICS,
    ItemRef,
    StatConfig,
    seed_for,
)
from evals.report.load import RunData
from evals.report.scores import Scores
from evals.report.wording import repositories_phrase
from evals.run.judge import Grade
from evals.stats import PairedObs, paired_bootstrap_ci, pareto_frontier

CHANGE = "change"
EXPLAIN = "explain"
KINDS = (CHANGE, EXPLAIN)
EXPLAIN_TEMPLATE = "hand.explain"
UNANSWERABLE_TEMPLATE = "hand.unanswerable"

TABLE_METRICS = (
    "recall",
    "precision",
    "correctness",
    "faithfulness",
    "relevancy",
    "cost",
    "speed",
    "steps",
)
JUDGED = ("correctness", "faithfulness", "relevancy")

METRIC_TITLE = {
    "recall": "file recall",
    "correctness": "correctness",
    "cost": "cost per answer",
}


def item_kind(item: GoldItem) -> str | None:
    """``change`` for a mined change question, ``explain`` for any answerable hand question.

    Hand questions of the older architecture and flow kinds count as explain questions, the same
    way the gold build counts them toward a repository's explain mix; unanswerable ones do not.
    """
    if item.family == "changeset":
        return CHANGE
    if item.family == "hand" and (
        item.template == EXPLAIN_TEMPLATE
        or (UNANSWERABLE_TAG not in item.tags and item.template != UNANSWERABLE_TEMPLATE)
    ):
        return EXPLAIN
    return None


@dataclass
class SimpleScores:
    """The scores of every arm on the change and explain questions, with the judge's grades.

    Attributes:
        scores: The file scores, cost and speed of every generation.
        grades: The judge's grade of each generation, by its key.
        kinds: The kind of each scored item.
    """

    scores: Scores
    grades: dict[str, Grade]
    kinds: dict[str, str]

    @classmethod
    def build(cls, data: RunData) -> SimpleScores:
        """Score the change and explain questions of a run.

        Args:
            data: The loaded run.

        Returns:
            The scores. Questions of other kinds are left out.
        """
        scores = Scores.build(data, include=lambda item: item_kind(item) is not None)
        return cls(
            scores=scores,
            grades={g.generation_key: g for g in data.judgments},
            kinds={i.id: item_kind(i) or "" for i in scores.items},
        )

    def get(self, arm: str, item_id: str, metric: str) -> float | None:
        """One metric of one arm on one question; ``None`` for an error or a missing grade.

        Args:
            arm: The arm.
            item_id: The question.
            metric: One of :data:`TABLE_METRICS`.

        Returns:
            File recall and precision and the judge's scores as fractions, cost in dollars,
            speed in seconds and steps as a count of tool calls.
        """
        row = self.scores.rows.get(arm, {}).get(item_id)
        if row is None or not row.ok:
            return None
        if metric == "recall":
            return row.answer.recall if row.answer else None
        if metric == "precision":
            return row.answer.precision if row.answer else None
        if metric == "cost":
            return row.cost
        if metric == "speed":
            return row.latency_ms / 1000.0
        if metric == "steps":
            calls = [s for s in row.generation.steps if s.kind == "tool_call"]
            return float(len(calls)) if calls else None
        grade = self.grades.get(row.generation.record_key)
        if grade is None:
            return None
        if metric == "correctness":
            return grade.correct_score
        if metric == "faithfulness":
            return grade.faithful_score
        if metric == "relevancy":
            return grade.relevancy_score
        raise KeyError(f"unknown metric {metric!r}")

    def refs(self, ids: set[str] | None = None) -> list[ItemRef]:
        """The pairing identities of the scored questions, optionally of a subset."""
        return [r for r in self.scores.refs if ids is None or r.id in ids]


# --- the tables -------------------------------------------------------------------------


def _cell(
    ss: SimpleScores, arm: str, metric: str, refs: Sequence[ItemRef], config: StatConfig, name: str
) -> dict[str, Any] | None:
    values = [(r, v) for r in refs if (v := ss.get(arm, r.id, metric)) is not None]
    return compute.mean_ci(values, config, f"{name}:{arm}:{metric}")


def arm_table(
    ss: SimpleScores, arms: Sequence[str], refs: Sequence[ItemRef], config: StatConfig, name: str
) -> dict[str, Any]:
    """One table: a row per arm with the six metrics and the counts beside them.

    Args:
        ss: The scores.
        arms: The arms, in table order.
        refs: The questions the table covers.
        config: Resampling sizes and seed.
        name: What seeds the table's resampling, so two tables never share draws.

    Returns:
        ``n_questions`` and ``arms``, a mapping of arm to its cells (``recall``, ``precision``,
        ``correctness``, ``faithfulness``, ``relevancy``, ``cost``, ``speed``, ``steps``; each a
        mean with its interval and ``n`` or ``None``), ``format_failures`` (a Wilson rate),
        ``n_scored``, ``n_errors``, ``n_judge_missing`` and ``n_not_reached``.
    """
    ids = {r.id for r in refs}
    out: dict[str, Any] = {}
    for arm in arms:
        rows = [r for r in ss.scores.rows.get(arm, {}).values() if r.item_id in ids]
        ok = [r for r in rows if r.ok]
        scored = [r for r in ok if r.answer is not None]
        failures = sum(1 for r in scored if r.answer and r.answer.format_failure)
        entry: dict[str, Any] = {
            metric: _cell(ss, arm, metric, refs, config, name) for metric in TABLE_METRICS
        }
        entry["format_failures"] = compute.wilson(failures, len(scored))
        entry["n_scored"] = len(ok)
        entry["n_errors"] = len(rows) - len(ok)
        entry["n_not_reached"] = len(ids) - len(rows)
        entry["n_judge_missing"] = sum(
            1 for r in ok if ss.get(arm, r.item_id, "correctness") is None
        )
        out[arm] = entry
    return {"n_questions": len(ids), "arms": out}


def _drop_empty_metrics(table: dict[str, Any]) -> list[str]:
    """The metrics at least one arm has a value for, in column order."""
    return [m for m in TABLE_METRICS if any(a.get(m) for a in table["arms"].values())]


def tables_section(
    ss: SimpleScores, arms: Sequence[str], config: StatConfig, repos: Sequence[str]
) -> dict[str, Any]:
    """The overall table, one per repository and one per question kind."""
    refs = ss.refs()
    overall = arm_table(ss, arms, refs, config, "overall")
    by_repo = {
        repo: arm_table(ss, arms, [r for r in refs if r.repo == repo], config, f"repo:{repo}")
        for repo in repos
    }
    present_kinds = [k for k in KINDS if any(ss.kinds[r.id] == k for r in refs)]
    by_kind = (
        {
            kind: arm_table(
                ss, arms, [r for r in refs if ss.kinds[r.id] == kind], config, f"kind:{kind}"
            )
            for kind in present_kinds
        }
        if len(present_kinds) > 1
        else {}
    )
    metrics = _drop_empty_metrics(overall)
    return {"metrics": metrics, "overall": overall, "by_repo": by_repo, "by_kind": by_kind}


# --- head to head -----------------------------------------------------------------------


def verdict_of(low: float, high: float) -> str:
    """``A higher`` or ``B higher`` when the interval excludes zero, otherwise ``not resolved``."""
    if low > 0:
        return "A higher"
    if high < 0:
        return "B higher"
    return "not resolved"


def difference(
    ss: SimpleScores,
    arm_a: str,
    arm_b: str,
    metric: str,
    refs: Sequence[ItemRef],
    config: StatConfig,
    scope: str,
) -> dict[str, Any] | None:
    """The paired difference of two arms on a metric over a set of questions.

    Args:
        ss: The scores.
        arm_a: The first arm.
        arm_b: The second arm.
        metric: ``recall``, ``correctness`` or ``cost``.
        refs: The questions.
        config: Resampling sizes and seed.
        scope: ``overall`` or a repository's name.

    Returns:
        The mean of ``a - b`` with its 95% cluster bootstrap interval, ``n`` (questions both arms
        have a result for), the clusters and exclusions behind it and the verdict; ``None`` when
        no question has a result from both arms.
    """
    obs = [
        PairedObs(r.repo, r.cluster, ss.get(arm_a, r.id, metric), ss.get(arm_b, r.id, metric))
        for r in refs
    ]
    if not any(o.a is not None and o.b is not None for o in obs):
        return None
    ci = paired_bootstrap_ci(
        obs,
        n_boot=config.n_boot,
        seed=seed_for(f"h2h:{arm_a}:{arm_b}:{metric}:{scope}", config.seed),
    )
    return {
        "arm_a": arm_a,
        "arm_b": arm_b,
        "metric": metric,
        "scope": scope,
        "estimate": ci.estimate,
        "ci_lo": ci.lo,
        "ci_hi": ci.hi,
        "n": ci.n,
        "n_clusters": ci.n_clusters,
        "n_excluded": ci.n_excluded,
        "verdict": verdict_of(ci.lo, ci.hi),
    }


def diff_text(metric: str, value: float, *, signed: bool = False) -> str:
    """A difference as printed: dollars to five decimals, scores to three.

    Three decimals keep an interval that excludes zero from printing as ``0.00``.

    Args:
        metric: ``recall``, ``correctness`` or ``cost``.
        value: The difference.
        signed: Put an explicit ``+`` on a positive value.

    Returns:
        The text, with the minus sign before the dollar symbol.
    """
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    body = f"${abs(value):.5f}" if metric == "cost" else f"{abs(value):.3f}"
    return sign + body


def sentence(record: dict[str, Any], repositories: int) -> str:
    """The one sentence a paired difference is stated in.

    An interval that excludes zero is stated as a result on these repositories, with the
    estimate, interval and ``n``, naming the arm that is higher first. Any other difference is
    not resolved at this sample size.

    Args:
        record: A record from :func:`difference`.
        repositories: How many repositories the run covers.

    Returns:
        A complete sentence.
    """
    metric = record["metric"]
    n = record["n"]
    title = METRIC_TITLE[metric]
    if record["verdict"] == "not resolved":
        return (
            f"Not resolved at this sample size (`{record['arm_a']}` against "
            f"`{record['arm_b']}`, {title}, n = {n})."
        )
    scope = (
        repositories_phrase(repositories)
        if record["scope"] == "overall"
        else f"On the repository `{record['scope']}`"
    )
    low, high, estimate = record["ci_lo"], record["ci_hi"], record["estimate"]
    first, second = record["arm_a"], record["arm_b"]
    if record["verdict"] == "B higher":
        first, second = second, first
        low, high, estimate = -high, -low, -estimate
    detail = (
        f"({diff_text(metric, estimate, signed=True)}, 95% CI {diff_text(metric, low)} to "
        f"{diff_text(metric, high)}, n = {n})"
    )
    if metric == "cost":
        return f"{scope}, `{first}` cost more per answer than `{second}` {detail}."
    return f"{scope}, `{first}` scored higher than `{second}` on {title} {detail}."


def comparisons_section(
    ss: SimpleScores, arms: Sequence[str], config: StatConfig, repos: Sequence[str]
) -> list[dict[str, Any]]:
    """Every head-to-head row whose two arms were run, overall and per repository.

    Args:
        ss: The scores.
        arms: The arms with records.
        config: Resampling sizes and seed.
        repos: The repositories, in report order.

    Returns:
        One record per comparison, metric and scope, in the order of the design freeze. A
        comparison with an arm that was not run is left out, and so is a metric with no paired
        result.
    """
    present = set(arms)
    refs = ss.refs()
    records: list[dict[str, Any]] = []
    for arm_a, arm_b in SIMPLE_COMPARISONS:
        if arm_a not in present or arm_b not in present:
            continue
        for metric in SIMPLE_METRICS:
            scopes: list[tuple[str, Sequence[ItemRef]]] = [("overall", refs)]
            scopes += [(repo, [r for r in refs if r.repo == repo]) for repo in repos]
            for scope, scoped in scopes:
                record = difference(ss, arm_a, arm_b, metric, scoped, config, scope)
                if record is not None:
                    record["sentence"] = sentence(record, len(repos))
                    records.append(record)
    return records


# --- scope ------------------------------------------------------------------------------


def scope_section(data: RunData, ss: SimpleScores, arms: Sequence[str]) -> dict[str, Any]:
    """The repositories, their eras and base commits, question counts, models and arms."""
    items = list(data.items.values())
    repos = sorted({i.repo for i in items})
    pins = data.manifest.get("corpus_pins") or {}
    kinds = Counter()
    per_repo: dict[str, Counter[str]] = {r: Counter() for r in repos}
    for item in items:
        kind = item_kind(item) or f"other ({item.family})"
        kinds[kind] += 1
        per_repo[item.repo][kind] += 1
    generator = str((data.manifest.get("models") or {}).get("generator", ""))
    judge_model = (data.judge_manifest or {}).get("models", {}).get("judge")
    return {
        "repositories": [
            {
                "name": repo,
                "era": data.corpus.get(repo, {}).get("era"),
                "language": data.corpus.get(repo, {}).get("language"),
                "base_commit": pins.get(repo),
                "base_date": data.corpus.get(repo, {}).get("base_date"),
                "questions": dict(sorted(per_repo[repo].items())),
            }
            for repo in repos
        ],
        "n_repositories": len(repos),
        "n_questions": len(items),
        "n_scored_questions": len(ss.scores.items),
        "questions": dict(sorted(kinds.items())),
        "arms": list(arms),
        "n_arms": len(arms),
        "generator_models": [m for m in generator.split(",") if m],
        "judge_model": judge_model,
        "deepeval_versions": list(data.deepeval_versions),
        "slice": data.slice_name,
    }


# --- codebase style and how arms move across repositories -------------------------------


def style_section(data: RunData, repos: Sequence[str]) -> dict[str, Any] | None:
    """The captured codebase measurements for the run's repositories, or ``None``."""
    found = {repo: data.style[repo] for repo in repos if repo in data.style}
    return {"repos": found, "recent_window_months": 12} if found else None


def _best(per_repo: dict[str, float], high: bool) -> tuple[str, float]:
    pick = max if high else min
    repo = pick(per_repo, key=lambda r: (per_repo[r], r))
    return repo, per_repo[repo]


def observations_section(
    tables: dict[str, Any], scope: dict[str, Any], arms: Sequence[str]
) -> dict[str, Any] | None:
    """How each arm's results move across the repositories, stated as observation only.

    Args:
        tables: The result of :func:`tables_section`.
        scope: The result of :func:`scope_section`.
        arms: The arms in table order.

    Returns:
        Per arm and metric the highest and lowest repository means, and which arm had the
        highest file recall on each repository; ``None`` with fewer than two repositories.
    """
    repos = [r["name"] for r in scope["repositories"] if r["name"] in tables["by_repo"]]
    if len(repos) < 2:
        return None
    label = {r["name"]: r.get("era") for r in scope["repositories"]}
    rows: list[dict[str, Any]] = []
    for arm in arms:
        for metric in ("recall", "correctness"):
            per_repo = {}
            for repo in repos:
                cell = tables["by_repo"][repo]["arms"].get(arm, {}).get(metric)
                if cell:
                    per_repo[repo] = cell["mean"]
            if len(per_repo) < 2:
                continue
            high, low = _best(per_repo, True), _best(per_repo, False)
            rows.append(
                {
                    "arm": arm,
                    "metric": metric,
                    "highest": {"repo": high[0], "era": label.get(high[0]), "mean": high[1]},
                    "lowest": {"repo": low[0], "era": label.get(low[0]), "mean": low[1]},
                }
            )
    leaders: dict[str, str] = {}
    for repo in repos:
        means = {
            arm: cell["mean"]
            for arm, entry in tables["by_repo"][repo]["arms"].items()
            if (cell := entry.get("recall"))
        }
        if means:
            leaders[repo] = max(means, key=lambda a: (means[a], a))
    if not rows:
        return None
    return {"n_repositories": len(repos), "rows": rows, "recall_leaders": leaders}


# --- cost against quality ---------------------------------------------------------------


def cost_quality_section(tables: dict[str, Any]) -> dict[str, Any] | None:
    """Dollars per answer against correctness for every arm, with the frontier."""
    points = []
    for arm, entry in tables["overall"]["arms"].items():
        cost, quality = entry.get("cost"), entry.get("correctness")
        if cost and quality:
            points.append((arm, cost["mean"], quality["mean"], quality["n"]))
    if len(points) < 2:
        return None
    frontier = [name for name, _, _ in pareto_frontier([(p[0], p[1], p[2]) for p in points])]
    return {
        "points": [
            {
                "arm": name,
                "cost_per_answer": cost,
                "correctness": quality,
                "n": n,
                "on_frontier": name in frontier,
            }
            for name, cost, quality, n in points
        ],
        "frontier": frontier,
    }


# --- the judge check --------------------------------------------------------------------


def judge_check_section(data: RunData, config: StatConfig) -> dict[str, Any] | None:
    """Agreement with the hand-scored answers; a not-done marker when judgments exist alone."""
    if not data.judgments:
        return None
    agreement = compute.judge_agreement_section(data, config)
    if agreement is None:
        return {"done": False, "labels_found": len(data.judge_labels)}
    pooled = [e for e in agreement["entries"] if e["family"] == "all"]
    entries = pooled or agreement["entries"]
    poor = any(e["exploratory"] for e in entries)
    return {
        "done": True,
        "n": agreement["n"],
        "minimum": agreement["minimum"],
        "meets_minimum": agreement["meets_minimum"],
        "entries": entries,
        "exploratory": poor,
    }


# --- limitations ------------------------------------------------------------------------


def _rate_text(k: int, n: int) -> str:
    return f"{k} of {n} ({k / n * 100:.1f}%)" if n else "none"


def limitations_section(
    data: RunData,
    scope: dict[str, Any],
    tables: dict[str, Any],
    judge_check: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """The run's limitations, each with the numbers it states.

    Args:
        data: The loaded run.
        scope: The scope section.
        tables: The tables section.
        judge_check: The judge check section.

    Returns:
        Records with ``id``, ``text`` and ``facts``; the text is built from the facts, which go
        into ``report.json`` beside it.
    """
    n_repos = scope["n_repositories"]
    eras = [r.get("era") for r in scope["repositories"]]
    per_era = (
        f", one per era ({', '.join(eras)})" if all(eras) and len(set(eras)) == len(eras) else ""
    )
    arms = tables["overall"]["arms"].values()
    generations = sum(a["n_scored"] + a["n_errors"] for a in arms)
    errors = sum(a["n_errors"] for a in arms)
    scored = sum(a["n_scored"] for a in arms)
    failures = sum(a["format_failures"]["k"] for a in arms)
    answered = sum(a["format_failures"]["n"] for a in arms)
    judge_missing = sum(a["n_judge_missing"] for a in arms)
    out: list[dict[str, Any]] = [
        {
            "id": "repositories",
            "text": (
                f"{n_repos} repositories{per_era}. Every result describes these repositories at "
                "their base commits and says nothing about other codebases."
            ),
            "facts": {"n_repositories": n_repos},
        },
        {
            "id": "generator",
            "text": (
                f"{len(scope['generator_models'])} generator "
                f"{'model' if len(scope['generator_models']) == 1 else 'models'} "
                f"({', '.join(f'`{m}`' for m in scope['generator_models']) or 'not recorded'}); "
                "other models may order the arms differently."
            ),
            "facts": {"n_generator_models": len(scope["generator_models"])},
        },
    ]
    explain = scope["questions"].get(EXPLAIN, 0)
    if explain:
        checks = data.checks
        if checks:
            checked = checks["supported"] + checks["partly_supported"] + checks["unsupported"]
            check_text = (
                f"A second model checked them against the code: {checks['supported']} supported, "
                f"{checks['partly_supported']} partly supported and {checks['unsupported']} "
                f"unsupported of {checked} checked ({checks['errors']} failed checks)."
            )
        else:
            check_text = "No check result was found in the output directory."
        out.append(
            {
                "id": "explain_keys",
                "text": (
                    f"The {explain} explain questions have answer keys written by a model. "
                    f"{check_text}"
                ),
                "facts": {"n_explain": explain, "checks": dict(checks)},
            }
        )
    if scope["judge_model"]:
        out.append(
            {
                "id": "same_model",
                "text": (
                    "One model phrases the change questions and judges every answer "
                    f"(judge: `{scope['judge_model']}`), so its own wording habits may favour "
                    "answers that resemble it."
                ),
                "facts": {},
            }
        )
    if judge_check is not None:
        if judge_check["done"]:
            entry = next((e for e in judge_check["entries"] if e["dimension"] == "correct"), None)
            kappa = (
                f"weighted kappa {entry['kappa']:.2f} (95% CI {entry['lo']:.2f} to "
                f"{entry['hi']:.2f}), exact agreement {entry['agreement'] * 100:.1f}%"
                if entry and entry["kappa"] is not None and entry["agreement"] is not None
                else "no usable agreement figure"
            )
            suffix = (
                " The agreement is poor, so the judged columns are exploratory."
                if judge_check["exploratory"]
                else ""
            )
            enough = (
                ""
                if judge_check["meets_minimum"]
                else f" This is fewer than the {judge_check['minimum']} answers the check needs."
            )
            text = (
                f"The judge was compared with {judge_check['n']} hand-scored answers on "
                f"correctness: {kappa}.{enough}{suffix}"
            )
        else:
            text = (
                "The judge has not been checked against hand-scored answers, so the judged "
                "columns are unvalidated."
            )
        out.append({"id": "judge", "text": text, "facts": {"done": judge_check["done"]}})
    out.append(
        {
            "id": "errors",
            "text": (
                f"Errors: {_rate_text(errors, generations)} generations ended in an error and are "
                f"excluded from their cells. Format failures: {_rate_text(failures, answered)} "
                "answers had no `Files:` list and score 0 file recall."
                + (
                    f" {judge_missing} completed answers lack a correctness grade."
                    if judge_missing and scope["judge_model"]
                    else ""
                )
            ),
            "facts": {
                "generations": generations,
                "errors": errors,
                "scored": scored,
                "format_failures": failures,
                "answered": answered,
                "judge_missing": judge_missing,
                "error_rate": errors / generations if generations else None,
                "format_failure_rate": failures / answered if answered else None,
            },
        }
    )
    final_keys = {g.record_key for g in data.generations}
    excluded = [g for g in data.judgments if g.not_applicable and g.generation_key in final_keys]
    if excluded:
        listing = ", ".join(f"`{g.arm}` on `{g.item_id}`" for g in excluded)
        out.append(
            {
                "id": "empty_answers",
                "text": (
                    f"{len(excluded)} empty "
                    f"{'answer has' if len(excluded) == 1 else 'answers have'} no faithfulness "
                    "or relevancy score and "
                    f"{'is' if len(excluded) == 1 else 'are'} left out of those columns; "
                    f"correctness counts {'it' if len(excluded) == 1 else 'them'} as 0: "
                    f"{listing}."
                ),
                "facts": {
                    "empty_answers": [{"arm": g.arm, "item_id": g.item_id} for g in excluded]
                },
            }
        )
    reach = {arm: a["n_not_reached"] for arm, a in tables["overall"]["arms"].items()}
    missing = {arm: n for arm, n in reach.items() if n}
    if missing:
        listing = ", ".join(f"`{arm}` {n}" for arm, n in missing.items())
        out.append(
            {
                "id": "not_reached",
                "text": (
                    f"Questions an arm did not reach (a budget stop, nothing imputed): {listing}."
                ),
                "facts": {"not_reached": missing},
            }
        )
    return out


# --- the whole report -------------------------------------------------------------------


def assemble_simple(data: RunData, config: StatConfig) -> dict[str, Any]:
    """Compute every section of the default report from a loaded run.

    Args:
        data: The loaded run.
        config: Resampling sizes and seed.

    Returns:
        The report data; a section with no data is absent.
    """
    ss = SimpleScores.build(data)
    arms = ss.scores.arms()
    scope = scope_section(data, ss, arms)
    report: dict[str, Any] = {"schema": 1, "mode": "simple", "scope": scope}
    report["run"] = {
        "name": data.name,
        "slice": data.slice_name,
        "generator_models": scope["generator_models"],
        "judge_model": scope["judge_model"],
        "judge_slug": data.judge_slug,
        "deepeval_versions": scope["deepeval_versions"],
        "confidence_level": 0.95,
        "notes": list(data.notes),
    }
    repos = [r["name"] for r in scope["repositories"]]
    if ss.scores.items and arms:
        tables = tables_section(ss, arms, config, repos)
        report["tables"] = tables
        report["comparisons"] = comparisons_section(ss, arms, config, repos)
        report["observations"] = observations_section(tables, scope, arms)
        report["cost_quality"] = cost_quality_section(tables)
        judge_check = judge_check_section(data, config)
        report["judge_check"] = judge_check
        report["limitations"] = limitations_section(data, scope, tables, judge_check)
    report["style"] = style_section(data, repos)
    for name in [n for n, v in report.items() if v in (None, [], {})]:
        del report[name]
    report["sections"] = [
        name
        for name in (
            "scope",
            "tables",
            "comparisons",
            "style",
            "cost_quality",
            "judge_check",
            "limitations",
        )
        if name in report
    ]
    return report


# --- the per-question export -----------------------------------------------------------

QUESTION_COLUMNS = (
    "repo",
    "era",
    "item_id",
    "kind",
    "template",
    "question",
    "arm",
    "status",
    "error",
    "file_recall",
    "file_precision",
    "files_required",
    "files_found",
    "files_listed",
    "format_failure",
    "correctness",
    "correctness_rubric",
    "faithfulness",
    "answer_relevancy",
    "judge_errors",
    "cost_usd",
    "seconds",
    "tool_steps",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "generation_key",
)
"""The columns of the per-question export, in order."""


def question_rows(data: RunData, ss: SimpleScores | None = None) -> list[dict[str, Any]]:
    """One row per question and arm, with every metric the tables average.

    Every generation of a change or explain question appears, errors included, so a reader can
    see exactly which answers each average rests on. A metric that does not apply or was not
    graded is ``None``.

    Args:
        data: The loaded run.
        ss: The scores, when already built.

    Returns:
        The rows, ordered by repository, question and arm; each has the keys in
        :data:`QUESTION_COLUMNS`.
    """
    ss = ss or SimpleScores.build(data)
    rows: list[dict[str, Any]] = []
    for arm in ss.scores.arms():
        for item_id, row in ss.scores.rows.get(arm, {}).items():
            item = data.items[item_id]
            grade = ss.grades.get(row.generation.record_key)
            answer = row.answer if row.ok else None
            rows.append(
                {
                    "repo": item.repo,
                    "era": data.corpus.get(item.repo, {}).get("era"),
                    "item_id": item_id,
                    "kind": ss.kinds.get(item_id) or None,
                    "template": item.template,
                    "question": item.question or item.question_seed,
                    "arm": arm,
                    "status": "ok" if row.ok else "error",
                    "error": row.error,
                    "file_recall": answer.recall if answer else None,
                    "file_precision": answer.precision if answer else None,
                    "files_required": answer.gold_n if answer else None,
                    "files_found": answer.tp if answer else None,
                    "files_listed": answer.listed if answer else None,
                    "format_failure": answer.format_failure if answer else None,
                    "correctness": ss.get(arm, item_id, "correctness"),
                    "correctness_rubric": grade.correct if grade and row.ok else None,
                    "faithfulness": ss.get(arm, item_id, "faithfulness"),
                    "answer_relevancy": ss.get(arm, item_id, "relevancy"),
                    "judge_errors": ",".join(sorted(grade.errors))
                    if grade and grade.errors
                    else None,
                    "cost_usd": row.cost,
                    "seconds": row.latency_ms / 1000.0,
                    "tool_steps": ss.get(arm, item_id, "steps"),
                    "input_tokens": row.tokens.input,
                    "cached_input_tokens": row.tokens.cached,
                    "output_tokens": row.tokens.output,
                    "generation_key": row.generation.record_key,
                }
            )
    rows.sort(key=lambda r: (r["repo"], r["item_id"], r["arm"]))
    return rows


__all__ = [
    "CHANGE",
    "EXPLAIN",
    "QUESTION_COLUMNS",
    "SimpleScores",
    "arm_table",
    "assemble_simple",
    "diff_text",
    "item_kind",
    "question_rows",
    "sentence",
    "verdict_of",
]
