"""``build_report``: a run directory in, ``report.json``, ``report.md``, figures and a manifest out.

``report.json`` is the source of truth and ``report.md`` is rendered from it. The builder refuses
to run when any self-test case fails, leaves out a section whose arms or data are absent, and
checks its own prose against the wording rules before writing anything.
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals import selftest_registry
from evals.manifest import MANIFEST_NAME
from evals.metrics.answer import scored_gold
from evals.metrics.trajectory import shortest_path_nodes, touched_files
from evals.report import compute
from evals.report.comparisons import PILOT_COMPARISONS, StatConfig, run_comparisons
from evals.report.figures import make_figures
from evals.report.limitations import build_limitations
from evals.report.load import RunData, load_run
from evals.report.render import render_markdown
from evals.report.render_simple import render_simple_markdown
from evals.report.scores import Scores
from evals.report.simple import QUESTION_COLUMNS, assemble_simple, question_rows
from evals.report.summary import scope_lines, select_findings
from evals.report.wording import check_wording

SCHEMA = 1
TRAJECTORY_GRAPH = "trajectory_graph.json"


class ReportError(RuntimeError):
    """The report cannot be built, or would break its own rules."""


@dataclass
class Report:
    """A built report.

    Attributes:
        data: The contents of ``report.json``.
        markdown: The contents of ``report.md``.
        out_dir: Where the files were written.
        paths: The files written, by name.
    """

    data: dict[str, Any]
    markdown: str
    out_dir: Path
    paths: dict[str, Path] = field(default_factory=dict)


def run_selftest() -> None:
    """Run every registered self-test case.

    Raises:
        ReportError: If any case fails, naming each.
    """
    import evals.metrics.selftest  # noqa: F401  # registers the metric cases
    import evals.stats_selftest  # noqa: F401  # registers the statistics cases

    _, failed = selftest_registry.run_all()
    if failed:
        listing = "; ".join(f"{name}: {message}" for name, message in failed)
        raise ReportError(f"the self-test fails, so no report is built: {listing}")


def _trajectory_graph(data: RunData, scores: Scores, arms: list[str]) -> dict[str, Any] | None:
    """One agent run's touched files, the import edges among them and the shortest paths."""
    best: tuple[int, str, Any] | None = None
    by_id = {i.id: i for i in scores.items}
    for arm in compute.agent_arms(arms):
        for row in scores.ok_rows(arm):
            item = by_id[row.item_id]
            if not row.generation.steps or item.repo not in data.graph:
                continue
            size = len(touched_files(row.generation.steps))
            candidate = (size, row.item_id, (arm, item, row))
            if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
                best = candidate
    if best is None:
        return None
    arm, item, row = best[2]
    adjacency = data.graph[item.repo]
    gold = sorted(scored_gold(item))
    from evals.metrics.trajectory import seed_files

    seeds = sorted(seed_files(row.generation.steps))
    touched = sorted(touched_files(row.generation.steps))
    paths = []
    on_path: set[str] = set()
    for seed in seeds:
        for target in gold:
            nodes = shortest_path_nodes(adjacency, seed, target)
            if nodes:
                paths.append({"from": seed, "to": target, "nodes": sorted(nodes)})
                on_path |= nodes
    nodes_all = sorted(set(touched) | set(gold) | on_path)
    members = set(nodes_all)
    edges = sorted(
        [a, b] for a in nodes_all for b in adjacency.get(a, ()) if b in members and a != b
    )
    return {
        "item_id": item.id,
        "repo": item.repo,
        "arm": arm,
        "gold_files": gold,
        "seed_files": seeds,
        "touched_files": touched,
        "nodes": nodes_all,
        "edges": edges,
        "paths": paths,
    }


def _preregistered_pairs(mode: str) -> dict[tuple[str, str], str]:
    if mode != "pilot":
        return {}
    return {(s.arm_a, s.arm_b): s.id for s in PILOT_COMPARISONS if s.metric == "recall"}


