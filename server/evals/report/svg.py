"""Standalone SVG figures drawn with plain primitives, so the report needs no plotting library.

Each function returns the text of a complete ``<svg>`` document with a light background, axes,
ticks, a title and, where there are several series, a legend. The numbers a figure plots are
written into ``report.json`` by the caller; nothing here reads or writes files.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

PALETTE = (
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#d97706",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#475569",
    "#ea580c",
    "#0d9488",
    "#9333ea",
)
INK = "#1f2937"
MUTED = "#6b7280"
GRID = "#e5e7eb"
PAPER = "#ffffff"
FONT = 'font-family="system-ui, Segoe UI, sans-serif"'

WIDTH = 720
HEIGHT = 440
MARGIN_LEFT = 72
MARGIN_RIGHT = 190
MARGIN_TOP = 44
MARGIN_BOTTOM = 56


def nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round tick positions covering ``[low, high]``.

    Args:
        low: The smallest value to cover.
        high: The largest value to cover.
        count: About how many ticks to produce.

    Returns:
        Ascending tick values; a single value when ``low == high``.
    """
    if high <= low:
        return [low]
    raw = (high - low) / max(count, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = magnitude
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if step >= raw:
            break
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 1e-9:
        ticks.append(round(value, 12))
        value += step
    return ticks


def _fmt(value: float) -> str:
    text = f"{value:.4g}"
    return "0" if text == "-0" else text


class _Canvas:
    def __init__(self, title: str, width: int = WIDTH, height: int = HEIGHT) -> None:
        self.width = width
        self.height = height
        self.parts: list[str] = [
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="{PAPER}"/>',
            f'<text x="{MARGIN_LEFT}" y="26" font-size="15" font-weight="600" fill="{INK}" '
            f"{FONT}>{escape(title)}</text>",
        ]
        self.plot_w = width - MARGIN_LEFT - MARGIN_RIGHT
        self.plot_h = height - MARGIN_TOP - MARGIN_BOTTOM

    def x(self, value: float, low: float, high: float) -> float:
        span = (high - low) or 1.0
        return MARGIN_LEFT + (value - low) / span * self.plot_w

    def y(self, value: float, low: float, high: float) -> float:
        span = (high - low) or 1.0
        return MARGIN_TOP + self.plot_h - (value - low) / span * self.plot_h

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: int = 11,
        anchor: str = "start",
        fill: str = MUTED,
    ) -> None:
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{fill}" {FONT}>{escape(content)}</text>'
        )

    def line(
        self, x1: float, y1: float, x2: float, y2: float, colour: str = GRID, width: float = 1
    ) -> None:
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{colour}" stroke-width="{width}"/>'
        )

    def axes(
        self,
        xs: Sequence[float],
        ys: Sequence[float],
        xlim: tuple[float, float],
        ylim: tuple[float, float],
        xlabel: str,
        ylabel: str,
        *,
        xticks_text: Mapping[float, str] | None = None,
    ) -> None:
        bottom = MARGIN_TOP + self.plot_h
        for tick in ys:
            ypos = self.y(tick, *ylim)
            self.line(MARGIN_LEFT, ypos, MARGIN_LEFT + self.plot_w, ypos)
            self.text(MARGIN_LEFT - 8, ypos + 4, _fmt(tick), anchor="end")
        for tick in xs:
            xpos = self.x(tick, *xlim)
            self.line(xpos, bottom, xpos, bottom + 4, MUTED)
            label = xticks_text[tick] if xticks_text and tick in xticks_text else _fmt(tick)
            self.text(xpos, bottom + 18, label, anchor="middle")
        self.line(MARGIN_LEFT, bottom, MARGIN_LEFT + self.plot_w, bottom, MUTED)
        self.line(MARGIN_LEFT, MARGIN_TOP, MARGIN_LEFT, bottom, MUTED)
        self.text(MARGIN_LEFT + self.plot_w / 2, self.height - 14, xlabel, anchor="middle", size=12)
        middle = MARGIN_TOP + self.plot_h / 2
        self.parts.append(
            f'<text x="16" y="{middle:.1f}" font-size="12" fill="{MUTED}" '
            f'text-anchor="middle" transform="rotate(-90 16 {middle:.1f})" '
            f"{FONT}>{escape(ylabel)}</text>"
        )

    def legend(self, entries: Sequence[tuple[str, str]]) -> None:
        x = self.width - MARGIN_RIGHT + 16
        for index, (label, colour) in enumerate(entries):
            y = MARGIN_TOP + 8 + index * 18
            self.parts.append(f'<rect x="{x}" y="{y - 9}" width="10" height="10" fill="{colour}"/>')
            self.text(x + 16, y, label, fill=INK)

    def render(self) -> str:
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'role="img">\n{body}\n</svg>\n'
        )


def _range(values: Sequence[float], *, floor: float | None = None) -> tuple[float, float]:
    low, high = min(values), max(values)
    if floor is not None:
        low = min(low, floor)
    if high == low:
        high = low + 1.0
    pad = (high - low) * 0.08
    return (floor if floor is not None and low >= floor else low - pad), high + pad


