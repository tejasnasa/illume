"""The pilot report's limitations, encoded as data and filled from the run's own numbers.

Each limitation has three parts: what it is; its effect on reading this report, written with the
pilot's own numbers (sample sizes, interval widths, minimum detectable differences, the gold
error rate, kappa, the arms that were not run, the post-cutoff count); and how the full-run
design addresses it, written as a description of that design and never as a promise. The one
generator model is the exception: the full-run design does not address it either, and the row
says so. Counts in the titles come from the data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

from evals.arms import ARMS
from evals.models import JUDGE_MODEL, PHRASER_MODEL
from evals.report.comparisons import FULL_COMPARISONS, PILOT_COMPARISONS
from evals.report.fmt import code, num, pct, pts, span_pct

Facts = Mapping[str, Any]


@dataclass(frozen=True)
class Limitation:
    """One row of the limitations table.

    Attributes:
        id: A stable identifier.
        title: Builds the row's heading from the data.
        what: Builds what the limitation is.
        effect: Builds its effect on this report, with the pilot's own numbers.
        full_run: The description of how the full-run design addresses it.
        values: Builds the numbers the row prints, for ``report.json``.
    """

    id: str
    title: Callable[[Facts], str]
    what: Callable[[Facts], str]
    effect: Callable[[Facts], str]
    full_run: str
    values: Callable[[Facts], dict[str, Any]]


def _recall_comparisons(facts: Facts) -> list[Mapping[str, Any]]:
    return [
        c
        for c in facts["comparisons"]
        if c["metric"] == "recall" and c.get("kind", "diff") == "diff" and c.get("mdd") is not None
    ]


def _width_stats(facts: Facts) -> dict[str, Any]:
    comparisons = _recall_comparisons(facts)
    if not comparisons:
        return {"n_recall_comparisons": 0}
    mdds = [c["mdd"] for c in comparisons]
    half = [(c["ci_hi"] - c["ci_lo"]) / 2 for c in comparisons]
    return {
        "n_recall_comparisons": len(comparisons),
        "mdd_min": min(mdds),
        "mdd_max": max(mdds),
        "median_half_width": median(half),
        "n": max(c["n"] for c in comparisons),
        "n_clusters": max(c["n_clusters"] for c in comparisons),
    }


def _kappa(facts: Facts, family: str, dimension: str) -> Mapping[str, Any] | None:
    agreement = facts.get("judge_agreement")
    if not agreement:
        return None
    for entry in agreement["entries"]:
        if entry["family"] == family and entry["dimension"] == dimension:
            return entry
    return None


def _names(names: Sequence[str]) -> str:
    quoted = [code(n) for n in names]
    if len(quoted) <= 1:
        return "".join(quoted)
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def missing_arms(present: Sequence[str]) -> list[str]:
    """The arms of the full arm set that the run did not include."""
    return [name for name in ARMS if name not in present]


def uncovered_hypotheses(missing: Sequence[str]) -> list[str]:
    """Full-run hypotheses that need at least one arm that was not run."""
    out: list[str] = []
    for spec in FULL_COMPARISONS:
        if set(spec.arms) & set(missing) and spec.hypothesis not in out:
            out.append(spec.hypothesis)
    return out


def _channels_missing(missing: Sequence[str]) -> list[str]:
    return [m.split("_-", 1)[1] for m in missing if m.startswith("structural_-")]


# --- the rows ----------------------------------------------------------------------------


def _changeset_title(f: Facts) -> str:
    return f"{f['scope']['n_changeset']} change-set questions"


def _changeset_what(f: Facts) -> str:
    s = f["scope"]
    return (
        f"The pilot asks {s['n_changeset']} change-set questions drawn from "
        f"{s['n_changeset_clusters']} pull requests; the anchor and blind variants of one pull "
        "request move together as one cluster, so the effective sample is the cluster count."
    )


def _changeset_effect(f: Facts) -> str:
    w = _width_stats(f)
    if not w["n_recall_comparisons"]:
        return "No answer-recall comparison could be computed from the arms that were run."
    return (
        f"Intervals are wide and only large gaps are resolved. Across the "
        f"{w['n_recall_comparisons']} recall comparisons the minimum detectable difference runs "
        f"from {pts(w['mdd_min'])} to {pts(w['mdd_max'])} points, and the median half-width of "
        f"a paired 95% interval is {pts(w['median_half_width'])} points "
        f"(up to n = {w['n']} items in {w['n_clusters']} clusters)."
    )


def _repos_title(f: Facts) -> str:
    s = f["scope"]
    text = f"{s['n_repositories']} repositories"
    if s["n_languages"]:
        text += f", {s['n_languages']} languages"
    return text


def _repos_what(f: Facts) -> str:
    s = f["scope"]
    languages = f" in {_names(s['languages'])}" if s["languages"] else ""
    return f"The corpus is {_names(s['repositories'])}{languages}."


def _repos_effect(f: Facts) -> str:
    s = f["scope"]
    return (
        f"Results describe these {s['n_repositories']} repositories only. A per-repository "
        f"direction count can be at most {s['n_repositories']} of {s['n_repositories']} and "
        "says nothing about a wider population."
    )


def _split_title(f: Facts) -> str:
    return "No separate tuning and test split"


def _split_what(f: Facts) -> str:
    s = f["scope"]
    return f"All {s['n_questions']} questions sit in one `{s['slice']}` slice."


def _split_effect(f: Facts) -> str:
    return (
        "Templates and the judge rubric were fixed while looking at the same items that are "
        "reported, which can bias results upward; this report cannot size that bias."
    )


def _prereg_title(f: Facts) -> str:
    return "Light pre-registration only"


def _prereg_what(f: Facts) -> str:
    primary = sum(1 for s in PILOT_COMPARISONS if s.family == "primary")
    secondary = sum(1 for s in PILOT_COMPARISONS if s.family == "secondary")
    return (
        f"The pilot pre-states {primary} primary and {secondary} secondary comparisons and "
        "no others."
    )


def _prereg_effect(f: Facts) -> str:
    run = {"primary": 0, "secondary": 0}
    for c in f["comparisons"]:
        if c["family"] in run:
            run[c["family"]] += 1
    primary = sum(1 for s in PILOT_COMPARISONS if s.family == "primary")
    secondary = sum(1 for s in PILOT_COMPARISONS if s.family == "secondary")
    return (
        f"{run['primary']} of {primary} primary and {run['secondary']} of {secondary} secondary "
        "comparisons could be computed from the arms that were run. No equivalence margins were "
        "pre-stated, so no result here reads as equivalence, and every other comparison in this "
        "report is exploratory."
    )


def _small_title(f: Facts) -> str:
    fam = f["scope"]["families"]
    return f"{fam.get('rationale', 0)} rationale and {fam.get('hand', 0)} hand-written questions"


def _small_what(f: Facts) -> str:
    return (
        "Rationale and hand-written questions are graded by the judge rather than scored "
        "against changed files, and there are few of them."
    )


def _judged(f: Facts) -> dict[str, int]:
    judge = f.get("judge_results") or {}
    return {family: block["n_judged"] for family, block in (judge.get("descriptive") or {}).items()}


def _small_effect(f: Facts) -> str:
    judged = _judged(f)
    if not judged:
        return "No judged answers are in this run, so there are no answer-quality results."
    parts = ", ".join(f"n = {n} judged {family} answers" for family, n in sorted(judged.items()))
    return f"Answer-quality results rest on {parts} across all arms and are descriptive only."


def _judge_title(f: Facts) -> str:
    agreement = f.get("judge_agreement")
    labels = agreement["n"] if agreement else 0
    same = JUDGE_MODEL == PHRASER_MODEL
    who = f"{code(JUDGE_MODEL)} both phrased and judged" if same else "a different judge phrased"
    return f"Judge checked on {labels} labels; {who}"


def _judge_what(f: Facts) -> str:
    return (
        "The judge was checked against a small hand-labelled sample, and the model that "
        "phrased the questions also judged the answers, so it may favour answers to questions "
        "it phrased."
    )


def _judge_effect(f: Facts) -> str:
    pooled = _kappa(f, "all", "correct")
    if pooled is None or pooled["kappa"] is None:
        return (
            "The judge was not checked against hand labels in this run, so its agreement "
            "is unknown."
        )
    text = (
        f"Pooled weighted kappa on correctness is {num(pooled['kappa'])} "
        f"(95% CI {num(pooled['lo'])} to {num(pooled['hi'])}, n = {pooled['n']}), so agreement "
        "is uncertain."
    )
    flagged = (f.get("judge_agreement") or {}).get("exploratory_families") or []
    if flagged:
        text += f" Families reported as exploratory (kappa below the cut-off): {_names(flagged)}."
    return text


def _arms_title(f: Facts) -> str:
    missing = missing_arms(f["scope"]["arms"])
    return f"Arms not run ({_names(missing)})" if missing else "Arms not run (none)"


def _arms_what(f: Facts) -> str:
    missing = missing_arms(f["scope"]["arms"])
    if not missing:
        return "Every arm of the full arm set was run."
    return f"These arms of the full arm set were left out of the run: {_names(missing)}."


def _arms_effect(f: Facts) -> str:
    missing = missing_arms(f["scope"]["arms"])
    if not missing:
        return "Every pre-registered full-run hypothesis has its arms in this run."
    parts = []
    if "hybrid_jev" in missing:
        parts.append("The Jev-versus-Cohere reranker comparison is not covered")
    channels = _channels_missing(missing)
    if channels:
        parts.append(
            f"the channel ablations for {', '.join(channels)} are not covered "
            "(only the ablations of the arms that were run are reported)"
        )
    hypotheses = uncovered_hypotheses(missing)
    if hypotheses:
        parts.append(
            "full-run hypotheses that need an absent arm cannot be assessed: "
            + ", ".join(hypotheses)
        )
    if not parts:
        return "No hypothesis depends on them."
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def _runs_title(f: Facts) -> str:
    return "One run per arm"


def _runs_what(f: Facts) -> str:
    repeats = f["scope"]["repeat_records"]
    if repeats:
        return (
            f"Each arm answered each question once for the comparisons; {repeats} repeat "
            "records exist and are not pooled into them."
        )
    return "Each arm answered each question once."


def _runs_effect(f: Facts) -> str:
    return (
        "There is no estimate of run-to-run variation for arms whose pipeline calls a model "
        "(reranking, hypothetical snippets, query rewriting, the agent); the intervals reflect "
        "the sampling of questions only."
    )


def _gold_title(f: Facts) -> str:
    return "Gold error rate (from the hand check)"


def _gold_what(f: Facts) -> str:
    return "Recall is measured against a gold set that a hand check found to contain errors."


def _gold_effect(f: Facts) -> str:
    quality = f.get("gold_quality")
    if not quality:
        return (
            "No hand check of the gold was recorded in this run, so the gold error rate is unknown."
        )
    overall = quality["overall"]
    if overall["rate"] is None:
        return "The hand check scored no item, so the gold error rate is unknown."
    text = (
        f"{overall['k']} of {overall['n']} hand-checked gold answers were marked wrong, an error "
        f"rate of {pct(overall['rate'])} (95% Wilson CI {span_pct(overall['lo'], overall['hi'])}); "
        "recall is measured against a gold set with this error rate."
    )
    ambiguous = len(quality.get("ambiguous_items") or [])
    if ambiguous:
        text += f" {ambiguous} items were marked ambiguous."
    return text


def _generator_title(f: Facts) -> str:
    return "One generator model"


def _generator_what(f: Facts) -> str:
    models = f["scope"]["generator_models"]
    return f"Every answer was generated by {_names(models) if models else 'one model'}."


def _generator_effect(f: Facts) -> str:
    return "Results may not carry over to other generator models."


def _cutoff_title(f: Facts) -> str:
    return f"Pre- and post-cutoff items mixed, {f['scope']['n_post_cutoff']} post-cutoff"


def _cutoff_what(f: Facts) -> str:
    s = f["scope"]
    return (
        f"{s['n_pre_cutoff']} change-set items come from pull requests merged before the "
        f"generator's training cutoff and {s['n_post_cutoff']} from after it."
    )


def _cutoff_effect(f: Facts) -> str:
    s = f["scope"]
    section = f.get("cutoff") or {}
    post = (section.get("groups") or {}).get("post_cutoff")
    text = (
        f"With n = {s['n_post_cutoff']} post-cutoff items the memorisation check is too small "
        "to read."
    )
    if post:
        for arm, cell in post["by_arm"].items():
            if cell:
                text += (
                    f" For {code(arm)} the 95% interval on post-cutoff recall spans "
                    f"{span_pct(cell['lo'], cell['hi'])} points."
                )
                break
    return text


LIMITATIONS: tuple[Limitation, ...] = (
    Limitation(
        "changeset_size",
        _changeset_title,
        _changeset_what,
        _changeset_effect,
        "The full-run design uses a test split of a few hundred change-set items.",
        lambda f: _width_stats(f) | {"n_changeset": f["scope"]["n_changeset"]},
    ),
    Limitation(
        "repositories",
        _repos_title,
        _repos_what,
        _repos_effect,
        "The full-run design uses four to five repositories in four languages, each of "
        "two hundred to three thousand source files.",
        lambda f: {
            "n_repositories": f["scope"]["n_repositories"],
            "n_languages": f["scope"]["n_languages"],
        },
    ),
    Limitation(
        "no_split",
        _split_title,
        _split_what,
        _split_effect,
        "The full-run design uses a frozen test split that is never looked at during tuning.",
        lambda f: {"n_questions": f["scope"]["n_questions"]},
    ),
    Limitation(
        "light_prereg",
        _prereg_title,
        _prereg_what,
        _prereg_effect,
        "The full-run design uses the full pre-registration, including an equivalence test for "
        "the workers arm within a margin of three points of recall.",
        lambda f: {
            "n_comparisons": len(f["comparisons"]),
        },
    ),
    Limitation(
        "small_families",
        _small_title,
        _small_what,
        _small_effect,
        "The full-run design uses at least fifty labelled items per family.",
        lambda f: _judged(f),
    ),
    Limitation(
        "judge",
        _judge_title,
        _judge_what,
        _judge_effect,
        "The full-run design uses a check of one hundred and fifty hand labels per family.",
        lambda f: {
            "n_labels": (f.get("judge_agreement") or {}).get("n", 0),
        },
    ),
    Limitation(
        "arms_not_run",
        _arms_title,
        _arms_what,
        _arms_effect,
        "The full-run design uses the full arm set.",
        lambda f: {"n_missing": len(missing_arms(f["scope"]["arms"]))},
    ),
    Limitation(
        "single_run",
        _runs_title,
        _runs_what,
        _runs_effect,
        "The full-run design uses repeat runs on a variance subset.",
        lambda f: {"repeat_records": f["scope"]["repeat_records"]},
    ),
    Limitation(
        "gold_error",
        _gold_title,
        _gold_what,
        _gold_effect,
        "The full-run design uses larger labelled samples per family under the same labelling "
        "rule.",
        lambda f: (
            {k: v for k, v in f["gold_quality"]["overall"].items() if k != "all_checked"}
            if f.get("gold_quality")
            else {}
        ),
    ),
    Limitation(
        "one_generator",
        _generator_title,
        _generator_what,
        _generator_effect,
        "The full-run design does not address this either; a second generator model is listed "
        "there as future work too.",
        lambda f: {"n_generator_models": f["scope"]["n_generator_models"]},
    ),
    Limitation(
        "cutoff_mix",
        _cutoff_title,
        _cutoff_what,
        _cutoff_effect,
        "The full-run design reports the pre- and post-cutoff split separately.",
        lambda f: {
            "n_post_cutoff": f["scope"]["n_post_cutoff"],
            "n_pre_cutoff": f["scope"]["n_pre_cutoff"],
        },
    ),
)


def build_limitations(facts: Facts) -> list[dict[str, Any]]:
    """Fill every limitation from the report's own data.

    Args:
        facts: The report data assembled so far: ``scope``, ``comparisons`` and the optional
            ``gold_quality``, ``judge_agreement``, ``judge_results`` and ``cutoff`` sections.

    Returns:
        One record per limitation with ``title``, ``what``, ``effect``, ``full_run`` and the
        ``values`` its text prints.
    """
    return [
        {
            "id": row.id,
            "title": row.title(facts),
            "what": row.what(facts),
            "effect": row.effect(facts),
            "full_run": row.full_run,
            "values": row.values(facts),
        }
        for row in LIMITATIONS
    ]


__all__ = [
    "LIMITATIONS",
    "Limitation",
    "build_limitations",
    "missing_arms",
    "uncovered_hypotheses",
]
