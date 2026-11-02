"""The OpenRouter Decisions client: request shape, typed answers and error mapping."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import (
    DECISIONS_URL,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionError,
    DecisionUnavailable,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    submit,
)

pytestmark = pytest.mark.unit

MODEL = "typesafe/jev-1.14"


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")


def response_body(answers: dict, **overrides) -> dict:
    body = {
        "answers": answers,
        "model": "typesafe/jev-1.13-20260917",
        "provider": "typesafe",
        "usage": {"cost": 0.0021, "input_tokens": 120, "output_tokens": 9},
        "id": "dec_123",
    }
    body.update(overrides)
    return body


class TestRequest:
    @respx.mock
    async def test_posts_the_documented_body_with_a_bearer_key(self):
        route = respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(
                200, json=response_body({"q": {"noul": 0.75, "confidence": 0.9}})
            )
        )
        await submit(
            {"file": "a.py"},
            {"q": NoulQuestion("Is it a test?", true="It is.", false="It is not.")},
            model=MODEL,
        )

        request = route.calls.last.request
        assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
        assert request.headers["authorization"] == "Bearer or-test-key"
        assert json.loads(request.content) == {
            "model": MODEL,
            "state": {"file": "a.py"},
            "questions": {
                "q": {
                    "type": "noul",
                    "instructions": "Is it a test?",
                    "criteria": {"true": "It is.", "false": "It is not."},
                }
            },
        }

    @respx.mock
    async def test_session_id_is_sent_only_when_given(self):
        route = respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(200, json=response_body({"q": {"noul": 0.5}}))
        )
        question = {"q": NoulQuestion("?", true="t", false="f")}

        await submit("state", question, model=MODEL)
        assert "session_id" not in json.loads(route.calls.last.request.content)

        await submit("state", question, model=MODEL, session_id="run-7")
        assert json.loads(route.calls.last.request.content)["session_id"] == "run-7"

    async def test_a_missing_key_raises_before_any_request(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        with respx.mock:  # any request would fail the test as an unmocked call
            with pytest.raises(DecisionUnavailable, match="OPENROUTER_API_KEY"):
                await submit("s", {"q": NoulQuestion("?", true="t", false="f")}, model=MODEL)

    async def test_no_questions_is_refused(self):
        with pytest.raises(ValueError, match="at least one question"):
            await submit("s", {}, model=MODEL)


class TestAnswers:
    @respx.mock
    async def test_score_answers_parse_into_levels(self):
        respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json=response_body(
                    {
                        "p0": {
                            "score": 2.4,
                            "probabilities": {"0": 0.05, "1": 0.1, "2": 0.35, "3": 0.5},
                            "legend": ["unrelated", "mentions", "partial", "direct"],
                            "confidence": 0.8,
                        }
                    }
                ),
            )
        )
        result = await submit("s", {"p0": ScoreQuestion("rate", ["a", "b", "c", "d"])}, model=MODEL)

        answer = result.answers["p0"]
        assert isinstance(answer, ScoreAnswer)
        assert answer.score == pytest.approx(2.4)
        assert answer.probabilities == {0: 0.05, 1: 0.1, 2: 0.35, 3: 0.5}
        assert answer.confidence == pytest.approx(0.8)
        assert answer.legend == ["unrelated", "mentions", "partial", "direct"]

    @respx.mock
    async def test_choice_answers_parse_into_options(self):
        route = respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json=response_body(
                    {
                        "route": {
                            "choice": "search",
                            "probabilities": {"search": 0.7, "answer": 0.3},
                            "confidence": 0.6,
                        }
                    }
                ),
            )
        )
        result = await submit(
            "s",
            {"route": ChoiceQuestion("What next?", {"search": "look more", "answer": "reply now"})},
            model=MODEL,
        )

        answer = result.answers["route"]
        assert isinstance(answer, ChoiceAnswer)
        assert answer.choice == "search"
        assert answer.probabilities == {"search": 0.7, "answer": 0.3}
        assert answer.confidence == pytest.approx(0.6)
        sent = json.loads(route.calls.last.request.content)["questions"]["route"]
        assert sent["criteria"] == {"search": "look more", "answer": "reply now"}

    @respx.mock
    async def test_noul_answers_parse_into_a_probability(self):
        respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(200, json=response_body({"claim": {"noul": 0.125}}))
        )
        result = await submit(
            "s", {"claim": NoulQuestion("Supported?", true="yes", false="no")}, model=MODEL
        )

        answer = result.answers["claim"]
        assert isinstance(answer, NoulAnswer)
        assert answer.noul == pytest.approx(0.125)

    @respx.mock
    async def test_mixed_question_types_in_one_request(self):
        route = respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json=response_body(
                    {
                        "a": {"score": 1.0},
                        "b": {"choice": "x", "probabilities": {"x": 1.0}},
                        "c": {"noul": 0.0},
                    }
                ),
            )
        )
        result = await submit(
            "s",
            {
                "a": ScoreQuestion("rate", ["lo", "hi"]),
                "b": ChoiceQuestion("pick", {"x": "first"}),
                "c": NoulQuestion("true?", true="t", false="f"),
            },
            model=MODEL,
        )

        assert [type(result.answers[name]) for name in "abc"] == [
            ScoreAnswer,
            ChoiceAnswer,
            NoulAnswer,
        ]
        assert len(json.loads(route.calls.last.request.content)["questions"]) == 3

    @respx.mock
    async def test_the_snapshot_cost_and_raw_body_are_kept(self):
        body = response_body({"q": {"noul": 0.5}})
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = await submit("s", {"q": NoulQuestion("?", true="t", false="f")}, model=MODEL)

        assert result.model == "typesafe/jev-1.13-20260917"
        assert result.provider == "typesafe"
        assert result.cost == pytest.approx(0.0021)
        assert (result.input_tokens, result.output_tokens) == (120, 9)
        assert result.id == "dec_123"
        assert result.raw == body


class TestErrors:
    @pytest.mark.parametrize(
        ("status", "reason", "fragment"),
        [
            (400, "bad_request", "malformed"),
            (401, "unauthorized", "API key"),
            (402, "out_of_credit", "out of credit"),
            (413, "too_large", "too large"),
            (429, "rate_limited", "rate-limited"),
            (500, "server", "failed to answer"),
            (503, "server", "failed to answer"),
        ],
    )
    @respx.mock
    async def test_status_codes_map_to_a_clear_error(self, status, reason, fragment):
        respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(status, json={"error": {"message": "because"}})
        )
        with pytest.raises(DecisionError, match=fragment) as raised:
            await submit("s", {"q": NoulQuestion("?", true="t", false="f")}, model=MODEL)

        assert raised.value.reason == reason
        assert raised.value.status_code == status
        assert "because" in str(raised.value)

    @respx.mock
    async def test_a_timeout_is_a_timeout_error(self):
        respx.post(DECISIONS_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(DecisionError, match="timed out") as raised:
            await submit("s", {"q": NoulQuestion("?", true="t", false="f")}, model=MODEL)
        assert raised.value.reason == "timeout"

    @respx.mock
    async def test_a_connection_failure_is_a_transport_error(self):
        respx.post(DECISIONS_URL).mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(DecisionError, match="ConnectError") as raised:
            await submit("s", {"q": NoulQuestion("?", true="t", false="f")}, model=MODEL)
        assert raised.value.reason == "transport"

    @pytest.mark.parametrize(
        "body",
        [
            "not json at all",
            [],
            {"model": "m"},
            {"answers": {}, "model": "m"},
            {"answers": {"q": {"noul": "high"}}, "model": "m"},
            {"answers": {"q": "nope"}, "model": "m"},
            {"answers": {"q": {"noul": 0.5}}},
        ],
        ids=[
            "not-json",
            "not-an-object",
            "no-answers",
            "missing-answer",
            "non-numeric",
            "answer-not-object",
            "no-model",
        ],
    )
    @respx.mock
    async def test_malformed_bodies_raise(self, body):
        content = body if isinstance(body, str) else json.dumps(body)
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(200, content=content))
        with pytest.raises(DecisionError) as raised:
            await submit("s", {"q": NoulQuestion("?", true="t", false="f")}, model=MODEL)
        assert raised.value.reason == "malformed"
