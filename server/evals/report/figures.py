"""The report's figures, drawn from the report data (never from the run's files).

Each figure is returned with the numbers it plots, which go into ``report.json`` beside it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evals.arms import AUTO
from evals.report import svg


def pareto_figure(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Dollars per question against answer recall, the frontier joined, ``auto`` ringed."""
    section = data.get("pareto")
    if not section:
        return None
    points = [(p["arm"], p["cost_per_question"], p["recall"]) for p in section["points"]]
    text = svg.scatter_svg(
        points,
        frontier=section["frontier"],
        highlight=[AUTO],
        title="Cost against answer file recall",
        xlabel="Dollars per question",
        ylabel="Answer file recall",
    )
    return text, {"points": section["points"], "frontier": section["frontier"]}


def cost_quality_figure(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Dollars per answer against mean correctness for every arm, the frontier joined."""
    section = data.get("cost_quality")
    if not section:
        return None
    points = [(p["arm"], p["cost_per_answer"], p["correctness"]) for p in section["points"]]
    text = svg.scatter_svg(
        points,
        frontier=section["frontier"],
        highlight=[AUTO],
        title="Cost against correctness",
        xlabel="Dollars per answer",
        ylabel="Mean correctness",
    )
    return text, {"points": section["points"], "frontier": section["frontier"]}


def ablation_figure(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The change in answer recall when each channel is removed, with its interval, in points."""
    section = data.get("ablation")
    if not section:
        return None
    rows = [r for r in section["rows"] if r["metric"] == "recall"]
    if not rows:
        return None
    bars = [
        (f"without {r['channel']}", r["estimate"] * 100, r["ci_lo"] * 100, r["ci_hi"] * 100)
        for r in rows
    ]
    text = svg.bars_svg(
        bars,
        title="Recall lost when a channel is removed",
        xlabel="Points of answer file recall, structural minus ablated",
    )
    return text, {
        "rows": [
            {
                "channel": r["channel"],
                "estimate": r["estimate"],
                "ci_lo": r["ci_lo"],
                "ci_hi": r["ci_hi"],
                "n": r["n"],
            }
            for r in rows
        ]
    }


def steps_figure(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The share of agent runs that have touched a gold file by each step."""
    section = data.get("trajectory")
    if not section or not section["steps_to_gold_curve"]:
        return None
    curves = section["steps_to_gold_curve"]
    series = {arm: [(float(s), share) for s, share in points] for arm, points in curves.items()}
    text = svg.lines_svg(
        series,
        title="Runs that have reached a changed file, by step",
        xlabel="Steps taken",
        ylabel="Share of runs",
        ylim=(0.0, 1.0),
    )
    return text, {"curves": curves}


def drift_figure(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Answer recall by how long after the base commit the pull request merged."""
    section = data.get("drift")
    if not section:
        return None
    buckets = section["buckets"]
    arms = [a for a in buckets[0]["by_arm"] if all(b["by_arm"].get(a) for b in buckets)]
    if not arms:
        return None
    series = {
        arm: [(float(i), b["by_arm"][arm]["mean"]) for i, b in enumerate(buckets)] for arm in arms
    }
    labels = {float(i): f"{b['lo']} to {b['hi']}" for i, b in enumerate(buckets)}
    text = svg.lines_svg(
        series,
        title="Answer recall by merges after the base commit",
        xlabel="Merges since the base commit",
        ylabel="Answer file recall",
        xtick_labels=labels,
        ylim=(0.0, 1.0),
    )
    return text, {
        "series": {arm: [[i, m] for i, m in points] for arm, points in series.items()},
        "buckets": [{"lo": b["lo"], "hi": b["hi"], "n_items": b["n_items"]} for b in buckets],
    }


FIGURES = (
    ("pareto", pareto_figure),
    ("cost_quality", cost_quality_figure),
    ("ablation", ablation_figure),
    ("steps_to_gold", steps_figure),
    ("drift", drift_figure),
)


def make_figures(data: Mapping[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Every figure the data supports, by name."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for name, build in FIGURES:
        figure = build(data)
        if figure is not None:
            out[name] = figure
    return out


__all__ = ["FIGURES", "make_figures"]