def scatter_svg(
    points: Sequence[tuple[str, float, float]],
    *,
    frontier: Sequence[str] = (),
    highlight: Sequence[str] = (),
    title: str,
    xlabel: str,
    ylabel: str,
) -> str:
    """A labelled scatter plot with the non-dominated points joined by a line.

    Args:
        points: ``(label, x, y)`` triples.
        frontier: Labels on the frontier, drawn joined and filled.
        highlight: Labels drawn larger with a ring (``auto``, for the cost chart).
        title: The figure title.
        xlabel: The x axis label.
        ylabel: The y axis label.

    Returns:
        The SVG document.
    """
    canvas = _Canvas(title)
    xlim = _range([p[1] for p in points], floor=0.0)
    ylim = _range([p[2] for p in points], floor=0.0)
    canvas.axes(nice_ticks(*xlim), nice_ticks(*ylim), xlim, ylim, xlabel, ylabel)
    on_frontier = [p for p in sorted(points, key=lambda p: p[1]) if p[0] in frontier]
    for left, right in zip(on_frontier, on_frontier[1:], strict=False):
        canvas.line(
            canvas.x(left[1], *xlim),
            canvas.y(left[2], *ylim),
            canvas.x(right[1], *xlim),
            canvas.y(right[2], *ylim),
            PALETTE[0],
            1.5,
        )
    entries = []
    for index, (label, x, y) in enumerate(points):
        colour = PALETTE[index % len(PALETTE)]
        radius = 7 if label in highlight else 5
        cx, cy = canvas.x(x, *xlim), canvas.y(y, *ylim)
        fill = colour if label in frontier else PAPER
        canvas.parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{fill}" '
            f'stroke="{colour}" stroke-width="2"/>'
        )
        if label in highlight:
            canvas.parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius + 4}" fill="none" '
                f'stroke="{INK}" stroke-width="1"/>'
            )
        entries.append((label, colour))
    canvas.legend(entries)
    return canvas.render()


def bars_svg(
    rows: Sequence[tuple[str, float, float, float]],
    *,
    title: str,
    xlabel: str,
) -> str:
    """Horizontal bars with a whisker for an interval, around a zero line.

    Args:
        rows: ``(label, value, low, high)`` per bar.
        title: The figure title.
        xlabel: The value axis label.

    Returns:
        The SVG document.
    """
    height = max(HEIGHT // 2, MARGIN_TOP + MARGIN_BOTTOM + 34 * len(rows))
    canvas = _Canvas(title, WIDTH, height)
    extremes = [0.0] + [r[2] for r in rows] + [r[3] for r in rows] + [r[1] for r in rows]
    xlim = _range(extremes)
    bottom = MARGIN_TOP + canvas.plot_h
    for tick in nice_ticks(*xlim):
        xpos = canvas.x(tick, *xlim)
        canvas.line(xpos, MARGIN_TOP, xpos, bottom)
        canvas.text(xpos, bottom + 18, _fmt(tick), anchor="middle")
    zero = canvas.x(0.0, *xlim)
    canvas.line(zero, MARGIN_TOP, zero, bottom, MUTED, 1.5)
    canvas.text(MARGIN_LEFT + canvas.plot_w / 2, height - 14, xlabel, anchor="middle", size=12)
    slot = canvas.plot_h / max(len(rows), 1)
    for index, (label, value, low, high) in enumerate(rows):
        centre = MARGIN_TOP + slot * (index + 0.5)
        colour = PALETTE[index % len(PALETTE)]
        left, right = sorted((zero, canvas.x(value, *xlim)))
        canvas.parts.append(
            f'<rect x="{left:.1f}" y="{centre - 9:.1f}" width="{max(right - left, 1):.1f}" '
            f'height="18" fill="{colour}" fill-opacity="0.75"/>'
        )
        canvas.line(canvas.x(low, *xlim), centre, canvas.x(high, *xlim), centre, INK, 1.5)
        for end in (low, high):
            xpos = canvas.x(end, *xlim)
            canvas.line(xpos, centre - 5, xpos, centre + 5, INK, 1.5)
        canvas.text(MARGIN_LEFT + canvas.plot_w + 12, centre + 4, label, fill=INK)
    return canvas.render()


def lines_svg(
    series: Mapping[str, Sequence[tuple[float, float]]],
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    xtick_labels: Mapping[float, str] | None = None,
    ylim: tuple[float, float] | None = None,
) -> str:
    """Lines with markers, one per series.

    Args:
        series: Series name to ``(x, y)`` points in x order.
        title: The figure title.
        xlabel: The x axis label.
        ylabel: The y axis label.
        xtick_labels: Text to print at specific x positions instead of the number.
        ylim: A fixed y range; fitted to the data when omitted.

    Returns:
        The SVG document.
    """
    canvas = _Canvas(title)
    xs = [x for points in series.values() for x, _ in points] or [0.0, 1.0]
    ys = [y for points in series.values() for _, y in points] or [0.0, 1.0]
    xlim = (min(xs) - 0.25, max(xs) + 0.25) if xtick_labels else _range(xs)
    chosen_y = ylim or _range(ys, floor=0.0)
    xticks = list(xtick_labels) if xtick_labels else nice_ticks(*xlim)
    canvas.axes(
        xticks,
        nice_ticks(*chosen_y),
        xlim,
        chosen_y,
        xlabel,
        ylabel,
        xticks_text=xtick_labels,
    )
    entries = []
    for index, (name, points) in enumerate(series.items()):
        colour = PALETTE[index % len(PALETTE)]
        coords = [(canvas.x(x, *xlim), canvas.y(y, *chosen_y)) for x, y in points]
        if len(coords) > 1:
            path = " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)
            canvas.parts.append(
                f'<polyline points="{path}" fill="none" stroke="{colour}" stroke-width="2"/>'
            )
        for cx, cy in coords:
            canvas.parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{colour}"/>')
        entries.append((name, colour))
    canvas.legend(entries)
    return canvas.render()


__all__ = ["PALETTE", "bars_svg", "lines_svg", "nice_ticks", "scatter_svg"]
