"""The pinned price table and the cost of a metered call.

Prices are data, not code: ``prices.yaml`` holds them, dated and versioned, with every rate
``null`` until the user fills it from the providers' pricing pages. A paid run calls
:meth:`PriceTable.require_complete` first and refuses to start while any rate it needs is
missing. A call that reports its own cost (Cohere and Jev do) is never priced from the table.

DeepSeek charges less in a daily off-peak window, so a model may carry separate ``peak`` and
``off_peak`` rates and the cost of a call depends on when it is made.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from evals.run.records import Usage

PRICES_PATH = Path(__file__).with_name("prices.yaml")
TOKENS_PER_RATE = 1_000_000

_RATE_FIELDS = ("input_cache_miss", "input_cache_hit", "output")


class PricesIncomplete(ValueError):
    """The price table lacks a rate a run needs.

    Attributes:
        missing: One entry per missing rate, such as ``gpt-6-luna.rates.output``.
    """

    def __init__(self, missing: Iterable[str]) -> None:
        self.missing = list(missing)
        listed = "\n  ".join(self.missing)
        super().__init__(
            "the price table is incomplete; fill in server/evals/run/prices.yaml from each "
            f"provider's pricing page before a paid run. Missing:\n  {listed}"
        )


class UnpricedUsage(LookupError):
    """A call used tokens of a model the table has no entry for, and reported no cost."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"no price for model {model!r} and the call reported no cost")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rates(_Frozen):
    """One set of per-million-token rates, in US dollars.

    Attributes:
        input_cache_miss: Input tokens not served from the provider's cache.
        input_cache_hit: Input tokens served from the provider's cache.
        output: Output tokens.
    """

    input_cache_miss: float | None = None
    input_cache_hit: float | None = None
    output: float | None = None

    def missing(self, label: str) -> list[str]:
        """The rates that are still ``null``, labelled ``<label>.<field>``."""
        return [f"{label}.{name}" for name in _RATE_FIELDS if getattr(self, name) is None]


class ModelPrice(_Frozen):
    """The rates of one model: one flat set, or separate peak and off-peak sets.

    Attributes:
        rates: The rates at any time of day.
        peak: The rates outside the off-peak window.
        off_peak: The rates inside the off-peak window.
    """

    rates: Rates | None = None
    peak: Rates | None = None
    off_peak: Rates | None = None

    @model_validator(mode="after")
    def _one_shape(self) -> Self:
        timed = self.peak is not None or self.off_peak is not None
        if self.rates is not None and timed:
            raise ValueError("a model has either `rates` or `peak` and `off_peak`, not both")
        if self.rates is None and (self.peak is None or self.off_peak is None):
            raise ValueError("a model needs `rates`, or both `peak` and `off_peak`")
        return self

    @property
    def is_timed(self) -> bool:
        """Whether the price depends on the time of day."""
        return self.rates is None

    def missing(self, label: str) -> list[str]:
        """The rates that are still ``null``."""
        parts = (("rates", self.rates), ("peak", self.peak), ("off_peak", self.off_peak))
        return [
            entry
            for name, rates in parts
            if rates is not None
            for entry in rates.missing(f"{label}.{name}")
        ]


class OffPeakWindow(_Frozen):
    """The daily off-peak window as UTC ``HH:MM`` times; it may wrap past midnight.

    Attributes:
        start_utc: When the window opens.
        end_utc: When it closes.
    """

    start_utc: str | None = None
    end_utc: str | None = None

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if (self.start_utc is None) != (self.end_utc is None):
            raise ValueError("set both start_utc and end_utc, or neither")
        if self.start_utc is not None and self.start_utc == self.end_utc:
            raise ValueError("an off-peak window cannot start and end at the same time")
        for text in (self.start_utc, self.end_utc):
            if text is not None:
                _parse_clock(text)
        return self

    @property
    def is_set(self) -> bool:
        """Whether both ends are filled in."""
        return self.start_utc is not None and self.end_utc is not None


