"""The invariants both deciders guarantee, checked against random and malformed answers."""

from __future__ import annotations

import json
import random
from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import (
    DECISIONS_URL,
    ChoiceResult,
    DecisionError,
    JevDecider,
    LlmDecider,
    NoulResult,
    ScoreResult,
    state_hash,
)
from app.services.decisions import llm as llm_module
from tests.fixtures.retrieval import install_fake_openai, make_llm

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")


def options(rng: random.Random) -> dict[str, str]:
    """A random set of two to four options."""
    count = rng.randint(2, 4)
    return {f"option{index}": f"description {index}" for index in range(count)}


def levels(rng: random.Random) -> list[str]:
    """A random rubric of two to five levels."""
    return [f"level {index}" for index in range(rng.randint(2, 5))]


def jev_answers(request: httpx.Request, rng: random.Random) -> dict[str, Any]:
    """Random but legal answers, some with a choice the caller did not offer."""
    questions = json.loads(request.content)["questions"]
    answers: dict[str, Any] = {}
    for name, question in questions.items():
        if question["type"] == "choice":
            offered = list(question["criteria"])
            answers[name] = {
                "choice": rng.choice([*offered, "not_an_option"]),
                "probabilities": {option: rng.uniform(-2, 3) for option in offered},
                "confidence": rng.uniform(-1, 2),
            }
        elif question["type"] == "score":
            answers[name] = {
                "score": rng.uniform(-5, 10),
                "probabilities": {str(level): rng.uniform(-2, 2) for level in range(4)},
                "confidence": rng.uniform(-1, 2),
            }
        else:
            answers[name] = {"noul": rng.uniform(-2, 3)}
    return answers


class TestRandomAnswers:
    @respx.mock
    async def test_jev_always_stays_inside_the_contract(self):
        rng = random.Random(17)
        respx.post(DECISIONS_URL).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={
                    "answers": jev_answers(request, rng),
                    "model": "typesafe/jev-1.13-20260917",
                    "provider": "typesafe",
                    "usage": {"cost": 0.001},
                    "id": "dec_random",
                },
            )
        )
        decider = JevDecider()

        for _ in range(25):
            offered = options(rng)
            choice = await decider.choice("state", "pick", offered)
            assert isinstance(choice, ChoiceResult)
            assert choice.choice in offered
            assert all(0.0 <= value <= 1.0 for value in choice.probabilities.values())
            assert choice.confidence is None or 0.0 <= choice.confidence <= 1.0

            rubric = levels(rng)
            score = await decider.score("state", "rate", rubric)
            assert isinstance(score, ScoreResult)
            assert 0.0 <= score.score <= len(rubric) - 1
            assert all(0.0 <= value <= 1.0 for value in score.probabilities.values())

            probability = await decider.noul("state", "claim")
            assert isinstance(probability, NoulResult)
            assert 0.0 <= probability.noul <= 1.0

    async def test_llm_always_stays_inside_the_contract(self, monkeypatch):
        rng = random.Random(23)

        def choice_output() -> str:
            if rng.random() < 0.15:
                return rng.choice(["no json", "{}", "[]"])
            return json.dumps(
                {
                    "choice": rng.choice(["option0", "option1", "not_an_option"]),
                    "probability": rng.uniform(-3, 4),
                    "confidence": rng.uniform(-3, 4),
                }
            )

        def score_output() -> str:
            if rng.random() < 0.15:
                return rng.choice(["no json", "{}", "[]"])
            return json.dumps({"score": rng.uniform(-20, 20), "confidence": rng.uniform(-3, 4)})

        def noul_output() -> str:
            if rng.random() < 0.15:
                return rng.choice(["no json", "{}", "[]"])
            return json.dumps({"probability": rng.uniform(-3, 4), "confidence": rng.uniform(-3, 4)})

        outputs = [
            output for _ in range(25) for output in (choice_output(), score_output(), noul_output())
        ]
        install_fake_openai(monkeypatch, *outputs, module=llm_module)
        decider = LlmDecider(make_llm())
        offered = {"option0": "first", "option1": "second"}

        for _ in range(25):
            choice = await decider.choice("state", "pick", offered)
            assert choice.choice in offered
            assert all(0.0 <= value <= 1.0 for value in choice.probabilities.values())
            assert choice.confidence is None or 0.0 <= choice.confidence <= 1.0

            score = await decider.score("state", "rate", ["a", "b", "c"])
            assert 0.0 <= score.score <= 2.0

            probability = await decider.noul("state", "claim")
            assert 0.0 <= probability.noul <= 1.0


class TestSharedContract:
    @respx.mock
    async def test_both_deciders_return_the_same_result_types_for_the_same_inputs(
        self, monkeypatch
    ):
        respx.post(DECISIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "answers": {
                        "choice": {
                            "choice": "a",
                            "probabilities": {"a": 0.8, "b": 0.2},
                            "confidence": 0.9,
                        },
                        "score": {"score": 1.0, "probabilities": {}, "confidence": 0.7},
                        "noul": {"noul": 0.6},
                    },
                    "model": "typesafe/jev-1.13-20260917",
                    "provider": "typesafe",
                    "usage": {"cost": 0.001},
                    "id": "dec_contract",
                },
            )
        )
        install_fake_openai(
            monkeypatch,
            json.dumps({"choice": "a", "probability": 0.8, "confidence": 0.9}),
            json.dumps({"score": 1.0, "confidence": 0.7}),
            json.dumps({"probability": 0.6, "confidence": 0.8}),
            module=llm_module,
        )

        for decider in (JevDecider(), LlmDecider(make_llm())):
            assert isinstance(
                await decider.choice("state", "pick", {"a": "first", "b": "second"}),
                ChoiceResult,
            )
            assert isinstance(await decider.score("state", "rate", ["a", "b"]), ScoreResult)
            assert isinstance(await decider.noul("state", "claim"), NoulResult)


class TestStateHash:
    def test_a_string_hashes_by_its_content(self):
        assert state_hash("the same") == state_hash("the same")
        assert state_hash("the same") != state_hash("something else")

    def test_a_mapping_hashes_canonically(self):
        assert state_hash({"a": 1, "b": 2}) == state_hash({"b": 2, "a": 1})

    def test_an_unserialisable_value_still_hashes(self):
        assert len(state_hash({"when": object()})) == 64


def test_a_malformed_jev_answer_raises_rather_than_returning_a_wrong_type():
    """A body whose answer is the wrong primitive is a client bug, not a decision."""
    assert issubclass(DecisionError, RuntimeError)
