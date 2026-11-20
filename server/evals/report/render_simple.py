"""``report.md`` for the default mode, written from the report data.

Every number printed here is read from the data. A section is written only when the data holds it
and a table only when it has rows, so a run with fewer arms or no judge gives a shorter report
rather than one with empty tables. Identifiers are in backticks, which keeps them out of the
numbers a test checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evals.report.fmt import code, md_table, mean_num, mean_usd, num, pct
from evals.report.render import _figure, _section
from evals.report.simple import KINDS, METRIC_TITLE, diff_text

Data = Mapping[str, Any]

COLUMN = {
    "recall": "File recall",
    "precision": "File precision",
    "correctness": "Correctness",
    "faithfulness": "Faithfulness",
    "relevancy": "Answer relevancy",
    "cost": "$ per answer",
    "speed": "Seconds per answer",
    "steps": "Tool steps",
}
JUDGED = ("correctness", "faithfulness", "relevancy")
KIND_TITLE = {"change": "Change questions", "explain": "Explain questions"}


def _cell(metric: str, cell: Mapping[str, Any] | None) -> str:
    if not cell:
        return "n/a"
    if metric == "cost":
        return mean_usd(cell)
    if metric in ("speed", "steps"):
        return mean_num(cell, 1)
    return mean_num(cell, 2)


def _table(table: Mapping[str, Any], metrics: list[str], *, exploratory: bool = False) -> str:
    headers = ["Arm"]
    for metric in metrics:
        title = COLUMN[metric]
        headers.append(title + (" (exploratory)" if exploratory and metric in JUDGED else ""))
        if metric == "recall":
            headers.append("No `Files:` list")
    headers += ["n scored", "Errors"]
    rows = []
    for arm, entry in table["arms"].items():
        row = [code(arm)]
        for metric in metrics:
            row.append(_cell(metric, entry.get(metric)))
            if metric == "recall":
                failures = entry["format_failures"]
                row.append(pct(failures["rate"]) if failures["n"] else "n/a")
        row += [str(entry["n_scored"]), str(entry["n_errors"])]
        rows.append(row)
    return md_table(headers, rows)


# --- sections ---------------------------------------------------------------------------


def render_scope(data: Data) -> str:
    """Repositories, base commits, question counts, models."""
    scope = data["scope"]
    rows = []
    for repo in scope["repositories"]:
        questions = ", ".join(f"{n} {kind}" for kind, n in repo["questions"].items())
        rows.append(
            [
                code(repo["name"]),
                repo.get("era") or "not labelled",
                repo.get("language") or "n/a",
                code(repo["base_commit"][:10]) if repo.get("base_commit") else "n/a",
                questions or "none",
            ]
        )
    headers = ["Repository", "Era", "Language", "Base commit", "Questions"]
    lines = [
        f"- Questions: {scope['n_questions']} in all ("
        + ", ".join(f"{n} {kind}" for kind, n in scope["questions"].items())
        + f"); {scope['n_scored_questions']} are scored here.",
        f"- Arms: {scope['n_arms']} (" + ", ".join(code(a) for a in scope["arms"]) + ").",
        "- Generator: " + (", ".join(code(m) for m in scope["generator_models"]) or "not recorded"),
    ]
    if scope.get("judge_model"):
        versions = ", ".join(scope.get("deepeval_versions") or []) or "not recorded"
        lines.append(f"- Judge: {code(scope['judge_model'])}, DeepEval {versions}.")
    return _section("Scope", md_table(headers, rows), "\n".join(lines))


def render_tables(data: Data) -> str:
    """The overall table and one table per repository."""
    tables = data.get("tables")
    if not tables:
        return ""
    metrics = tables["metrics"]
    exploratory = bool((data.get("judge_check") or {}).get("exploratory"))
    note = (
        "Cells are the mean over questions with a 95% bootstrap interval that resamples questions "
        "(pull request clusters) within each repository. File recall is the share of the "
        "required files named in the answer's `Files:` list; precision and the share of answers "
        "with no list sit beside it. Cost and speed are per answer; tool steps are counted for "
        "arms that use tools. `n scored` counts answers that completed and `Errors` those that "
        "did not; each cell's own n is in `report.json`."
    )
    blocks = [note, _table(tables["overall"], metrics, exploratory=exploratory)]
    not_reached = {
        arm: e["n_not_reached"]
        for arm, e in tables["overall"]["arms"].items()
        if e["n_not_reached"]
    }
    if not_reached:
        blocks.append(
            "Questions an arm did not reach: "
            + ", ".join(f"{code(a)} {n}" for a, n in not_reached.items())
            + "."
        )
    for repo, table in tables["by_repo"].items():
        label = next(
            (r.get("era") for r in data["scope"]["repositories"] if r["name"] == repo), None
        )
        title = f"{code(repo)}" + (f" ({label})" if label else "")
        blocks += [
            f"**{title}**, {table['n_questions']} questions:",
            _table(table, metrics, exploratory=exploratory),
        ]
    return _section("Results", *blocks)


def _comparison_table(data: Data, metric: str) -> str:
    rows_by_pair: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for record in data["comparisons"]:
        if record["metric"] == metric:
            rows_by_pair.setdefault((record["arm_a"], record["arm_b"]), {})[record["scope"]] = (
                record
            )
    if not rows_by_pair:
        return ""
    repos = [r["name"] for r in data["scope"]["repositories"]]
    headers = ["A against B", "n", "Overall", *(code(r) for r in repos)]
    rows = []
    for (a, b), scopes in rows_by_pair.items():

        def cell(scope: str, scopes: dict[str, Mapping[str, Any]] = scopes) -> str:
            r = scopes.get(scope)
            if r is None:
                return "n/a"
            return (
                f"{diff_text(metric, r['estimate'], signed=True)} "
                f"({diff_text(metric, r['ci_lo'])} to {diff_text(metric, r['ci_hi'])}), "
                f"{r['verdict']}"
            )

        overall = scopes.get("overall")
        rows.append(
            [
                f"{code(a)} against {code(b)}",
                str(overall["n"]) if overall else "n/a",
                cell("overall"),
                *(cell(repo) for repo in repos),
            ]
        )
    return f"**{METRIC_TITLE[metric].capitalize()}**, mean difference per question:\n\n" + md_table(
        headers, rows
    )


def render_comparisons(data: Data) -> str:
    """Paired head-to-head rows, overall and per repository."""
    if not data.get("comparisons"):
        return ""
    note = (
        "Each row compares two arms on the same questions: the mean per-question difference "
        "(A minus B) with a 95% bootstrap interval that resamples pull request clusters within "
        "each repository. The verdict names the higher arm only when the interval excludes "
        "zero; otherwise it reads not resolved. For cost, higher means more expensive. The "
        "pairs are the ones fixed in the design freeze; any other pair would be exploratory."
    )
    metrics = ("recall", "correctness", "cost")
    blocks = [note] + [_comparison_table(data, m) for m in metrics]
    sentences = [
        f"- {r['sentence']}"
        for m in metrics
        for r in data["comparisons"]
        if r["metric"] == m and r["scope"] == "overall"
    ]
    if sentences:
        blocks += ["Stated in words, across all repositories:", "\n".join(sentences)]
    return _section("Head-to-head comparisons", *blocks)


def render_by_kind(data: Data) -> str:
    """The overall table split by question kind."""
    tables = data.get("tables")
    if not tables or not tables["by_kind"]:
        return ""
    metrics = tables["metrics"]
    exploratory = bool((data.get("judge_check") or {}).get("exploratory"))
    blocks = []
    for kind in KINDS:
        table = tables["by_kind"].get(kind)
        if table:
            blocks += [
                f"**{KIND_TITLE[kind]}**, {table['n_questions']} questions:",
                _table(table, metrics, exploratory=exploratory),
            ]
    return _section("Change against explain", *blocks)


# --- the codebases ----------------------------------------------------------------------


def _get(entry: Mapping[str, Any], *path: str) -> Any:
    for key in path:
        if not isinstance(entry, Mapping) or key not in entry:
            return None
        entry = entry[key]
    return entry


def _share(entry: Mapping[str, Any], *path: str) -> str | None:
    block = _get(entry, *path)
    if not block or not block.get("n"):
        return None
    return f"{block['k']} of {block['n']} ({pct(block['share'])})"


_STYLE_COLUMNS: tuple[tuple[str, Any], ...] = (
    (
        "Comments and docstrings per function",
        lambda e: _fmt(_get(e, "functions", "doc_lines_per_function"), 2),
    ),
    (
        "Average function length (lines)",
        lambda e: _fmt(_get(e, "functions", "mean_length_lines"), 1),
    ),
    ("Average file length (lines)", lambda e: _fmt(_get(e, "files", "mean_length_lines"), 1)),
    (
        "Average identifier length (characters)",
        lambda e: _fmt(_get(e, "identifiers", "mean_length_chars"), 1),
    ),
    (
        "Median commit message (characters)",
        lambda e: _fmt(_get(e, "commits", "median_message_chars"), 0),
    ),
    (
        "Median PR description (characters)",
        lambda e: _fmt(_get(e, "pull_requests", "median_description_chars"), 0),
    ),
    (
        "Median files changed per PR",
        lambda e: _fmt(_get(e, "pull_requests", "median_files_changed"), 0),
    ),
    ("Commits with visible AI involvement, all", lambda e: _share(e, "ai_involvement", "all")),
    (
        "Commits with visible AI involvement, last 12 months",
        lambda e: _share(e, "ai_involvement", "last_12_months"),
    ),
)


def _fmt(value: float | None, places: int) -> str | None:
    return None if value is None else num(value, places)


def _movement(observations: Mapping[str, Any]) -> str:
    def where(point: Mapping[str, Any]) -> str:
        era = f"{point['era']}, " if point.get("era") else ""
        return f"{code(point['repo'])} ({era}mean {point['mean']:.2f})"

    by_arm: dict[str, list[str]] = {}
    for row in observations["rows"]:
        by_arm.setdefault(row["arm"], []).append(
            f"{METRIC_TITLE[row['metric']]} was highest on {where(row['highest'])} and lowest on "
            f"{where(row['lowest'])}"
        )
    lines = [f"- {code(arm)}: " + "; ".join(parts) + "." for arm, parts in by_arm.items()]
    leaders = observations["recall_leaders"]
    n = observations["n_repositories"]
    if len(set(leaders.values())) == 1 and len(leaders) == n:
        leader = next(iter(leaders.values()))
        lead = f"{code(leader)} had the highest mean file recall on all {n} repositories."
    else:
        lead = (
            "The arm with the highest mean file recall was "
            + ", ".join(f"{code(arm)} on {code(repo)}" for repo, arm in leaders.items())
            + "."
        )
    closing = (
        f"These are observations on {n} repositories; this report does not test why results "
        "differ between them."
    )
    return "\n".join(
        [
            "How each arm's results move across the repositories (means from the tables above):",
            "",
            *lines,
            "",
            f"{lead} {closing}",
        ]
    )


def render_style(data: Data) -> str:
    """The codebase measurements beside a description of how arms move across repositories."""
    style = data.get("style")
    if not style:
        return ""
    eras = {r["name"]: r.get("era") for r in data["scope"]["repositories"]}
    entries = style["repos"]
    columns = [
        (title, read)
        for title, read in _STYLE_COLUMNS
        if any(read(entry) is not None for entry in entries.values())
    ]
    rows = [
        [code(repo) + (f" ({eras[repo]})" if eras.get(repo) else "")]
        + [read(entry) or "n/a" for _, read in columns]
        for repo, entry in entries.items()
    ]
    note = (
        "Measured at each repository's base commit. Comments are counted from each function's "
        "source with a line-comment heuristic, plus its docstring; commit messages are the whole "
        "message of non-merge commits; PR figures come from the pull requests ingested as "
        "history. Visible AI involvement is a lower bound: a commit counts only when it has a "
        "`Co-Authored-By` trailer naming an AI tool or an AI bot as its author, and says nothing "
        "about code written with AI help that left no such trace."
    )
    blocks = [note, md_table(["Repository", *(t for t, _ in columns)], rows)]
    observations = data.get("observations")
    if observations:
        blocks.append(_movement(observations))
    return _section("How the codebases differ", *blocks)


def render_cost_quality(data: Data) -> str:
    """Dollars per answer against correctness."""
    section = data.get("cost_quality")
    if not section:
        return ""
    rows = [
        [
            code(p["arm"]),
            f"${p['cost_per_answer']:.4f}",
            num(p["correctness"], 2),
            str(p["n"]),
            "yes" if p["on_frontier"] else "no",
        ]
        for p in section["points"]
    ]
    return _section(
        "Cost against quality",
        _figure(data, "cost_quality", "Dollars per answer against mean correctness, by arm"),
        "Mean cost and mean correctness over all scored questions; an arm is on the frontier "
        "when no other arm is both cheaper and more correct.",
        md_table(["Arm", "$ per answer", "Correctness", "n judged", "On frontier"], rows),
    )


def render_judge_check(data: Data) -> str:
    """Agreement with the hand-scored answers."""
    check = data.get("judge_check")
    if not check:
        return ""
    if not check["done"]:
        return _section(
            "Judge check",
            "The judge has not yet been checked against hand-scored answers; the judged "
            "columns are unvalidated.",
        )
    rows = [
        [
            e["dimension"],
            str(e["n"]),
            "n/a" if e["agreement"] is None else pct(e["agreement"]),
            "n/a"
            if e["kappa"] is None
            else f"{num(e['kappa'])} ({num(e['lo'])} to {num(e['hi'])})",
        ]
        for e in check["entries"]
    ]
    status = (
        f"{check['n']} hand-scored answers were compared with the judge's scores, binned to "
        f"the same labels; the check needs at least {check['minimum']}"
        + (" and has them." if check["meets_minimum"] else " and falls short.")
    )
    if check["exploratory"]:
        status += " Agreement is poor, so the judged columns are labelled exploratory."
    return _section(
        "Judge check",
        status,
        md_table(["Label", "n", "Exact agreement", "Weighted kappa (95% CI)"], rows),
    )


def render_limitations(data: Data) -> str:
    """The run's limitations, from the data."""
    items = data.get("limitations")
    if not items:
        return ""
    return _section("Limitations", "\n".join(f"- {item['text']}" for item in items))


_ORDER = (
    render_scope,
    render_tables,
    render_comparisons,
    render_by_kind,
    render_style,
    render_cost_quality,
    render_judge_check,
    render_limitations,
)


def render_simple_markdown(data: Data) -> str:
    """The whole default ``report.md``.

    Args:
        data: The report data.

    Returns:
        The markdown text, ending in a newline.
    """
    parts = ["# Evaluation report\n"]
    for render in _ORDER:
        text = render(data)
        if text:
            parts.append(text)
    return "\n".join(parts).rstrip() + "\n"


__all__ = ["render_simple_markdown"]