class PeakHours(_Frozen):
    """Peak hours as UTC ``HH:MM`` windows on given weekdays; every other hour is off-peak.

    This describes a provider whose discount covers everything outside a few weekday windows,
    which a single daily off-peak window cannot. Windows may not wrap past midnight. Public
    holidays a provider also treats as off-peak are not modelled, so a call on one is priced at
    the peak rate, which can only overstate the cost.

    Attributes:
        days: ISO weekdays the windows apply on, 1 for Monday to 7 for Sunday.
        windows_utc: ``[start, end]`` pairs; a window covers ``start`` up to but not ``end``.
    """

    days: tuple[int, ...] = (1, 2, 3, 4, 5)
    windows_utc: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if not self.windows_utc:
            raise ValueError("peak_hours needs at least one window")
        if not self.days or any(day not in range(1, 8) for day in self.days):
            raise ValueError("peak_hours days are ISO weekdays, 1 (Monday) to 7 (Sunday)")
        for start, end in self.windows_utc:
            if _parse_clock(start) >= _parse_clock(end):
                raise ValueError(f"a peak window must end after it starts: {start}-{end}")
        return self

    def windows(self) -> list[tuple[time, time]]:
        """The windows as times, in order of their start."""
        return sorted((_parse_clock(a), _parse_clock(b)) for a, b in self.windows_utc)

    def window_at(self, moment: datetime) -> tuple[time, time] | None:
        """The peak window ``moment`` (in UTC) falls in, or ``None`` when it is off-peak."""
        if moment.isoweekday() not in self.days:
            return None
        clock = moment.time()
        for start, end in self.windows():
            if start <= clock < end:
                return start, end
        return None


def _parse_clock(text: str) -> time:
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{text!r} is not an HH:MM time") from None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _lookup[T](table: dict[str, T], model: str) -> tuple[str, T] | None:
    """The entry for ``model``: an exact id, else the longest id that prefixes it.

    A provider may report a dated snapshot (``gpt-6-luna-2026-10-01``) for the id asked for.
    """
    if model in table:
        return model, table[model]
    prefixes = [key for key in table if model.startswith(key)]
    if not prefixes:
        return None
    best = max(prefixes, key=len)
    return best, table[best]


