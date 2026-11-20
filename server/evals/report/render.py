"""``report.md`` from ``report.json``: every number printed here is read from the data.

A section is rendered only when the data holds it, and a table only when it has rows, so a report
for fewer arms is shorter rather than padded with empty tables. Identifiers (arm names, items) are
in backticks, which keeps them out of the numbers a test checks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evals.report.fmt import (
    code,
    md_table,
    mean_num,
    mean_pct,
    mean_usd,
    num,
    pct,
    rate,
    span_pct,
    usd,
)
from evals.report.wording import METRICS, unit_text, value_text

Data = Mapping[str, Any]

FAMILY_LABEL = {
    "primary": "primary",
    "secondary": "secondary",
    "main": "main",
    "equivalence": "equivalence (own family)",
}
VERDICT_LABEL = {
    "supported": "supported",
    "not_supported": "not supported",
    "difference": "difference found",
    "no_difference": "no difference found",
    "equivalent": "equivalent within the margin",
    "not_equivalent": "equivalence not shown",
}
DIRECTION_LABEL = {
    "greater": "first arm higher",
    "less": "first arm lower",
    "two-sided": "two-sided",
}


def _section(title: str, *blocks: str) -> str:
    body = "\n\n".join(b for b in blocks if b)
    return f"## {title}\n\n{body}\n" if body else ""


def _figure(data: Data, name: str, alt: str) -> str:
    figure = (data.get("figures") or {}).get(name)
    return f"![{alt}]({figure['path']})" if figure else ""


# --- headline pieces --------------------------------------------------------------------


def render_findings(data: Data) -> str:
    """The pilot's findings summary and scope statement."""
    findings = data.get("findings")
    if not findings:
        return ""
    scope = "\n\n".join(data["scope_lines"])
    bullets = "\n".join(f"- {f['text']}" for f in findings)
    return _section("Findings summary", scope, bullets)


def _estimate_cell(c: Mapping[str, Any]) -> str:
    if c["kind"] in ("cost_multiple", "ratio_floor", "ratio_ceiling"):
        return f"ratio {num(c['estimate'])} ({num(c['ci_lo'])} to {num(c['ci_hi'])})"
    metric = c["metric"]
    return (
        f"{value_text(metric, c['estimate'], signed=True)}{unit_text(metric)} "
        f"({value_text(metric, c['ci_lo'])} to {value_text(metric, c['ci_hi'])})"
    )


