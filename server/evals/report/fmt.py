"""Number formatting shared by the prose and the tables, so one value reads one way everywhere."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def pct(value: float) -> str:
    """A fraction as a percentage to one decimal."""
    return f"{value * 100:.1f}%"


def pts(value: float) -> str:
    """A fraction as points (percentage without the sign) to one decimal."""
    return f"{value * 100:.1f}"


def num(value: float, places: int = 2) -> str:
    """A plain decimal."""
    return f"{value:.{places}f}"


def usd(value: float, places: int = 4) -> str:
    """Dollars with the symbol first."""
    return f"-${abs(value):.{places}f}" if value < 0 else f"${value:.{places}f}"


def span_pct(low: float, high: float) -> str:
    """An interval of fractions, as percentages."""
    return f"{pts(low)} to {pts(high)}"


def mean_pct(cell: Mapping[str, Any] | None) -> str:
    """A mean-with-interval cell holding fractions: ``63.4% (55.2 to 71.0)``."""
    if not cell:
        return "n/a"
    return f"{pct(cell['mean'])} ({span_pct(cell['lo'], cell['hi'])})"


def mean_num(cell: Mapping[str, Any] | None, places: int = 2) -> str:
    """A mean-with-interval cell holding plain numbers."""
    if not cell:
        return "n/a"
    return f"{num(cell['mean'], places)} ({num(cell['lo'], places)} to {num(cell['hi'], places)})"


def mean_usd(cell: Mapping[str, Any] | None) -> str:
    """A mean-with-interval cell holding dollars."""
    if not cell:
        return "n/a"
    return f"{usd(cell['mean'])} ({usd(cell['lo'])} to {usd(cell['hi'])})"


def rate(cell: Mapping[str, Any]) -> str:
    """A Wilson cell: ``12.5% (4.2 to 29.0)``; ``n/a`` when nothing was counted."""
    if not cell["n"]:
        return "n/a"
    return f"{pct(cell['rate'])} ({span_pct(cell['lo'], cell['hi'])})"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """A markdown table, or an empty string when there are no rows (never an empty table)."""
    if not rows:
        return ""
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def code(name: str) -> str:
    """An identifier in backticks."""
    return f"`{name}`"


__all__ = [
    "code",
    "md_table",
    "mean_num",
    "mean_pct",
    "mean_usd",
    "num",
    "pct",
    "pts",
    "rate",
    "span_pct",
    "usd",
]
