"""The planning decision and the relevance wording: thresholds, records and both decider paths."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import (
    DECISIONS_URL,
    RELEVANCE_LEVELS,
    ChoiceResult,
    DecisionRecord,
    JevDecider,
    LlmDecider,
    NoulResult,
    ScoreResult,
    decide_plan,
    state_hash,
)
from app.services.decisions import llm as llm_module
from app.services.decisions.points import relevance_instructions, relevance_state
from tests.fixtures.retrieval import install_fake_openai, make_llm

pytestmark = pytest.mark.unit


@dataclass
class Call:
    """One primitive call the fake decider saw."""

    primitive: str
    state: Any
    instructions: str
    options: dict[str, str] | None = None
    levels: list[str] | None = None


class FakeDecider:
    """Returns fixed answers and records what it was asked."""

    kind = "fake"
    model_id = "fake-model"

    def __init__(
        self,
        *,
        choice: str = "local",
        confidence: float | None = 0.9,
        probabilities: dict[str, float] | None = None,
        score: float = 2.0,
        score_probabilities: dict[int, float] | None = None,
        noul: float = 0.8,
        defaulted: bool = False,
    ) -> None:
        self.choice_answer = choice
        self.confidence = confidence
        self.choice_probabilities = probabilities or {choice: 0.9}
        self.score_value = score
        self.score_probabilities = score_probabilities or {2: 0.9}
        self.noul_value = noul
        self.defaulted = defaulted
        self.calls: list[Call] = []

    async def choice(self, state: Any, instructions: str, options: Any) -> ChoiceResult:
        self.calls.append(Call("choice", state, instructions, options=dict(options)))
        return ChoiceResult(
            choice=self.choice_answer,
            probabilities=self.choice_probabilities,
            confidence=self.confidence,
            latency_ms=2.0,
            model=self.model_id,
            provider="fake",
            cost=0.0001,
            request_id="req_1",
            raw={"answer": self.choice_answer},
            defaulted=self.defaulted,
        )

    async def score(self, state: Any, instructions: str, levels: Any) -> ScoreResult:
        self.calls.append(Call("score", state, instructions, levels=list(levels)))
        return ScoreResult(
            score=self.score_value,
            probabilities=self.score_probabilities,
            confidence=self.confidence,
            latency_ms=2.0,
            model=self.model_id,
            provider="fake",
            cost=0.0001,
            request_id="req_2",
            raw={"score": self.score_value},
            defaulted=self.defaulted,
        )

    async def noul(self, state: Any, instructions: str) -> NoulResult:
        self.calls.append(Call("noul", state, instructions))
        return NoulResult(
            noul=self.noul_value,
            confidence=self.confidence,
            latency_ms=2.0,
            model=self.model_id,
            provider="fake",
            cost=0.0001,
            request_id="req_3",
            raw={"noul": self.noul_value},
            defaulted=self.defaulted,
        )

    async def batch(self, state: Any, questions: Any) -> dict[str, Any]:
        return {}


@dataclass
class Recorder:
    """Collects the records a point writes."""

    records: list[DecisionRecord] = field(default_factory=list)

    async def __call__(self, record: DecisionRecord) -> None:
        self.records.append(record)


class TestPlan:
    async def test_planning_runs_at_or_above_the_threshold(self):
        assert (await decide_plan(FakeDecider(noul=0.5), "q", threshold=0.5)).plan is True
        assert (await decide_plan(FakeDecider(noul=0.49), "q", threshold=0.5)).plan is False

    async def test_the_state_is_the_question(self):
        decider = FakeDecider()
        await decide_plan(decider, "how are jobs retried?")
        assert "how are jobs retried?" in decider.calls[0].state
        assert "several independent investigations" in decider.calls[0].instructions


class TestRelevanceWording:
    def test_the_jev_reranker_asks_the_shared_question(self):
        from app.services.retrieval.rerank.jev import LEVELS

        assert LEVELS == RELEVANCE_LEVELS
        assert "how is auth done?" in relevance_state("how is auth done?")
        instructions = relevance_instructions("F:a.py:1-4", "the passage")
        assert "F:a.py:1-4" in instructions
        assert "the passage" in instructions


class TestUnusableOutput:
    """A placeholder answer never counts as a confident one: planning fails safe."""

    @staticmethod
    def _decider(**answers: Any) -> FakeDecider:
        return FakeDecider(defaulted=True, **answers)

    async def test_planning_does_not_run(self):
        decision = await decide_plan(self._decider(noul=0.5), "q", threshold=0.5)
        assert not decision.plan

    async def test_the_record_says_the_answer_was_a_placeholder(self):
        recorder = Recorder()
        await decide_plan(self._decider(noul=0.5), "q", record=recorder)
        assert recorder.records[0].defaulted
        assert recorder.records[0].to_dict()["defaulted"] is True


class TestRecords:
    async def test_the_decision_writes_one_record_with_its_point_and_primitive(self):
        recorder = Recorder()

        await decide_plan(FakeDecider(noul=0.8), "q", record=recorder)

        assert [record.point for record in recorder.records] == ["plan"]
        assert [record.primitive for record in recorder.records] == ["noul"]

    async def test_the_record_holds_the_hash_of_the_state_that_was_sent(self):
        decider = FakeDecider(noul=0.8)
        recorder = Recorder()

        await decide_plan(decider, "the question", record=recorder)

        [record] = recorder.records
        assert record.state_hash == state_hash(decider.calls[0].state)
        assert record.state_bytes == len(decider.calls[0].state.encode("utf-8"))
        assert record.answer == 0.8
        assert record.confidence == 0.9
        assert record.model == "fake-model"
        assert record.provider == "fake"
        assert record.latency_ms == 2.0
        assert record.cost == 0.0001
        assert record.request_id == "req_3"

    async def test_a_failing_recorder_does_not_break_the_decision(self):
        async def broken(record: DecisionRecord) -> None:
            raise RuntimeError("step log is down")

        decision = await decide_plan(FakeDecider(), "q", record=broken)
        assert decision.plan is True


# --- both deciders end to end ------------------------------------------------


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")


def jev_responder(request: httpx.Request) -> httpx.Response:
    """Answers each question by its type, as the decision model would."""
    questions = json.loads(request.content)["questions"]
    answers: dict[str, Any] = {}
    for name, question in questions.items():
        if question["type"] == "choice":
            first = next(iter(question["criteria"]))
            answers[name] = {
                "choice": first,
                "probabilities": {first: 0.9},
                "confidence": 0.9,
            }
        elif question["type"] == "score":
            answers[name] = {
                "score": 2.0,
                "probabilities": {"0": 0.1, "1": 0.1, "2": 0.6, "3": 0.2},
                "confidence": 0.8,
            }
        else:
            answers[name] = {"noul": 0.8}
    return httpx.Response(
        200,
        json={
            "answers": answers,
            "model": "typesafe/jev-1.13-20260917",
            "provider": "typesafe",
            "usage": {"cost": 0.0005},
            "id": "dec_points",
        },
    )


class TestBothDeciderPaths:
    @respx.mock
    async def test_the_plan_decision_works_with_jev(self):
        respx.post(DECISIONS_URL).mock(side_effect=jev_responder)

        result = await decide_plan(JevDecider(), "how is auth done?")

        assert result.plan is True
        assert result.model == "typesafe/jev-1.13-20260917"

    async def test_the_plan_decision_works_with_the_llm_stand_in(self, monkeypatch):
        install_fake_openai(
            monkeypatch,
            json.dumps({"probability": 0.8, "confidence": 0.7}),
            module=llm_module,
        )

        result = await decide_plan(LlmDecider(make_llm()), "how is auth done?")

        assert result.plan is True
