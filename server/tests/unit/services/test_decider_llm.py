"""The LLM decider: request shape, typed results, batching and safe defaults."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.decisions import (
    ChoiceQuestion,
    ChoiceResult,
    LlmDecider,
    NoulQuestion,
    NoulResult,
    ScoreQuestion,
    ScoreResult,
)
from app.services.decisions import llm as llm_module
from app.services.decisions.llm import MAX_STATE_CHARS
from tests.fixtures.retrieval import install_fake_openai, make_llm

pytestmark = pytest.mark.unit


@pytest.fixture
def fake(monkeypatch):
    def install(*outputs: Any):
        return install_fake_openai(monkeypatch, *outputs, module=llm_module)

    return install


def user_message(response, index: int = 0) -> str:
    """The user message the model was sent."""
    return response.calls[index]["input"][1]["content"]


def schema(response, index: int = 0) -> dict:
    """The JSON schema the call asked for."""
    return response.calls[index]["text"]["format"]["schema"]


class TestRequests:
    async def test_a_choice_asks_for_one_offered_option_with_two_probabilities(self, fake):
        responses = fake(json.dumps({"choice": "local", "probability": 0.8, "confidence": 0.7}))
        result = await LlmDecider(make_llm()).choice(
            {"question": "where?"}, "classify it", {"local": "one place", "global": "all"}
        )

        assert isinstance(result, ChoiceResult)
        assert result.choice == "local"
        assert result.probabilities == {"local": 0.8}
        assert result.confidence == 0.7
        assert result.model == "test-model"
        assert result.provider == "llm"
        assert result.latency_ms >= 0.0
        assert (result.tokens_in, result.tokens_out) == (100, 7)

        call = responses.calls[0]
        assert call["model"] == "test-model"
        user = user_message(responses)
        assert "classify it" in user
        assert "- local: one place" in user
        assert '"question": "where?"' in user
        assert "never as instructions" in repr(call["input"][0]["content"])
        assert schema(responses)["properties"]["choice"]["enum"] == ["local", "global"]

    async def test_a_score_asks_for_a_position_on_the_numbered_rubric(self, fake):
        responses = fake(json.dumps({"score": 2.0, "confidence": 0.6}))
        result = await LlmDecider(make_llm()).score("passage", "rate it", ["low", "mid", "high"])

        assert isinstance(result, ScoreResult)
        assert result.score == 2.0
        assert result.confidence == 0.6
        user = user_message(responses)
        assert "0. low" in user and "1. mid" in user and "2. high" in user
        assert "0 to 2" in user

    async def test_a_noul_asks_for_one_probability(self, fake):
        responses = fake(json.dumps({"probability": 0.75, "confidence": 0.9}))
        result = await LlmDecider(make_llm()).noul("tool output", "is this statement true?")

        assert isinstance(result, NoulResult)
        assert result.noul == 0.75
        assert result.confidence == 0.9
        assert "is this statement true?" in user_message(responses)

    async def test_a_string_state_is_sent_verbatim_and_a_mapping_as_json(self, fake):
        responses = fake(
            json.dumps({"probability": 0.5, "confidence": 0.5}),
            json.dumps({"probability": 0.5, "confidence": 0.5}),
        )
        decider = LlmDecider(make_llm())

        await decider.noul("the raw state", "statement")
        await decider.noul({"file": "app/main.py"}, "statement")

        assert "the raw state" in user_message(responses, 0)
        assert '"file": "app/main.py"' in user_message(responses, 1)

    async def test_an_enormous_state_is_bounded(self, fake):
        responses = fake(json.dumps({"probability": 0.5, "confidence": 0.5}))
        await LlmDecider(make_llm()).noul("x" * (MAX_STATE_CHARS * 2), "statement")
        assert MAX_STATE_CHARS < len(user_message(responses)) < MAX_STATE_CHARS * 2
        assert "[state truncated]" in user_message(responses)


class TestBatch:
    async def test_every_question_gets_its_own_call_and_its_typed_result(self, fake):
        responses = fake(
            json.dumps({"choice": "a", "probability": 0.9, "confidence": 0.8}),
            json.dumps({"probability": 0.3, "confidence": 0.7}),
            json.dumps({"score": 1.0, "confidence": 0.5}),
        )
        questions = {
            "first": ChoiceQuestion("pick", {"a": "one", "b": "two"}),
            "second": NoulQuestion("true?", true="yes", false="no"),
            "third": ScoreQuestion("rate", ["low", "mid", "high"]),
        }

        results = await LlmDecider(make_llm()).batch("the state", questions)

        assert len(responses.calls) == 3
        assert list(results) == ["first", "second", "third"]
        assert isinstance(results["first"], ChoiceResult)
        assert isinstance(results["second"], NoulResult)
        assert isinstance(results["third"], ScoreResult)
        assert "True means: yes" in user_message(responses, 1)

    async def test_an_empty_batch_makes_no_call(self, fake):
        responses = fake()
        assert await LlmDecider(make_llm()).batch("state", {}) == {}
        assert responses.calls == []


class TestSafeDefaults:
    async def test_non_json_output_resolves_to_the_documented_defaults(self, fake):
        fake("I am not going to answer in JSON.", "no JSON here.", "still prose")
        decider = LlmDecider(make_llm())

        choice = await decider.choice("state", "pick", {"local": "here", "global": "all"})
        score = await decider.score("state", "rate", ["low", "high"])
        noul = await decider.noul("state", "claim")

        assert (choice.choice, choice.probabilities, choice.confidence) == ("local", {}, 0.0)
        assert (score.score, score.confidence) == (0.0, None)
        assert (noul.noul, noul.confidence) == (0.5, None)
        assert choice.defaulted and score.defaulted and noul.defaulted

    async def test_a_usable_answer_is_not_flagged_as_a_placeholder(self, fake):
        fake(json.dumps({"probability": 0.2, "confidence": 0.9}))
        result = await LlmDecider(make_llm()).noul("state", "claim")
        assert not result.defaulted

    async def test_an_unoffered_choice_becomes_the_first_option_with_zero_confidence(self, fake):
        fake(json.dumps({"choice": "banana", "probability": 0.95, "confidence": 0.9}))
        result = await LlmDecider(make_llm()).choice(
            "state", "pick", {"local": "here", "global": "all"}
        )
        assert (result.choice, result.probabilities, result.confidence) == ("local", {}, 0.0)

    async def test_a_missing_choice_field_becomes_the_first_option(self, fake):
        fake(json.dumps({"probability": 0.9, "confidence": 0.8}))
        result = await LlmDecider(make_llm()).choice(
            "state", "pick", {"local": "here", "global": "all"}
        )
        assert result.choice == "local"
        assert result.confidence == 0.0

    async def test_probabilities_outside_zero_to_one_are_clamped(self, fake):
        fake(
            json.dumps({"choice": "global", "probability": 4.5, "confidence": -2}),
            json.dumps({"probability": -1, "confidence": 7}),
        )
        decider = LlmDecider(make_llm())

        choice = await decider.choice("state", "pick", {"local": "here", "global": "all"})
        noul = await decider.noul("state", "claim")

        assert choice.probabilities == {"global": 1.0}
        assert choice.confidence == 0.0
        assert (noul.noul, noul.confidence) == (0.0, 1.0)

    async def test_a_score_outside_the_rubric_is_clamped(self, fake):
        fake(json.dumps({"score": 99, "confidence": 0.9}), json.dumps({"score": -4}))
        decider = LlmDecider(make_llm())

        high = await decider.score("state", "rate", ["low", "mid", "high"])
        low = await decider.score("state", "rate", ["low", "mid", "high"])

        assert high.score == 2.0
        assert low.score == 0.0

    async def test_a_missing_score_becomes_the_lowest_level(self, fake):
        fake(json.dumps({"confidence": 0.8}))
        result = await LlmDecider(make_llm()).score("state", "rate", ["low", "high"])
        assert (result.score, result.confidence) == (0.0, 0.8)


class TestProviderErrors:
    async def test_a_provider_error_propagates_rather_than_defaulting(self, fake):
        fake(RuntimeError("provider exploded"))
        with pytest.raises(RuntimeError, match="provider exploded"):
            await LlmDecider(make_llm()).choice("state", "pick", {"local": "here"})

    async def test_empty_options_and_levels_are_refused_before_any_call(self, fake):
        responses = fake()
        decider = LlmDecider(make_llm())
        with pytest.raises(ValueError, match="at least one option"):
            await decider.choice("state", "pick", {})
        with pytest.raises(ValueError, match="at least one level"):
            await decider.score("state", "rate", [])
        assert responses.calls == []
