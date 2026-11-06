"""The fallback between Jev and the LLM: one event per run, never a failed request."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import (
    DECISIONS_URL,
    ChoiceResult,
    DeciderUnavailable,
    DecisionError,
    FallbackDecider,
    JevDecider,
    LlmDecider,
    NoulResult,
    ScoreResult,
    get_decider,
)
from app.services.decisions import jev as jev_module
from app.services.decisions import llm as llm_module
from app.services.decisions.openrouter import JEV_MODEL, NoulQuestion
from tests.fixtures.retrieval import RecordingEmit, make_llm

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")


class StubDecider:
    """A decider that answers immediately or raises a fixed error."""

    kind = "stub"

    def __init__(self, name: str, *, error: Exception | None = None) -> None:
        self.kind = name
        self.model_id = name
        self.error = error
        self.calls: list[str] = []

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error

    async def choice(self, state: Any, instructions: str, options: Any) -> ChoiceResult:
        self.calls.append("choice")
        self._maybe_fail()
        return ChoiceResult(
            choice=next(iter(options)),
            probabilities={next(iter(options)): 0.9},
            confidence=0.9,
            latency_ms=1.0,
            model=self.model_id,
            provider=self.model_id,
        )

    async def score(self, state: Any, instructions: str, levels: Any) -> ScoreResult:
        self.calls.append("score")
        self._maybe_fail()
        return ScoreResult(
            score=1.0, confidence=0.8, latency_ms=1.0, model=self.model_id, provider=self.model_id
        )

    async def noul(self, state: Any, instructions: str) -> NoulResult:
        self.calls.append("noul")
        self._maybe_fail()
        return NoulResult(
            noul=0.5, confidence=0.7, latency_ms=1.0, model=self.model_id, provider=self.model_id
        )

    async def batch(self, state: Any, questions: Any) -> dict[str, Any]:
        self.calls.append("batch")
        self._maybe_fail()
        return {
            name: NoulResult(noul=0.5, latency_ms=1.0, model=self.model_id, provider=self.model_id)
            for name in questions
        }


async def ask_all(decider: FallbackDecider) -> None:
    """One call of every primitive, as a run would make."""
    await decider.choice("state", "pick", {"local": "here"})
    await decider.score("state", "rate", ["low", "high"])
    await decider.noul("state", "claim")
    await decider.batch("state", {"q": NoulQuestion("claim", true="yes", false="no")})


class TestFallback:
    async def test_without_a_primary_every_call_uses_the_fallback(self):
        fallback = StubDecider("llm")
        events = RecordingEmit()
        decider = FallbackDecider(None, fallback, emit=events, unavailable="no key")

        await ask_all(decider)

        assert fallback.calls == ["choice", "score", "noul", "batch"]
        assert decider.degraded

    async def test_a_missing_primary_emits_exactly_one_degraded_event_per_run(self):
        events = RecordingEmit()
        decider = FallbackDecider(
            None, StubDecider("llm"), emit=events, unavailable="OPENROUTER_API_KEY is not set"
        )

        await ask_all(decider)

        assert events.degraded == [
            {
                "stage": "decisions",
                "decider": "jev",
                "fallback": "llm",
                "reason": "OPENROUTER_API_KEY is not set",
            }
        ]

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(httpx.Response(503, json={}), id="5xx"),
            pytest.param(httpx.Response(429, json={}), id="rate-limited"),
            pytest.param(httpx.Response(200, json={"nothing": 1}), id="malformed-body"),
        ],
    )
    @respx.mock
    async def test_a_failing_jev_request_still_returns_a_valid_result(self, response):
        respx.post(DECISIONS_URL).mock(return_value=response)
        events = RecordingEmit()
        decider = FallbackDecider(JevDecider(), StubDecider("llm"), emit=events)

        result = await decider.noul("state", "claim")

        assert isinstance(result, NoulResult)
        assert result.model == "llm"
        assert len(events.degraded) == 1

    @respx.mock
    async def test_a_jev_timeout_still_returns_a_valid_result(self):
        respx.post(DECISIONS_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
        events = RecordingEmit()
        decider = FallbackDecider(JevDecider(), StubDecider("llm"), emit=events)

        result = await decider.choice("state", "pick", {"local": "here"})

        assert isinstance(result, ChoiceResult)
        assert result.model == "llm"
        assert "timed out" in events.degraded[0]["reason"]

    async def test_a_failing_primary_degrades_once_not_per_decision(self):
        events = RecordingEmit()
        primary = StubDecider(
            "jev", error=DecisionError("OpenRouter failed (503)", reason="server")
        )
        fallback = StubDecider("llm")
        decider = FallbackDecider(primary, fallback, emit=events)

        await ask_all(decider)

        assert len(events.degraded) == 1
        assert "503" in events.degraded[0]["reason"]

    @pytest.mark.parametrize("reason", ["unauthorized", "out_of_credit", "timeout", "server"])
    async def test_an_outage_retires_the_primary_for_the_rest_of_the_run(self, reason):
        primary = StubDecider("jev", error=DecisionError("down", reason=reason))
        fallback = StubDecider("llm")
        decider = FallbackDecider(primary, fallback)

        await ask_all(decider)

        assert primary.calls == ["choice"]
        assert fallback.calls == ["choice", "score", "noul", "batch"]

    @pytest.mark.parametrize("reason", ["rate_limited", "malformed", "too_large", "bad_request"])
    async def test_a_per_request_failure_keeps_trying_the_primary(self, reason):
        events = RecordingEmit()
        primary = StubDecider("jev", error=DecisionError("once", reason=reason))
        decider = FallbackDecider(primary, StubDecider("llm"), emit=events)

        await ask_all(decider)

        assert primary.calls == ["choice", "score", "noul", "batch"]
        assert len(events.degraded) == 1

    async def test_a_working_primary_answers_and_emits_nothing(self):
        events = RecordingEmit()
        primary = StubDecider("jev")
        fallback = StubDecider("llm")
        decider = FallbackDecider(primary, fallback, emit=events)

        result = await decider.choice("state", "pick", {"local": "here"})

        assert result.model == "jev"
        assert fallback.calls == []
        assert events.degraded == []
        assert not decider.degraded

    async def test_every_primitive_returns_the_fallbacks_typed_result(self):
        decider = FallbackDecider(
            StubDecider("jev", error=RuntimeError("down")), StubDecider("llm")
        )

        assert isinstance(await decider.choice("s", "i", {"a": "x"}), ChoiceResult)
        assert isinstance(await decider.score("s", "i", ["a", "b"]), ScoreResult)
        assert isinstance(await decider.noul("s", "i"), NoulResult)
        batch = await decider.batch("s", {"q": NoulQuestion("c", true="t", false="f")})
        assert isinstance(batch["q"], NoulResult)

    async def test_a_failing_fallback_still_raises(self):
        decider = FallbackDecider(
            StubDecider("jev", error=RuntimeError("primary")),
            StubDecider("llm", error=RuntimeError("secondary")),
        )
        with pytest.raises(RuntimeError, match="secondary"):
            await decider.noul("state", "claim")

    async def test_a_failing_emitter_does_not_break_the_decision(self):
        async def broken(event: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("redis is down")

        decider = FallbackDecider(None, StubDecider("llm"), emit=broken, unavailable="no key")
        assert (await decider.noul("state", "claim")).noul == 0.5

    def test_the_model_id_names_the_preferred_decider(self):
        assert FallbackDecider(StubDecider("jev"), StubDecider("llm")).model_id == "jev"
        assert FallbackDecider(None, StubDecider("llm")).model_id == "llm"


class TestConstruction:
    def test_llm_is_the_stand_in_directly(self):
        decider = get_decider("llm", llm=make_llm())
        assert isinstance(decider, LlmDecider)
        assert decider.model_id == "test-model"

    def test_llm_without_any_credential_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "AI_API_KEY", "")
        with pytest.raises(DeciderUnavailable, match="no model credential"):
            get_decider("llm")

    def test_jev_with_a_key_prefers_jev(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")
        decider = get_decider("jev", llm=make_llm())
        assert isinstance(decider, FallbackDecider)
        assert decider.model_id == JEV_MODEL

    def test_jev_without_a_key_is_the_llm_behind_the_fallback(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        decider = get_decider("jev", llm=make_llm())
        assert isinstance(decider, FallbackDecider)
        assert decider.model_id == "test-model"
        assert decider.kind == "jev"

    def test_jev_with_a_key_and_no_credential_for_the_stand_in_still_works(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")
        monkeypatch.setattr(settings, "AI_API_KEY", "")
        decider = get_decider("jev")
        assert isinstance(decider, JevDecider)

    def test_jev_with_neither_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(settings, "AI_API_KEY", "")
        with pytest.raises(DeciderUnavailable, match="OPENROUTER_API_KEY"):
            get_decider("jev")

    def test_an_unknown_kind_is_unavailable(self):
        with pytest.raises(DeciderUnavailable, match="not available"):
            get_decider("cohere", llm=make_llm())

    def test_the_factory_builds_the_real_classes(self, monkeypatch):
        """The lazy imports inside the factory resolve to these modules' classes."""
        assert jev_module.JevDecider is JevDecider
        assert llm_module.LlmDecider is LlmDecider