def _p(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def render_comparisons(data: Data) -> str:
    """The pre-registered comparisons: a table, then one sentence per comparison."""
    comparisons = data.get("comparisons")
    if not comparisons:
        return ""
    pilot = data["mode"] == "pilot"
    headers = [
        "Id",
        "Family",
        "First arm",
        "Second arm",
        "Metric",
        "Direction",
        "Estimate (95% CI)",
        "n (clusters)",
        "p",
        "p (Holm)",
    ]
    if pilot:
        headers.append("MDD")
    headers += ["Result", "Leading arm per repository"]
    rows = []
    for c in comparisons:
        row = [
            f"**{c['id']}**" if c["headline"] else c["id"],
            FAMILY_LABEL[c["family"]],
            code(c["arm_a"]),
            code(c["arm_b"]),
            c["metric_title"],
            DIRECTION_LABEL[c["alternative"]],
            _estimate_cell(c),
            f"{c['n']} ({c['n_clusters']})",
            _p(c.get("p_raw")),
            _p(c.get("p_adjusted")),
        ]
        if pilot:
            mdd = c.get("mdd")
            row.append(
                "n/a" if mdd is None else f"{value_text(c['metric'], mdd)}{unit_text(c['metric'])}"
            )
        direction = c.get("direction")
        lead = (
            f"first {direction['a_ahead']}, second {direction['b_ahead']}, tied {direction['tied']}"
            if direction
            else "n/a"
        )
        row += [VERDICT_LABEL[c["verdict"]], lead]
        rows.append(row)
    sentences = "\n".join(
        f"- **{c['id']}** ({code(c['arm_a'])} vs {code(c['arm_b'])}): {c['sentence']}"
        for c in comparisons
    )
    notes = [_family_note(comparisons), *_extra_lines(comparisons)]
    title = "Pre-registered comparisons" if pilot else "Hypotheses"
    return _section(title, md_table(headers, rows), sentences, "\n\n".join(n for n in notes if n))


def _family_note(comparisons: Sequence[Mapping[str, Any]]) -> str:
    seen: dict[str, Mapping[str, Any]] = {}
    for c in comparisons:
        seen.setdefault(c["family"], c)
    lines = []
    for family, c in seen.items():
        if family == "equivalence":
            continue
        lines.append(
            f"Holm correction within the {FAMILY_LABEL[family]} family covers "
            f"{c['family_size_run']} of {c['family_size_planned']} planned tests "
            "(tests whose arms were not run are left out)."
        )
    return " ".join(lines)


def _extra_lines(comparisons: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = []
    for c in comparisons:
        gap = c.get("gap")
        if gap:
            share = gap.get("share_closed")
            cost = gap.get("cost_fraction")
            parts = []
            if share:
                parts.append(
                    f"closes {pct(share['estimate'])} of the gap from {code(gap['baseline'])} to "
                    f"{code(gap['reference'])} (95% CI {span_pct(share['lo'], share['hi'])}, "
                    f"n = {gap['share_n']})"
                )
            if cost:
                parts.append(
                    f"costs {pct(cost['estimate'])} of {code(gap['reference'])}'s cost per "
                    f"question (95% CI {span_pct(cost['lo'], cost['hi'])}, criterion under "
                    f"{pct(cost['criterion'])}, n = {gap['cost_n']})"
                )
            if parts:
                lines.append(f"**{c['id']}**: {code(c['arm_a'])} " + " and ".join(parts) + ".")
        tost = c.get("tost")
        if tost:
            lines.append(
                f"**{c['id']}** equivalence (TOST, margin ±{num(tost['margin'])}): p = "
                f"{_p(tost['p_value'])}, n = {c['n']}."
            )
    return lines


# --- context ----------------------------------------------------------------------------


def render_corpus(data: Data) -> str:
    """The corpus table."""
    corpus = data.get("corpus")
    if not corpus:
        return ""
    headers = [
        "Repository",
        "Language",
        "Files",
        "Symbols",
        "Edges",
        "Commits",
        "PRs",
        "Co-change pairs",
        "Questions",
    ]
    rows = []
    for name, c in corpus["repos"].items():
        questions = ", ".join(f"{n} {f}" for f, n in c.get("questions", {}).items())
        rows.append(
            [
                code(name),
                c.get("language") or "n/a",
                str(c["files"]),
                str(c["symbols"]),
                str(c["edges"]),
                str(c["commits"]),
                str(c["prs"]),
                str(c["cochange_pairs"]),
                questions or "n/a",
            ]
        )
    return _section("Corpus", md_table(headers, rows))


def render_gold_quality(data: Data) -> str:
    """The gold error rate per family."""
    quality = data.get("gold_quality")
    if not quality:
        return ""
    headers = [
        "Family",
        "Items",
        "Hand-checked",
        "Ambiguous",
        "Wrong",
        "Error rate (95% Wilson CI)",
    ]
    rows = []
    for family, f in quality["families"].items():
        rows.append(
            [
                family,
                str(f["n_items"]),
                str(f["n_labelled"]),
                str(f["n_ambiguous"]),
                str(f["n_wrong"]),
                rate({"n": f["n_scored"], "rate": f["rate"], "lo": f["lo"], "hi": f["hi"]}),
            ]
        )
    overall = quality["overall"]
    checked = (
        f"All {overall['n_items']} gold items were hand-checked."
        if overall["all_checked"]
        else f"{overall['n_labelled']} of {overall['n_items']} gold items were hand-checked."
    )
    pooled = f"Pooled error rate {rate(overall)}, n = {overall['n']} scored items."
    listed = ""
    if quality["ambiguous_items"]:
        listed = (
            "Items marked ambiguous: "
            + ", ".join(code(i) for i in quality["ambiguous_items"])
            + "."
        )
    return _section("Gold quality", checked, md_table(headers, rows), pooled, listed)


# --- results ----------------------------------------------------------------------------


def render_main(data: Data) -> str:
    """Answer recall and precision by arm, with and without test files."""
    main = data.get("main_results")
    if not main:
        return ""
    headers = [
        "Arm",
        "n scored",
        "Recall",
        "Precision",
        "Recall, no test files",
        "Precision, no test files",
        "Format failures",
        "Errors",
        "Not reached",
    ]
    rows = []
    for arm, r in main["by_arm"].items():
        rows.append(
            [
                code(arm),
                f"{r['n_ok']} of {r['n_total']}",
                mean_pct(r["recall"]),
                mean_pct(r["precision"]),
                mean_pct(r["recall_nt"]),
                mean_pct(r["precision_nt"]),
                rate(r["format_failures"]),
                f"{r['n_errors']} ({rate(r['error_rate'])})",
                str(r["n_not_reached"]),
            ]
        )
    blocks = [
        "Change-set answer file recall and precision, from the `Files:` list each answer ends "
        "with. Recall counts every gold file, test files included; the no-test columns drop "
        "test files from the gold and from the list. Cells are the mean with its 95% cluster "
        "bootstrap interval; rates carry Wilson intervals.",
        md_table(headers, rows),
    ]
    templates = main.get("by_template") or {}
    if templates:
        arms = list(main["by_arm"])
        t_headers = ["Arm", *templates]
        t_rows = [
            [code(arm), *(mean_pct(templates[t].get(arm)) for t in templates)] for arm in arms
        ]
        blocks += ["Recall by question template:", md_table(t_headers, t_rows)]
    return _section("Main results", *blocks)


def render_retrieval(data: Data) -> str:
    """Recall, MRR and nDCG of the retrieval pool."""
    section = data.get("retrieval")
    if not section:
        return ""
    ks = section["ks"]
    headers = ["Arm"] + [f"Recall@{k}" for k in ks] + ["MRR"] + [f"nDCG@{k}" for k in ks]
    rows = []
    for arm, r in section["by_arm"].items():
        rows.append(
            [
                code(arm),
                *(mean_pct(r["recall"][str(k)]) for k in ks),
                mean_num(r["mrr"], 3),
                *(mean_num(r["ndcg"][str(k)], 3) for k in ks),
            ]
        )
    intro = "File-level retrieval on each single-shot arm's pool, over the change-set items."
    return _section("Retrieval", intro, md_table(headers, rows))


def _exploratory_rows(rows: Sequence[Mapping[str, Any]], label: str) -> list[list[str]]:
    out = []
    for r in rows:
        metric = r["metric"]
        out.append(
            [
                label_for(r, label),
                METRICS[metric].title,
                f"{value_text(metric, r['estimate'], signed=True)}{unit_text(metric)}",
                f"{value_text(metric, r['ci_lo'])} to {value_text(metric, r['ci_hi'])}",
                f"{r['n']} ({r['n_clusters']})",
                _p(r["p_raw"]),
            ]
        )
    return out


def label_for(row: Mapping[str, Any], label: str) -> str:
    """The first column of an exploratory row."""
    text = f"{code(row['arm_a'])} vs {code(row['arm_b'])}"
    if row.get("preregistered_id"):
        text += f" ({row['preregistered_id']})"
    return text


def render_ablation(data: Data) -> str:
    """The channel ablation."""
    section = data.get("ablation")
    if not section:
        return ""
    headers = [
        "Comparison",
        "Metric",
        "Difference",
        "95% CI",
        "n (clusters)",
        "p (two-sided, unadjusted)",
    ]
    rows = _exploratory_rows(section["rows"], "ablation")
    intro = (
        f"{code(section['base'])} against each variant with one channel removed. A positive "
        "difference means the channel helps. Exploratory unless a pre-registered id is shown."
    )
    return _section(
        "Channel ablation",
        intro,
        md_table(headers, rows),
        _figure(data, "ablation", "Recall lost when a channel is removed"),
    )


def render_rerankers(data: Data) -> str:
    """The reranker comparisons."""
    section = data.get("rerankers")
    if not section:
        return ""
    headers = [
        "Comparison",
        "Metric",
        "Difference",
        "95% CI",
        "n (clusters)",
        "p (two-sided, unadjusted)",
    ]
    rows = _exploratory_rows(section["rows"], "rerank")
    intro = "Reranked arms against the arm they differ from by the reranker alone."
    return _section("Rerankers", intro, md_table(headers, rows))


def render_trajectory(data: Data) -> str:
    """Agent trajectory metrics."""
    section = data.get("trajectory")
    if not section:
        return ""
    headers = [
        "Arm",
        "Runs",
        "Steps to first changed file (censored)",
        "Median steps when reached",
        "Never reached",
        "Wasted reads",
    ]
    rows = []
    blocks: list[str] = []
    for arm, t in section["by_arm"].items():
        median_steps = t["steps_reached_median"]
        rows.append(
            [
                code(arm),
                f"{t['n_runs']} of {t['n_items']}" + (" (subset)" if t["ran_on_subset"] else ""),
                mean_num(t["steps"], 1),
                "n/a" if median_steps is None else num(median_steps, 1),
                rate(t["never_reached"]),
                mean_pct(t["wasted_reads"]),
            ]
        )
        tools = ", ".join(f"{name} {count}" for name, count in t["tool_calls"].items())
        stops = ", ".join(f"{name} {count}" for name, count in t["stop_reasons"].items())
        blocks.append(
            f"{code(arm)}: tool calls: {tools or 'none'}; stop reasons: {stops or 'none'}."
        )
        overlap = t.get("worker_overlap")
        if overlap and overlap["mean_jaccard"] is not None:
            blocks.append(
                f"{code(arm)}: mean Jaccard overlap between workers' touched files "
                f"{num(overlap['mean_jaccard'])} (n = {overlap['n']} runs)."
            )
    intro = (
        "Steps are counted to the first step that touches a required gold file; a run that "
        "never reaches one is censored at its own step count."
    )
    return _section(
        "Agent trajectories",
        intro,
        md_table(headers, rows),
        "\n\n".join(blocks),
        _figure(data, "steps_to_gold", "Runs that have reached a changed file, by step"),
    )


def render_cost(data: Data) -> str:
    """Cost, tokens and latency."""
    section = data.get("cost")
    if not section:
        return ""
    headers = [
        "Arm",
        "n",
        "Dollars per question",
        "Dollars per correct answer",
        "Input tokens per question",
        "Output tokens per question",
        "Latency p50 (s)",
        "Latency p95 (s)",
    ]
    rows = []
    for arm, c in section["by_arm"].items():
        per_correct = c["per_correct_usd"]
        rows.append(
            [
                code(arm),
                str(c["n"]),
                mean_usd(c["per_question"]),
                "n/a" if per_correct is None else f"{usd(per_correct)} ({c['n_correct']} correct)",
                num(c["tokens"]["input_per_question"], 0),
                num(c["tokens"]["output_per_question"], 0),
                num(c["latency_p50_s"], 1),
                num(c["latency_p95_s"], 1),
            ]
        )
    intro = (
        "From metered usage. A correct answer lists every required file. Total recorded spend "
        f"on generations and routing decisions in this run: {usd(section['run_spend_usd'], 2)}."
    )
    return _section("Cost", intro, md_table(headers, rows))


def render_pareto(data: Data) -> str:
    """The Pareto frontier."""
    section = data.get("pareto")
    if not section:
        return ""
    headers = ["Arm", "Dollars per question", "Recall", "n", "On the frontier"]
    rows = [
        [
            code(p["arm"]),
            usd(p["cost_per_question"]),
            pct(p["recall"]),
            str(p["n"]),
            "yes" if p["on_frontier"] else "no",
        ]
        for p in section["points"]
    ]
    auto = section.get("auto_on_frontier")
    note = ""
    if auto is not None:
        note = "`auto` is on the frontier." if auto else "`auto` is not on the frontier."
    return _section(
        "Pareto frontier",
        "Dollars per question against answer file recall over every arm; descriptive.",
        md_table(headers, rows),
        note,
        _figure(data, "pareto", "Cost against answer file recall"),
    )


def render_routing(data: Data) -> str:
    """The routing summary for ``auto``."""
    section = data.get("routing")
    if not section:
        return ""
    routes = md_table(
        ["Route", "Share (95% Wilson CI)", "n"],
        [[code(k), rate(v), str(v["k"])] for k, v in section["routes"].items()],
    )
    targets = md_table(
        ["Arm run", "Share (95% Wilson CI)", "n"],
        [[code(k), rate(v), str(v["k"])] for k, v in section["targets"].items()],
    )
    fallbacks = md_table(
        ["Fallback reason", "Share (95% Wilson CI)", "n"],
        [[k, rate(v), str(v["k"])] for k, v in section["fallbacks"].items()],
    )
    comparison = md_table(
        ["Arm", "Mean recall", "Mean dollars per question", "n"],
        [
            [
                code(c["arm"]),
                "n/a" if c["mean_recall"] is None else pct(c["mean_recall"]),
                "n/a" if c["mean_cost_usd"] is None else usd(c["mean_cost_usd"]),
                str(c["n"]),
            ]
            for c in section["comparison"]
        ],
    )
    arms = section["confusion_arms"]
    cells = {(r["picked"], r["best"]): r["count"] for r in section["confusion"]}
    confusion = md_table(
        ["Picked \\ best", *(code(a) for a in arms)],
        [[code(p), *(str(cells.get((p, b), 0)) for b in arms)] for p in arms],
    )
    blocks = [
        f"{section['n']} routing decisions; {section['fallback_count']} fell back "
        f"({rate(section['fallback_rate'])}). Decisions cost "
        f"{usd(section['decision_cost_usd'], 6)} "
        "in all.",
        "Route distribution:",
        routes,
        "Arm actually run:",
        targets,
    ]
    if fallbacks:
        blocks += ["Fallbacks:", fallbacks]
    if comparison:
        blocks += [
            "`auto` against one fixed arm for every question, on the items all of them share:",
            comparison,
        ]
    if confusion:
        agreement = section["agreement"]
        blocks += [
            "Arm picked (rows) against the arm that did best on the item (columns); ties go to "
            "the cheaper arm.",
            confusion,
            f"The picked arm was the best one on {rate(agreement)} of {agreement['n']} items.",
        ]
    return _section("Routing", *blocks)


def render_drift(data: Data) -> str:
    """Recall by drift bucket."""
    section = data.get("drift")
    if not section:
        return ""
    buckets = section["buckets"]
    arms = list(buckets[0]["by_arm"])
    headers = ["Arm", *(f"{b['lo']} to {b['hi']} merges (n = {b['n_items']})" for b in buckets)]
    rows = [[code(a), *(mean_pct(b["by_arm"].get(a)) for b in buckets)] for a in arms]
    intro = "Answer recall by how many merges after the base commit the pull request landed."
    return _section(
        "Drift", intro, md_table(headers, rows), _figure(data, "drift", "Recall by drift bucket")
    )


def render_cutoff(data: Data) -> str:
    """Recall before and after the generator's cutoff."""
    section = data.get("cutoff")
    if not section:
        return ""
    groups = section["groups"]
    names = {"pre_cutoff": "Before the cutoff", "post_cutoff": "After the cutoff"}
    arms = list(next(iter(groups.values()))["by_arm"])
    headers = ["Arm", *(f"{names[g]} (n = {v['n_items']})" for g, v in groups.items())]
    rows = [[code(a), *(mean_pct(v["by_arm"].get(a)) for v in groups.values())] for a in arms]
    intro = (
        "Answer recall for pull requests merged before and after the generator's training cutoff."
    )
    return _section("Memorisation check", intro, md_table(headers, rows))


def _judge_table(block: Mapping[str, Any]) -> str:
    headers = ["Arm", "n", "Correct (0 to 3)", "Faithful (0 to 3)", "Abstained"]
    rows = [
        [
            code(arm),
            str(r["n"]),
            mean_num(r["correct"]),
            mean_num(r["faithful"]),
            rate(r["abstained"]),
        ]
        for arm, r in block["by_arm"].items()
    ]
    return md_table(headers, rows)


def render_judge(data: Data) -> str:
    """Judge grades, descriptive."""
    section = data.get("judge_results")
    if not section:
        return ""
    blocks: list[str] = [
        "Graded by one judge; descriptive only, with no hypothesis test. Cells are means with "
        "95% intervals."
    ]
    for family, block in section["descriptive"].items():
        flag = " (exploratory: judge agreement below the cut-off)" if block["exploratory"] else ""
        blocks += [f"**{family}**, {block['n_judged']} judged answers{flag}:", _judge_table(block)]
    sanity = section["structural_sanity"]
    for family, block in sanity.items():
        blocks += [
            f"**{family}** questions are a sanity class (can the graph tools answer graph "
            f"questions), circular by design and never part of a headline comparison; "
            f"{block['n_judged']} judged answers:",
            _judge_table(block),
        ]
    return _section("Judged results", *blocks)


def render_judge_agreement(data: Data) -> str:
    """Weighted kappa per family."""
    section = data.get("judge_agreement")
    if not section:
        return ""
    headers = ["Family", "Dimension", "n", "Exact agreement", "Weighted kappa (95% CI)", "Reading"]
    rows = []
    for e in section["entries"]:
        kappa = (
            "n/a" if e["kappa"] is None else f"{num(e['kappa'])} ({num(e['lo'])} to {num(e['hi'])})"
        )
        rows.append(
            [
                e["family"],
                e["dimension"],
                str(e["n"]),
                "n/a" if e["agreement"] is None else pct(e["agreement"]),
                kappa,
                "exploratory" if e["exploratory"] else "usable",
            ]
        )
    note = (
        f"{section['n']} hand-labelled answers compared; the check needs at least "
        f"{section['minimum']}"
        + (" and has them." if section["meets_minimum"] else " and falls short.")
    )
    return _section("Judge agreement", note, md_table(headers, rows))


def render_exclusions(data: Data) -> str:
    """Error records and items an arm did not reach."""
    section = data.get("exclusions")
    if not section:
        return ""
    blocks = []
    errors = section["errors"]
    if errors:
        shown = errors[:50]
        blocks.append(
            md_table(
                ["Arm", "Item", "Reason"],
                [
                    [code(e["arm"]), code(e["item_id"]), e["reason"].replace("|", "/")]
                    for e in shown
                ],
            )
        )
        if len(errors) > len(shown):
            blocks.append(f"{len(errors) - len(shown)} more error records are in report.json.")
    reached = section["not_reached"]
    if reached:
        blocks.append(
            md_table(
                ["Arm", "Items not reached"],
                [[code(arm), str(len(ids))] for arm, ids in reached.items()],
            )
        )
    flagged = section["flagged"]
    if flagged:
        blocks.append(
            md_table(
                ["Arm", "Flagged runs", "Unavailable tool results"],
                [
                    [code(arm), str(v["flagged"]), str(v["unavailable_tool_results"])]
                    for arm, v in flagged.items()
                ],
            )
        )
    intro = (
        "An error record is excluded from every paired comparison involving its arm, never "
        "scored as zero. Items an arm did not reach are excluded the same way; nothing is "
        "imputed."
    )
    return _section("Exclusions", intro, *blocks)


def render_limitations(data: Data) -> str:
    """The pilot's limitations."""
    rows = data.get("limitations")
    if not rows:
        return ""
    blocks = []
    for row in rows:
        blocks.append(
            f"### {row['title']}\n\n"
            f"- **What it is.** {row['what']}\n"
            f"- **Effect on this report.** {row['effect']}\n"
            f"- **How the full-run design addresses it.** {row['full_run']}"
        )
    return _section("Limitations", *blocks)


def render_run(data: Data) -> str:
    """What produced the numbers."""
    run = data["run"]
    lines = [
        f"- Mode: {data['mode']}; slice: {code(run['slice'] or 'unknown')}.",
        "- Generator: " + (", ".join(code(m) for m in run["generator_models"]) or "not recorded"),
    ]
    if run.get("judge_model"):
        lines.append(f"- Judge: {code(run['judge_model'])}")
    lines.append("- The run's manifest is copied beside this report as `manifest.json`.")
    return _section("Run", "\n".join(lines))


# --- the whole document -----------------------------------------------------------------

_ORDER = (
    render_findings,
    render_comparisons,
    render_run,
    render_corpus,
    render_gold_quality,
    render_main,
    render_retrieval,
    render_ablation,
    render_rerankers,
    render_trajectory,
    render_cost,
    render_pareto,
    render_routing,
    render_drift,
    render_cutoff,
    render_judge,
    render_judge_agreement,
    render_exclusions,
    render_limitations,
)


def render_markdown(data: Data) -> str:
    """The whole ``report.md``.

    Args:
        data: The report data.

    Returns:
        The markdown text, ending in a newline.
    """
    title = "Pilot report" if data["mode"] == "pilot" else "Evaluation report"
    parts = [f"# {title}\n"]
    for render in _ORDER:
        text = render(data)
        if text:
            parts.append(text)
    return "\n".join(parts).rstrip() + "\n"


__all__ = ["render_markdown"]
