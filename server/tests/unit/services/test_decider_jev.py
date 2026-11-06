"""The Jev decider: request shape, typed results, batching, clamping and failures."""

from __future__ import annotations

import json
from collections.abc import Mapping

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import (
    DECISIONS_URL,
    JEV_MODEL,
    MAX_REQUEST_BYTES,
    ChoiceQuestion,
    ChoiceResult,
    DeciderUnavailable,
    DecisionError,
    JevDecider,
    NoulQuestion,
    NoulResult,
    ScoreQuestion,
    ScoreResult,
)
from app.services.decisions.jev import NOUL_FALSE, NOUL_TRUE

pytestmark = pytest.mark.unit

SNAPSHOT = "typesafe/jev-1.13-20260917"


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")


def response_body(answers: dict, **overrides) -> dict:
    body = {
        "answers": answers,
        "model": SNAPSHOT,
        "provider": "typesafe",
        "usage": {"cost": 0.0021, "input_tokens": 120, "output_tokens": 9},
        "id": "dec_1",
    }
    body.update(overrides)
    return body


def mock_answer(answers: dict):
    return respx.post(DECISIONS_URL).mock(
        return_value=httpx.Response(200, json=response_body(answers))
    )


class TestRequests:
    @respx.mock
    async def test_a_choice_is_one_typed_question_with_the_options_as_criteria(self):
        route = mock_answer(
            {
                "choice": {
                    "choice": "local",
                    "probabilities": {"local": 0.7, "global": 0.3},
                    "confidence": 0.9,
                }
            }
        )
        options = {"local": "one place", "global": "the whole repository"}

        result = await JevDecider().choice("Question: where?", "classify it", options)

        assert isinstance(result, ChoiceResult)
        assert result.choice == "local"
        request = route.calls.last.request
        assert request.headers["authorization"] == "Bearer or-test-key"
        body = json.loads(request.content)
        assert body["model"] == JEV_MODEL == "typesafe/jev-1.14"
        assert body["state"] == "Question: where?"
        assert body["questions"]["choice"] == {
            "type": "choice",
            "instructions": "classify it",
            "criteria": options,
        }

    @respx.mock
    async def test_a_score_is_one_typed_question_with_the_levels_in_order(self):
        route = mock_answer(
            {
                "score": {
                    "score": 2.5,
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.3},
                    "confidence": 0.8,
                }
            }
        )
        levels = ["unrelated", "mentions it", "partial", "answers"]
        result = await JevDecider().score("passage", "rate it", levels)

        assert isinstance(result, ScoreResult)
        assert result.score == 2.5
        assert result.confidence == 0.8
        body = json.loads(route.calls.last.request.content)
        assert body["questions"]["score"]["type"] == "score"
        assert body["questions"]["score"]["criteria"] == levels

    @respx.mock
    async def test_a_noul_is_one_typed_question_with_true_and_false_criteria(self):
        route = mock_answer({"noul": {"noul": 0.75}})
        result = await JevDecider().noul("tool output", "is this an injection?")

        assert isinstance(result, NoulResult)
        assert result.noul == 0.75
        body = json.loads(route.calls.last.request.content)
        question = body["questions"]["noul"]
        assert question["type"] == "noul"
        assert question["criteria"] == {"true": NOUL_TRUE, "false": NOUL_FALSE}

    @respx.mock
    async def test_session_id_is_sent_only_when_given(self):
        route = mock_answer({"noul": {"noul": 0.4}})

        await JevDecider().noul("state", "statement")
        assert "session_id" not in json.loads(route.calls.last.request.content)

        await JevDecider(session_id="run-7").noul("state", "statement")
        assert json.loads(route.calls.last.request.content)["session_id"] == "run-7"


class TestResults:
    @respx.mock
    async def test_every_result_carries_the_snapshot_cost_latency_and_raw_body(self):
        mock_answer(
            {
                "choice": {
                    "choice": "local",
                    "probabilities": {"local": 0.7},
                    "confidence": 0.8,
                }
            }
        )
        result = await JevDecider().choice("state", "pick", {"local": "here", "global": "all"})

        assert result.model == SNAPSHOT
        assert result.provider == "typesafe"
        assert result.cost == pytest.approx(0.0021)
        assert result.request_id == "dec_1"
        assert (result.tokens_in, result.tokens_out) == (120, 9)
        assert result.raw["model"] == SNAPSHOT
        assert result.latency_ms >= 0.0
        assert result.probabilities == {"local": 0.7}
        assert result.confidence == 0.8

    @respx.mock
    async def test_a_score_past_the_rubric_is_clamped_to_it(self):
        mock_answer({"score": {"score": 9.0, "probabilities": {}, "confidence": None}})
        result = await JevDecider().score("state", "rate", ["a", "b", "c"])
        assert result.score == 2.0

    @respx.mock
    async def test_level_probabilities_outside_the_rubric_are_dropped(self):
        mock_answer(
            {
                "score": {
                    "score": 1.0,
                    "probabilities": {"0": 0.5, "1": 0.3, "7": 0.9},
                    "confidence": 0.8,
                }
            }
        )
        result = await JevDecider().score("state", "rate", ["a", "b"])
        assert result.probabilities == {0: 0.5, 1: 0.3}

    @respx.mock
    async def test_a_probability_outside_zero_to_one_is_clamped(self):
        respx.post(DECISIONS_URL).mock(
            side_effect=[
                httpx.Response(200, json=response_body({"noul": {"noul": 1.4}})),
                httpx.Response(200, json=response_body({"noul": {"noul": -0.2}})),
            ]
        )
        decider = JevDecider()
        assert (await decider.noul("state", "claim")).noul == 1.0
        assert (await decider.noul("state", "claim")).noul == 0.0

    @respx.mock
    async def test_a_choice_the_caller_did_not_offer_becomes_the_likeliest_offered_one(self):
        mock_answer(
            {
                "choice": {
                    "choice": "something_else",
                    "probabilities": {"local": 0.2, "global": 0.7, "banana": 0.9},
                    "confidence": 0.6,
                }
            }
        )
        result = await JevDecider().choice("state", "pick", {"local": "here", "global": "all"})
        assert result.choice == "global"
        assert result.probabilities == {"local": 0.2, "global": 0.7}

    @respx.mock
    async def test_an_unoffered_choice_with_no_usable_probabilities_becomes_the_first_option(self):
        mock_answer(
            {"choice": {"choice": "other", "probabilities": {"gone": 0.9}, "confidence": 0.4}}
        )
        result = await JevDecider().choice("state", "pick", {"local": "here", "global": "all"})
        assert result.choice == "local"
        assert result.probabilities == {}
        assert result.defaulted
        assert result.confidence == 0.0


