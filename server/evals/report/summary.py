"""The pilot report's findings summary and scope statement, chosen from ``report.json`` by rule.

The rule is deterministic: resolved comparisons first (their 95% interval excludes zero), ordered
by the size of the effect relative to the second arm's mean; then the unresolved comparisons of
the primary family in pre-registration order, then the secondary family's. At most five findings
are kept. Each is the comparison's own sentence, so it carries its number, interval or minimum
detectable difference, and ``n``; an unresolved one also states the observed difference with its
interval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evals.report.wording import METRICS, interval_text, unit_text, value_text

MAX_FINDINGS = 5
_FAMILY_ORDER = {"primary": 0, "secondary": 1}


def _relative_effect(comparison: Mapping[str, Any]) -> float:
    base = abs(comparison.get("mean_b") or 0.0)
    return abs(comparison["estimate"]) / max(base, 1e-9)


def _headline(comparison: Mapping[str, Any]) -> str:
    style = METRICS[comparison["metric"]]
    marker = ", the headline comparison" if comparison.get("headline") else ""
    return (
        f"**{comparison['id']}**{marker}: `{comparison['arm_a']}` vs "
        f"`{comparison['arm_b']}`, {style.title}."
    )


def _observed(comparison: Mapping[str, Any]) -> str:
    metric = comparison["metric"]
    return (
        f"Observed difference {value_text(metric, comparison['estimate'], signed=True)}"
        f"{unit_text(metric)} ({interval_text(metric, comparison['ci_lo'], comparison['ci_hi'])}, "
        f"n = {comparison['n']})."
    )


def select_findings(
    comparisons: Sequence[Mapping[str, Any]], limit: int = MAX_FINDINGS
) -> list[dict[str, Any]]:
    """Choose the findings to put at the top of a pilot report.

    Args:
        comparisons: The computed pilot comparisons, with their ``sentence`` and ``resolved``.
        limit: The most findings to keep.

    Returns:
        Up to ``limit`` records with ``id``, ``resolved`` and ``text``, in reading order.
    """
    candidates = [c for c in comparisons if c.get("family") in _FAMILY_ORDER]
    resolved = sorted(
        (c for c in candidates if c["resolved"]),
        key=lambda c: (-_relative_effect(c), c["id"]),
    )
    unresolved = sorted(
        (c for c in candidates if not c["resolved"]),
        key=lambda c: (_FAMILY_ORDER[c["family"]], _spec_position(c, comparisons)),
    )
    findings = []
    for comparison in [*resolved, *unresolved][:limit]:
        text = f"{_headline(comparison)} {comparison['sentence']}"
        if not comparison["resolved"] and comparison.get("kind", "diff") == "diff":
            text += f" {_observed(comparison)}"
        findings.append({"id": comparison["id"], "resolved": comparison["resolved"], "text": text})
    return findings


def _spec_position(comparison: Mapping[str, Any], comparisons: Sequence[Mapping[str, Any]]) -> int:
    return next(i for i, c in enumerate(comparisons) if c["id"] == comparison["id"])


def scope_lines(scope: Mapping[str, Any]) -> list[str]:
    """The two-line scope statement of a pilot report, filled from the data.

    Args:
        scope: The report's ``scope`` section.

    Returns:
        Two lines: what was asked of whom, and how the numbers are to be read.
    """
    families = scope["families"]
    parts = ", ".join(f"{count} {family}" for family, count in families.items())
    names = ", ".join(f"`{name}`" for name in scope["repositories"])
    models = ", ".join(f"`{m}`" for m in scope["generator_models"]) or "an unrecorded model"
    generators = "one generator model" if scope["n_generator_models"] == 1 else "generator models"
    first = (
        f"Scope: {scope['n_repositories']} repositories ({names}), {scope['n_questions']} "
        f"questions ({parts}), {generators} ({models}); a pilot run."
    )
    second = (
        f"{scope['n_arms']} arms answered the questions; every number carries its n and, where "
        "it is an estimate, a 95% interval, and every claim is about these repositories only."
    )
    return [first, second]


__all__ = ["MAX_FINDINGS", "scope_lines", "select_findings"]
