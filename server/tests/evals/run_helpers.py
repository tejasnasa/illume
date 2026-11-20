"""Scripted stand-ins shared by the generation-pass tests."""

from __future__ import annotations

import copy
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from app.services.decisions.base import ChoiceResult
from evals.arms import Arm
from evals.gold.schema import GoldItem, make_item
from evals.run.pricing import PriceTable
from evals.run.records import Generation, Usage
from tests.fixtures.agent_run import ScriptedModel, build_response


class PlainModel(ScriptedModel):
    """A scripted model that answers a non-streaming call with a whole response.

    A streaming call still gets the scripted event stream. ``cached_tokens`` is reported as
    ``usage.input_tokens_details.cached_tokens`` on every plain response, which the plain
    scripted response does not otherwise carry.
    """

    def __init__(self, *args: Any, cached_tokens: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cached_tokens = cached_tokens

    async def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return await super().create(**kwargs)
        self.requests.append(copy.deepcopy(kwargs))
        reply = self._script.pop(0)
        if reply.error is not None:
            raise reply.error
        response = build_response(reply)
        assert response.usage is not None
        response.usage.input_tokens_details.cached_tokens = self.cached_tokens
        return response


def make_gold_item(question: str = "Where is the password check?", **overrides: Any) -> GoldItem:
    """A small hand-written gold item."""
    fields: dict[str, Any] = {
        "repo": "example/sample",
        "base_commit": "b" * 40,
        "family": "hand",
        "template": "hand.flow",
        "question": question,
        "question_seed": question,
        "gold_files": ("app/auth/security.py",),
    }
    fields.update(overrides)
    return make_item(**fields)


class RouteDecider:
    """A decider that answers every routing question from a script.

    Args:
        route: The route value it picks.
        probability: The probability it reports for that route.
        error: Raised from ``choice`` instead of answering.
        delay: Seconds to wait before answering, to exercise the timeout.
    """

    kind = "fake"
    model_id = "fake-router"

    def __init__(
        self,
        route: str = "local",
        probability: float = 0.95,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.route = route
        self.probability = probability
        self.error = error
        self.delay = delay

    async def choice(self, state: Any, instructions: str, options: Any) -> ChoiceResult:
        import asyncio

        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return ChoiceResult(
            choice=self.route,
            probabilities={self.route: self.probability},
            confidence=self.probability,
            latency_ms=12.0,
            model=self.model_id,
            provider="fake",
            cost=0.00004,
            request_id="req-1",
            tokens_in=300,
            tokens_out=5,
        )


def client_with(**parts: Any) -> Any:
    """A client factory returning a namespace of the given parts, such as ``responses=model``."""

    def factory(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(**parts)

    return factory


# --- the generation runner -------------------------------------------------------------

GENERATOR = "deepseek-v4-1-flash-1017"
EMBEDDING = "text-embedding-3-small"

# Every call in the runner tests uses 100k cache-miss input tokens at $1.00 per 1M at peak,
# so a call costs $0.10 at peak and $0.05 off-peak.
CALL_TOKENS = 100_000
PEAK_CALL_COST = 0.10
OFF_PEAK_CALL_COST = 0.05


def complete_table(**overrides: Any) -> PriceTable:
    """A price table with every rate filled in, for the runner's tests.

    Peak rates are $1.00 cache-miss, $0.10 cache-hit and $2.00 output per 1M tokens; off-peak
    rates are half of that. The off-peak window is 16:30 to 00:30 UTC.
    """
    fields: dict[str, Any] = {
        "version": "test-1",
        "as_of": "2026-11-01",
        "verified": True,
        "off_peak": {"start_utc": "16:30", "end_utc": "00:30"},
        "models": {
            GENERATOR: {
                "peak": {"input_cache_miss": 1.0, "input_cache_hit": 0.1, "output": 2.0},
                "off_peak": {"input_cache_miss": 0.5, "input_cache_hit": 0.05, "output": 1.0},
            },
            "gpt-6-luna": {
                "rates": {"input_cache_miss": 1.0, "input_cache_hit": 0.1, "output": 2.0}
            },
            "test-model": {
                "rates": {"input_cache_miss": 1.0, "input_cache_hit": 0.1, "output": 2.0}
            },
        },
        "embeddings": {EMBEDDING: 0.02},
    }
    fields.update(overrides)
    return PriceTable.model_validate(fields)


def flat_table() -> PriceTable:
    """A table whose generator costs the same at any hour, for tests that cannot fix the clock."""
    rates = {"input_cache_miss": 1.0, "input_cache_hit": 0.1, "output": 2.0}
    return complete_table(models={GENERATOR: {"rates": rates}, "test-model": {"rates": rates}})


def make_items(count: int, *, prefix: str = "Where is feature") -> list[GoldItem]:
    """Gold items with distinct ids and questions."""
    return [
        make_gold_item(f"{prefix} {n}?", question_seed=f"seed {n}", gold_files=(f"app/f{n}.py",))
        for n in range(count)
    ]


def usage_call(kind: str = "generate", model: str = GENERATOR, tokens: int = CALL_TOKENS) -> Usage:
    """One metered call of ``tokens`` cache-miss input tokens."""
    return Usage(provider="deepseek", model=model, kind=kind, input_tokens=tokens)


class Crash(BaseException):
    """Stops a run the way a killed process would; nothing in the runner catches it."""


class ScriptedExecutor:
    """An executor that answers every pair from a script and counts its calls.

    Args:
        fail: ``(item_id, arm_name)`` to how many leading attempts return an error record.
        raise_for: ``(item_id, arm_name)`` pairs whose calls raise instead of returning.
        crash_after: Raise :class:`Crash` on the call after this many calls have been made.
        usages: What a successful call used; one standard call by default.
        on_call: Runs at the start of every call, with the item, arm and repeat.

    Attributes:
        calls: ``(item_id, arm_name, repeat)`` for every call, in order.
    """

    def __init__(
        self,
        *,
        fail: dict[tuple[str, str], int] | None = None,
        raise_for: set[tuple[str, str]] | None = None,
        crash_after: int | None = None,
        usages: Callable[[GoldItem, Arm], list[Usage]] | None = None,
        on_call: Callable[[GoldItem, Arm, int], Any] | None = None,
    ) -> None:
        self.fail = dict(fail or {})
        self.raise_for = set(raise_for or ())
        self.crash_after = crash_after
        self.usages = usages
        self.on_call = on_call
        self.calls: list[tuple[str, str, int]] = []

    async def __call__(self, item: GoldItem, arm: Arm, repeat: int) -> Generation:
        if self.crash_after is not None and len(self.calls) >= self.crash_after:
            raise Crash()
        self.calls.append((item.id, arm.name, repeat))
        if self.on_call is not None:
            self.on_call(item, arm, repeat)
        pair = (item.id, arm.name)
        if pair in self.raise_for:
            raise RuntimeError("provider down")
        common: dict[str, Any] = {
            "record_key": "overwritten-by-the-runner",
            "item_id": item.id,
            "arm": arm.name,
            "repeat": repeat,
            "config_hash": arm.config_hash(),
            "model": arm.model,
        }
        used = self.usages(item, arm) if self.usages else [usage_call()]
        if self.fail.get(pair, 0) > 0:
            self.fail[pair] -= 1
            return Generation(**common, status="error", error="boom", usages=used)
        return Generation(**common, answer=f"answer to {item.question}", usages=used)