def assemble(data: RunData, *, mode: str, config: StatConfig) -> dict[str, Any]:
    """Compute every section of the report from a loaded run.

    Args:
        data: The loaded run.
        mode: ``pilot`` or ``full``.
        config: Resampling sizes and seed.

    Returns:
        The report data, without figures' files or rendered text.
    """
    from evals.arms import ARMS

    scores = Scores.build(data)
    arms_all = [a for a in ARMS if any(g.arm == a for g in data.generations)]
    arms_all += sorted({g.arm for g in data.generations if g.arm not in ARMS})
    arms = scores.arms()

    report: dict[str, Any] = {"schema": SCHEMA, "mode": mode}
    report["scope"] = compute.scope_section(data, scores, arms_all, mode)
    judge_model = (data.judge_manifest or {}).get("models", {}).get("judge")
    report["run"] = {
        "name": data.name,
        "slice": data.slice_name,
        "generator_models": report["scope"]["generator_models"],
        "judge_model": judge_model,
        "judge_slug": data.judge_slug,
        "notes": list(data.notes),
    }

    optional: dict[str, Any] = {
        "corpus": compute.corpus_section(data),
        "gold_quality": compute.gold_quality_section(data),
    }
    if scores.items and arms:
        main = compute.main_results_section(scores, arms, config)
        cost = compute.cost_section(scores, arms, config, compute.total_spend(data))
        optional |= {
            "main_results": main,
            "retrieval": compute.retrieval_section(scores, arms, config),
            "ablation": compute.ablation_section(scores, arms, config),
            "rerankers": compute.rerankers_section(
                scores, arms, config, _preregistered_pairs(mode)
            ),
            "trajectory": compute.trajectory_section(data, scores, arms, config),
            "cost": cost,
            "pareto": compute.pareto_section(scores, arms, cost, main),
            "routing": compute.routing_section(data, scores),
            "drift": compute.drift_section(scores, arms, config),
            "cutoff": compute.cutoff_section(scores, arms, config),
            "exclusions": compute.exclusions_section(scores, arms),
        }
    agreement = compute.judge_agreement_section(data, config)
    optional["judge_agreement"] = agreement
    flagged = set((agreement or {}).get("exploratory_families") or [])
    optional["judge_results"] = compute.judge_results_section(data, arms_all, config, flagged)
    for name, value in optional.items():
        if value:
            report[name] = value

    comparisons = (
        run_comparisons(
            mode,
            scores.refs,
            scores.get,
            arms,
            config,
            repositories=report["scope"]["n_repositories"],
        )
        if scores.items
        else []
    )
    if comparisons:
        report["comparisons"] = comparisons
    if mode == "pilot":
        report["scope_lines"] = scope_lines(report["scope"])
        findings = select_findings(comparisons)
        if findings:
            report["findings"] = findings
        facts = {**report, "comparisons": comparisons}
        report["limitations"] = build_limitations(facts)
    report["sections"] = [
        name
        for name in (
            "findings",
            "comparisons",
            "corpus",
            "gold_quality",
            "main_results",
            "retrieval",
            "ablation",
            "rerankers",
            "trajectory",
            "cost",
            "pareto",
            "routing",
            "drift",
            "cutoff",
            "judge_results",
            "judge_agreement",
            "exclusions",
            "limitations",
        )
        if name in report
    ]
    report["_graph"] = _trajectory_graph(data, scores, arms)
    return report


MODES = ("simple", "full", "pilot")
DEFAULT_MODE = "simple"


QUESTIONS_JSONL = "questions.jsonl"
QUESTIONS_CSV = "questions.csv"


def write_question_rows(rows: list[dict[str, Any]], out: Path) -> dict[str, Path]:
    """Write the per-question rows as JSON Lines and as CSV beside the report.

    Args:
        rows: The rows, each keyed by :data:`~evals.report.simple.QUESTION_COLUMNS`.
        out: The report directory.

    Returns:
        The two paths, by file name.
    """
    jsonl = out / QUESTIONS_JSONL
    with jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
    table = out / QUESTIONS_CSV
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(QUESTION_COLUMNS))
        writer.writeheader()
        writer.writerows({k: ("" if v is None else v) for k, v in row.items()} for row in rows)
    return {QUESTIONS_JSONL: jsonl, QUESTIONS_CSV: table}


