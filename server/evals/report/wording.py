"""The report's wording rules, as code.

A comparison whose 95% interval excludes zero is stated as a finding about the repositories in the
run; any other comparison is stated as not resolved, with the smallest difference the data could
have resolved. No sentence claims a result for repositories in general, and none says
"significant" without the test and the sample size beside it. :func:`check_wording` flags the
forbidden phrasings so the builder can refuse its own output and the tests can pin the rules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
_WORDS[9] = "nine"


@dataclass(frozen=True)
class MetricStyle:
    """How a metric is named and printed.

    Attributes:
        key: The metric's key in the report.
        title: A short name for tables.
        unit: ``points``, ``dollars`` or ``steps``.
        more: The verb phrase for the first arm having more of it.
        less: The verb phrase for the first arm having less of it.
    """

    key: str
    title: str
    unit: str
    more: str
    less: str


METRICS: dict[str, MetricStyle] = {
    "recall": MetricStyle(
        "recall",
        "answer file recall",
        "points",
        "found more of the changed files than",
        "found fewer of the changed files than",
    ),
    "recall_nt": MetricStyle(
        "recall_nt",
        "answer file recall without test files",
        "points",
        "found more of the changed non-test files than",
        "found fewer of the changed non-test files than",
    ),
    "recall10": MetricStyle(
        "recall10",
        "file recall in the top ten",
        "points",
        "ranked more of the changed files in its top ten than",
        "ranked fewer of the changed files in its top ten than",
    ),
    "cost": MetricStyle(
        "cost",
        "dollars per question",
        "dollars",
        "cost more per question than",
        "cost less per question than",
    ),
    "steps": MetricStyle(
        "steps",
        "steps to the first changed file",
        "steps",
        "took more steps to reach the first changed file than",
        "took fewer steps to reach the first changed file than",
    ),
}


def repositories_phrase(count: int) -> str:
    """``on these two repositories``-style scope for a sentence start (capitalised).

    Args:
        count: How many repositories the comparison covers.

    Returns:
        ``On this repository`` for one, otherwise ``On these <n> repositories`` with the number
        spelled out up to nine.
    """
    if count == 1:
        return "On this repository"
    return f"On these {_WORDS.get(count, count)} repositories"


def money(value: float) -> str:
    """A dollar amount with its sign before the symbol, four decimals."""
    return f"-${abs(value):.4f}" if value < 0 else f"${value:.4f}"


def value_text(metric: str, value: float, *, signed: bool = False) -> str:
    """A metric value without its unit.

    Args:
        metric: A key of :data:`METRICS`.
        value: The value, as the report stores it (recall as a fraction).
        signed: Put an explicit ``+`` on positive values.

    Returns:
        Points to one decimal for recall metrics, dollars to four decimals for cost, steps to one
        decimal.
    """
    unit = METRICS[metric].unit
    sign = "+" if signed and value > 0 else ""
    if unit == "points":
        return f"{sign}{value * 100:.1f}"
    if unit == "dollars":
        return f"{sign}{money(value)}"
    return f"{sign}{value:.1f}"


def unit_text(metric: str) -> str:
    """The unit printed after a signed estimate."""
    unit = METRICS[metric].unit
    return {"points": " points", "dollars": " per question", "steps": " steps"}[unit]


def interval_text(metric: str, low: float, high: float) -> str:
    """``95% CI a to b`` for an interval."""
    return f"95% CI {value_text(metric, low)} to {value_text(metric, high)}"


def excludes_zero(low: float, high: float) -> bool:
    """Whether an interval lies entirely on one side of zero."""
    return low > 0 or high < 0


def _arm(name: str) -> str:
    return f"`{name}`"


def comparison_sentence(comparison: Mapping[str, Any], repositories: int) -> str:
    """The one sentence a comparison is stated in.

    A difference whose interval excludes zero is a finding about these repositories, with the
    estimate, interval and ``n``. Anything else is "not resolved" with the minimum detectable
    difference (or, for a ratio criterion, the interval and the criterion it spans) and ``n``.

    Args:
        comparison: A comparison record: ``kind``, ``arm_a``, ``arm_b``, ``metric``,
            ``estimate``, ``ci_lo``, ``ci_hi``, ``n`` and, where it applies, ``mdd`` and
            ``criterion``.
        repositories: How many repositories the run covers.

    Returns:
        A complete sentence ending in a full stop.
    """
    kind = comparison.get("kind", "diff")
    if kind in ("cost_multiple", "ratio_floor", "ratio_ceiling"):
        return _ratio_sentence(comparison, repositories)
    metric = comparison["metric"]
    style = METRICS[metric]
    low, high, n = comparison["ci_lo"], comparison["ci_hi"], comparison["n"]
    if excludes_zero(low, high):
        verb = style.more if comparison["estimate"] > 0 else style.less
        estimate = value_text(metric, comparison["estimate"], signed=True)
        return (
            f"{repositories_phrase(repositories)}, {_arm(comparison['arm_a'])} {verb} "
            f"{_arm(comparison['arm_b'])} ({estimate}{unit_text(metric)}, "
            f"{interval_text(metric, low, high)}, n = {n})."
        )
    mdd = comparison.get("mdd")
    if mdd is None:
        return f"Not resolved at this sample size (n = {n})."
    mdd_text = value_text(metric, mdd)
    return (
        f"Not resolved at this sample size (minimum detectable difference ≈ "
        f"{mdd_text}{unit_text(metric)}, n = {n})."
    )


def _ratio_sentence(comparison: Mapping[str, Any], repositories: int) -> str:
    kind = comparison["kind"]
    criterion = comparison["criterion"]
    low, high, n = comparison["ci_lo"], comparison["ci_hi"], comparison["n"]
    ratio = comparison["estimate"]
    spans = low <= criterion <= high
    detail = f"ratio {ratio:.2f}, 95% CI {low:.2f} to {high:.2f}, n = {n}"
    a, b = _arm(comparison["arm_a"]), _arm(comparison["arm_b"])
    scope = repositories_phrase(repositories)
    if spans:
        return (
            f"Not resolved at this sample size (the ratio's 95% CI {low:.2f} to {high:.2f} "
            f"spans the criterion {criterion:g}, n = {n})."
        )
    if kind == "cost_multiple":
        relation = "more" if low > criterion else "less"
        return (
            f"{scope}, {a} cost {relation} than {criterion:g} times as much per question as "
            f"{b} ({detail})."
        )
    if kind == "ratio_floor":
        relation = "at least" if low > criterion else "less than"
        return (
            f"{scope}, {a} kept {relation} {criterion * 100:.0f}% of {b}'s answer file recall "
            f"({detail})."
        )
    relation = "less" if high < criterion else "more"
    return (
        f"{scope}, {a} cost {relation} than {criterion * 100:.0f}% as much per question as "
        f"{b} ({detail})."
    )


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_SIGNIFICANT = re.compile(r"\bsignifican(?:t|tly|ce)\b", re.IGNORECASE)
_TEST_NAME = re.compile(
    r"permutation|sign-flip|bootstrap|\bTOST\b|\bHolm\b|Wilson|\bz-?test\b|\bt-?test\b|"
    r"\bp\s*[=<≤]",
    re.IGNORECASE,
)
_SAMPLE_SIZE = re.compile(r"\bn\s*=\s*\d", re.IGNORECASE)
_FORBIDDEN = (
    (re.compile(r"\bin general\b", re.IGNORECASE), "claims a result in general"),
    (re.compile(r"\brepositories in general\b", re.IGNORECASE), "claims a result for repositories"),
    (re.compile(r"\balways\b", re.IGNORECASE), "uses 'always'"),
)


def check_wording(text: str) -> list[str]:
    """Flag phrasings the report must not contain.

    The rules: "significant" (or "significantly", "significance") needs a test name and a sample
    size in the same sentence; "in general", "repositories in general" and "always" are never
    used.

    Args:
        text: Any prose, such as a whole ``report.md``.

    Returns:
        One message per violation, each quoting the sentence; empty when the text is clean.
    """
    problems: list[str] = []
    for sentence in _SENTENCE_BREAK.split(text):
        if not sentence.strip():
            continue
        if _SIGNIFICANT.search(sentence) and not (
            _TEST_NAME.search(sentence) and _SAMPLE_SIZE.search(sentence)
        ):
            problems.append(f"'significant' without a test and n in: {sentence.strip()!r}")
        for pattern, message in _FORBIDDEN:
            if pattern.search(sentence):
                problems.append(f"{message} in: {sentence.strip()!r}")
    return problems


__all__ = [
    "METRICS",
    "MetricStyle",
    "check_wording",
    "comparison_sentence",
    "excludes_zero",
    "interval_text",
    "money",
    "repositories_phrase",
    "unit_text",
    "value_text",
]