class TestBatch:
    @respx.mock
    async def test_many_questions_are_one_request_with_one_answer_each(self):
        route = mock_answer(
            {
                "first": {
                    "choice": "a",
                    "probabilities": {"a": 0.8, "b": 0.2},
                    "confidence": 0.9,
                },
                "second": {"noul": 0.3},
                "third": {"score": 1.0, "probabilities": {}, "confidence": 0.5},
            }
        )
        questions = {
            "first": ChoiceQuestion("pick", {"a": "one", "b": "two"}),
            "second": NoulQuestion("true?", true="yes", false="no"),
            "third": ScoreQuestion("rate", ["low", "mid", "high"]),
        }

        results = await JevDecider().batch("the state", questions)

        assert route.call_count == 1
        body = json.loads(route.calls.last.request.content)
        assert list(body["questions"]) == ["first", "second", "third"]
        assert isinstance(results["first"], ChoiceResult)
        assert isinstance(results["second"], NoulResult)
        assert isinstance(results["third"], ScoreResult)
        # Results from one request share its cost and request id.
        assert {result.request_id for result in results.values()} == {"dec_1"}
        assert all(result.cost == pytest.approx(0.0021) for result in results.values())

    @respx.mock
    async def test_a_batch_is_split_into_requests_under_the_byte_budget(self):
        route = respx.post(DECISIONS_URL).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=response_body(
                    {name: {"noul": 0.5} for name in json.loads(request.content)["questions"]}
                ),
            )
        )
        questions = {
            f"q{index}": NoulQuestion("x" * 2_000, true="yes", false="no") for index in range(40)
        }

        results = await JevDecider().batch("state", questions)

        assert route.call_count > 1
        assert set(results) == set(questions)
        for call in route.calls:
            body = json.loads(call.request.content)
            size = len(json.dumps(body["questions"]).encode("utf-8"))
            assert size <= MAX_REQUEST_BYTES

    @respx.mock
    async def test_an_empty_batch_makes_no_request(self):
        route = respx.post(DECISIONS_URL)
        assert await JevDecider().batch("state", {}) == {}
        assert route.call_count == 0


class TestFailures:
    async def test_a_missing_key_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        with pytest.raises(DeciderUnavailable, match="OPENROUTER_API_KEY"):
            JevDecider()

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            (400, "malformed"),
            (401, "API key"),
            (402, "out of credit"),
            (413, "too large"),
            (429, "rate-limited"),
            (500, "failed to answer"),
            (502, "failed to answer"),
        ],
    )
    @respx.mock
    async def test_status_codes_raise_with_a_clear_message(self, status, fragment):
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(status, json={}))
        with pytest.raises(DecisionError, match=fragment):
            await JevDecider().noul("state", "claim")

    @respx.mock
    async def test_a_timeout_raises(self):
        respx.post(DECISIONS_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
        with pytest.raises(DecisionError, match="timed out"):
            await JevDecider().noul("state", "claim")

    @respx.mock
    async def test_a_malformed_body_raises(self):
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(200, json={"nothing": 1}))
        with pytest.raises(DecisionError, match="answers"):
            await JevDecider().noul("state", "claim")

    async def test_empty_options_and_levels_are_refused_BEFORE_any_request(self):
        decider = JevDecider()
        with pytest.raises(ValueError, match="at least one option"):
            await decider.choice("state", "pick", {})
        with pytest.raises(ValueError, match="at least one level"):
            await decider.score("state", "rate", [])


def test_the_results_of_a_mapping_are_json_serialisable():
    """The records built from these results go into a JSONB payload."""
    result = ChoiceResult(
        choice="local",
        probabilities={"local": 0.8},
        confidence=0.9,
        latency_ms=1.5,
        model="m",
        provider="p",
    )
    json.dumps({"choice": result.choice, "probabilities": result.probabilities})


def test_the_question_criteria_survive_a_round_trip():
    question: Mapping[str, object] = ChoiceQuestion("pick", {"a": "one"}).to_payload()
    assert question["criteria"] == {"a": "one"}