class PriceTable(_Frozen):
    """The dated price table.

    Attributes:
        version: A label recorded in every run manifest.
        as_of: When the rates were read from the providers' pages.
        verified: Whether the rates have been checked; a paid run needs ``True``.
        off_peak: The daily off-peak window the ``off_peak`` rates apply in.
        peak_hours: Peak windows on given weekdays; when set, it replaces ``off_peak`` and every
            hour outside them is off-peak.
        models: Chat model rates by model id.
        embeddings: Embedding rates, per million input tokens, by model id.
    """

    version: str
    as_of: date | None = None
    verified: bool = False
    off_peak: OffPeakWindow = OffPeakWindow()
    peak_hours: PeakHours | None = None
    models: dict[str, ModelPrice] = {}
    embeddings: dict[str, float | None] = {}

    @classmethod
    def load(cls, path: Path = PRICES_PATH) -> Self:
        """Reads a table from a YAML file; the shipped ``prices.yaml`` when omitted."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    # --- completeness ---------------------------------------------------------

    def require_complete(self, models: Iterable[str]) -> None:
        """Refuses a paid run unless every rate the given models need is filled in.

        Args:
            models: The chat and embedding model ids the run will call.

        Raises:
            PricesIncomplete: Listing every missing rate; also when the table is unverified or
                a model has no entry at all.
        """
        missing: list[str] = []
        if not self.verified:
            missing.append("verified (set it to true once the rates are checked)")
        if self.as_of is None:
            missing.append("as_of")
        needs_window = False
        for name in dict.fromkeys(models):
            chat = _lookup(self.models, name)
            if chat is not None:
                key, price = chat
                missing.extend(price.missing(key))
                needs_window = needs_window or price.is_timed
                continue
            embedding = _lookup(self.embeddings, name)
            if embedding is not None:
                key, rate = embedding
                if rate is None:
                    missing.append(f"embeddings.{key}")
                continue
            missing.append(f"{name} (no entry)")
        if needs_window and self.peak_hours is None and not self.off_peak.is_set:
            missing.extend(["off_peak.start_utc", "off_peak.end_utc"])
        if missing:
            raise PricesIncomplete(missing)

    # --- the off-peak window --------------------------------------------------

    def is_off_peak(self, now: datetime) -> bool:
        """Whether ``now`` is off-peak: outside every peak window, or inside the off-peak one.

        Raises:
            PricesIncomplete: When neither ``peak_hours`` nor the off-peak window is filled in.
        """
        if self.peak_hours is not None:
            return self.peak_hours.window_at(_utc(now)) is None
        start, end = self._window()
        moment = _utc(now).time()
        if start < end:
            return start <= moment < end
        return moment >= start or moment < end

    def seconds_until_off_peak(self, now: datetime) -> float:
        """Seconds until the window next opens; ``0`` when it is open now."""
        if self.is_off_peak(now):
            return 0.0
        if self.peak_hours is not None:
            current = _utc(now)
            while (window := self.peak_hours.window_at(current)) is not None:
                current = datetime.combine(current.date(), window[1], tzinfo=UTC)
            return (current - _utc(now)).total_seconds()
        start, _ = self._window()
        current = _utc(now)
        opens = datetime.combine(current.date(), start, tzinfo=UTC)
        if opens <= current:
            opens += timedelta(days=1)
        return (opens - current).total_seconds()

    def _window(self) -> tuple[time, time]:
        if self.off_peak.start_utc is None or self.off_peak.end_utc is None:
            raise PricesIncomplete(["off_peak.start_utc", "off_peak.end_utc"])
        return _parse_clock(self.off_peak.start_utc), _parse_clock(self.off_peak.end_utc)

    # --- cost -------------------------------------------------------------------

    def cost(self, usage: Usage, now: datetime) -> float:
        """The cost of one metered call in US dollars.

        A cost the provider reported wins over the table. Otherwise the call is priced by its
        model: input split into cache-miss and cache-hit tokens, plus output, at the rates in
        force at ``now``; an embedding by its input tokens.

        Args:
            usage: The call.
            now: When the call was made; decides peak or off-peak rates.

        Raises:
            UnpricedUsage: When the call used tokens of a model with no entry.
            PricesIncomplete: When a rate the call needs is ``null``.
        """
        if usage.reported_cost_usd is not None:
            return usage.reported_cost_usd
        chat = _lookup(self.models, usage.model)
        if chat is not None:
            key, price = chat
            rates = price.rates or (price.off_peak if self.is_off_peak(now) else price.peak)
            if rates is None:
                raise PricesIncomplete([key])
            miss, hit, out = rates.input_cache_miss, rates.input_cache_hit, rates.output
            if miss is None or hit is None or out is None:
                raise PricesIncomplete(rates.missing(key))
            cached = min(usage.cached_input_tokens, usage.input_tokens)
            return (
                (usage.input_tokens - cached) * miss + cached * hit + usage.output_tokens * out
            ) / TOKENS_PER_RATE
        embedding = _lookup(self.embeddings, usage.model)
        if embedding is not None:
            key, rate = embedding
            if rate is None:
                raise PricesIncomplete([f"embeddings.{key}"])
            return usage.input_tokens * rate / TOKENS_PER_RATE
        if usage.input_tokens == 0 and usage.output_tokens == 0:
            return 0.0
        raise UnpricedUsage(usage.model)


def is_off_peak(now: datetime, table: PriceTable) -> bool:
    """Whether ``now`` falls inside the table's off-peak window."""
    return table.is_off_peak(now)


def seconds_until_off_peak(now: datetime, table: PriceTable) -> float:
    """Seconds until the table's off-peak window next opens; ``0`` when it is open."""
    return table.seconds_until_off_peak(now)


__all__ = [
    "PRICES_PATH",
    "ModelPrice",
    "OffPeakWindow",
    "PeakHours",
    "PriceTable",
    "PricesIncomplete",
    "Rates",
    "UnpricedUsage",
    "is_off_peak",
    "seconds_until_off_peak",
]