def build_report(
    run_dir: Path,
    *,
    mode: str = DEFAULT_MODE,
    out_dir: Path,
    out_root: Path | None = None,
    judge_slug: str | None = None,
    n_boot: int = 10_000,
    n_perm: int = 10_000,
    n_boot_mean: int = 2_000,
    seed: int = 0,
    selftest: bool = True,
) -> Report:
    """Build a report from a run directory.

    Args:
        run_dir: ``<out>/runs/<name>``.
        mode: ``simple`` (the default: arm tables with intervals, paired head-to-head rows,
            change against explain, codebase style, cost against quality, the judge check and
            the limitations), ``full`` (one result per pre-registered hypothesis, with
            permutation tests, Holm correction and the channel analyses) or ``pilot`` (the older
            pilot comparisons with minimum detectable differences, a findings summary and the
            limitations).
        out_dir: Where ``report.json``, ``report.md``, ``figures/`` and the manifest go.
        out_root: The eval output directory, for gold files when the run directory carries no
            copy; ``<run_dir>/../..`` when omitted.
        judge_slug: A judge to read instead of the default.
        n_boot: Bootstrap resamples for comparisons.
        n_perm: Permutation patterns for comparisons.
        n_boot_mean: Bootstrap resamples for descriptive means.
        seed: Added to every seed, so a different seed gives a different resampling.
        selftest: Run the self-test first and refuse to build on a failure.

    Returns:
        The built report.

    Raises:
        ReportError: If the self-test fails, the mode is unknown, or the prose breaks the
            wording rules.
        evals.report.load.RunNotFound: If the run has no generations.
    """
    if mode not in MODES:
        raise ReportError(f"unknown mode {mode!r}; use one of {', '.join(MODES)}")
    if selftest:
        run_selftest()
    data = load_run(Path(run_dir), out_dir=out_root, judge_slug=judge_slug)
    config = StatConfig(n_boot=n_boot, n_perm=n_perm, n_boot_mean=n_boot_mean, seed=seed)
    if mode == "simple":
        report = assemble_simple(data, config)
        graph = None
    else:
        report = assemble(data, mode=mode, config=config)
        graph = report.pop("_graph")

    out = Path(out_dir)
    figures_dir = out / "figures"
    out.mkdir(parents=True, exist_ok=True)
    figures = make_figures(report)
    report["figures"] = {
        name: {"path": f"figures/{name}.svg", "data": plotted}
        for name, (_, plotted) in figures.items()
    }
    if graph is not None:
        report["trajectory_graph"] = {
            "path": TRAJECTORY_GRAPH,
            "item_id": graph["item_id"],
            "arm": graph["arm"],
        }

    markdown = render_simple_markdown(report) if mode == "simple" else render_markdown(report)
    problems = check_wording(markdown)
    if problems:
        raise ReportError("the report breaks the wording rules: " + " | ".join(problems))

    paths: dict[str, Path] = {}
    if figures:
        figures_dir.mkdir(exist_ok=True)
    for name, (text, _) in figures.items():
        paths[f"figures/{name}.svg"] = figures_dir / f"{name}.svg"
        paths[f"figures/{name}.svg"].write_text(text, encoding="utf-8")
    if graph is not None:
        paths[TRAJECTORY_GRAPH] = out / TRAJECTORY_GRAPH
        paths[TRAJECTORY_GRAPH].write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    paths["report.json"] = out / "report.json"
    paths["report.json"].write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    paths["report.md"] = out / "report.md"
    paths["report.md"].write_text(markdown, encoding="utf-8")
    if mode == "simple":
        paths.update(write_question_rows(question_rows(data), out))
    for source in sorted(Path(run_dir).glob("manifest*.json")):
        if source.name == MANIFEST_NAME or source.name == f"manifest.judge.{data.judge_slug}.json":
            shutil.copyfile(source, out / source.name)
            paths[source.name] = out / source.name
    return Report(data=report, markdown=markdown, out_dir=out, paths=paths)


__all__ = [
    "DEFAULT_MODE",
    "MODES",
    "Report",
    "ReportError",
    "assemble",
    "build_report",
    "run_selftest",
]
