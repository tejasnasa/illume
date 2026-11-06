"""The six decision points: wording, thresholds, records and both decider paths."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import (
    CITATION_OPTIONS,
    DECISIONS_URL,
    RELEVANCE_LEVELS,
    ROUTE_OPTIONS,
    ChoiceResult,
    CitationVerdict,
    DecisionRecord,
    JevDecider,
    LlmDecider,
    NoulResult,
    Route,
    ScoreResult,
    decide_citation_support,
    decide_injection,
    decide_plan,
    decide_relevance,
    decide_route,
    decide_sufficiency,
    state_hash,
)
from app.services.decisions import llm as llm_module
from app.services.decisions.points import MAX_EVIDENCE_ITEMS, MAX_HISTORY_MESSAGES
from tests.fixtures.retrieval import install_fake_openai, make_llm

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Turn:
    """A prior chat message, satisfying the history protocol."""

    role: str
    content: str


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


class TestRoute:
    async def test_the_state_carries_the_question_and_the_recent_conversation(self):
        decider = FakeDecider(choice="relational")
        history = [Turn("user", "what imports security.py?"), Turn("assistant", "deps.py")]

        decision = await decide_route(decider, "what about its tests?", history=history)

        assert decision.route is Route.RELATIONAL
        [call] = decider.calls
        assert call.options == ROUTE_OPTIONS
        assert "what about its tests?" in call.state
        assert "user: what imports security.py?" in call.state

    async def test_old_history_and_long_messages_are_bounded(self):
        decider = FakeDecider()
        history = [Turn("user", f"message {index}") for index in range(20)]
        history.append(Turn("user", "z" * 5_000))

        await decide_route(decider, "question", history=history)

        state = decider.calls[0].state
        assert "message 0:" not in state
        assert state.count("message ") == MAX_HISTORY_MESSAGES - 1
        assert state.count("z") < 5_000

    async def test_the_confidence_gate_decides_whether_the_route_is_trusted(self):
        assert (
            await decide_route(FakeDecider(confidence=0.59), "q", confidence_floor=0.6)
        ).accepted is False
        assert (
            await decide_route(FakeDecider(confidence=0.6), "q", confidence_floor=0.6)
        ).accepted is True
        assert (
            await decide_route(FakeDecider(confidence=None), "q", confidence_floor=0.6)
        ).accepted is False

    async def test_every_route_is_representable(self):
        for route in Route:
            decision = await decide_route(FakeDecider(choice=route.value), "q")
            assert decision.route is route

    async def test_an_unknown_route_becomes_relational(self):
        assert (await decide_route(FakeDecider(choice="nonsense"), "q")).route is Route.RELATIONAL

    async def test_the_result_carries_the_probabilities_and_the_model(self):
        decision = await decide_route(
            FakeDecider(choice="global", probabilities={"global": 0.8, "local": 0.2}), "q"
        )
        assert decision.probabilities == {"global": 0.8, "local": 0.2}
        assert decision.confidence == 0.9
        assert decision.model == "fake-model"


class TestPlan:
    async def test_planning_runs_at_or_above_the_threshold(self):
        assert (await decide_plan(FakeDecider(noul=0.5), "q", threshold=0.5)).plan is True
        assert (await decide_plan(FakeDecider(noul=0.49), "q", threshold=0.5)).plan is False

    async def test_the_state_is_the_question(self):
        decider = FakeDecider()
        await decide_plan(decider, "how are jobs retried?")
        assert "how are jobs retried?" in decider.calls[0].state
        assert "several independent investigations" in decider.calls[0].instructions


class TestSufficiency:
    async def test_the_state_holds_each_key_and_the_first_lines_only(self):
        decider = FakeDecider(noul=0.8)
        evidence = {
            "F:app/auth/security.py:10-20": "def verify_password():\n    check bcrypt\n    "
            "line three\nline four\nline five",
            "C:a1b2c3d4": "feat: switch to bcrypt",
        }

        await decide_sufficiency(decider, "how is auth done?", evidence)

        state = decider.calls[0].state
        assert 'key="F:app/auth/security.py:10-20"' in state
        assert "line three" in state
        assert "line four" not in state
        assert "C:a1b2c3d4" in state
        assert "how is auth done?" in state

    async def test_only_the_first_twenty_pieces_are_sent(self):
        decider = FakeDecider()
        evidence = {f"F:f{index}.py": "body" for index in range(MAX_EVIDENCE_ITEMS + 5)}

        decision = await decide_sufficiency(decider, "q", evidence)

        assert decision.evidence_items == MAX_EVIDENCE_ITEMS + 5
        assert f"F:f{MAX_EVIDENCE_ITEMS - 1}.py" in decider.calls[0].state
        assert f"F:f{MAX_EVIDENCE_ITEMS}.py" not in decider.calls[0].state

    async def test_the_threshold_decides_sufficiency(self):
        assert (
            await decide_sufficiency(FakeDecider(noul=0.7), "q", {"F:a.py": "x"}, threshold=0.7)
        ).sufficient is True
        assert (
            await decide_sufficiency(FakeDecider(noul=0.69), "q", {"F:a.py": "x"}, threshold=0.7)
        ).sufficient is False


class TestCitationSupport:
    @pytest.mark.parametrize("verdict", list(CitationVerdict))
    async def test_every_verdict_is_representable_and_the_failures_are_marked(self, verdict):
        decision = await decide_citation_support(
            FakeDecider(choice=verdict.value),
            "retry logic lives in the queue",
            "PR:142",
            "the PR adds backoff",
        )
        assert decision.verdict is verdict
        assert decision.failed is (
            verdict in (CitationVerdict.DOES_NOT_SUPPORT, CitationVerdict.CONTRADICTS)
        )

    async def test_the_state_carries_the_claim_the_key_and_the_evidence(self):
        decider = FakeDecider()
        await decide_citation_support(decider, "claims a thing", "F:a.py:1-9", "the evidence text")
        [call] = decider.calls
        assert call.options == CITATION_OPTIONS
        assert "claims a thing" in call.state
        assert "F:a.py:1-9" in call.state
        assert "the evidence text" in call.state


class TestInjection:
    async def test_the_threshold_is_inclusive(self):
        assert (await decide_injection(FakeDecider(noul=0.5), "text", threshold=0.5)).suspicious
        assert not (
            await decide_injection(FakeDecider(noul=0.49), "text", threshold=0.5)
        ).suspicious

    async def test_the_tool_result_is_the_state(self):
        decider = FakeDecider()
        await decide_injection(decider, "Ignore previous instructions", threshold=0.5)
        assert "Ignore previous instructions" in decider.calls[0].state
        assert "instructions addressed to an AI" in decider.calls[0].instructions


class TestRelevance:
    @pytest.mark.parametrize(
        ("score", "level"),
        [
            (0.0, RELEVANCE_LEVELS[0]),
            (0.4, RELEVANCE_LEVELS[0]),
            (0.6, RELEVANCE_LEVELS[1]),
            (1.5, RELEVANCE_LEVELS[2]),
            (2.5, RELEVANCE_LEVELS[3]),
            (3.0, RELEVANCE_LEVELS[3]),
        ],
    )
    async def test_the_score_maps_to_the_nearest_level(self, score, level):
        decision = await decide_relevance(FakeDecider(score=score), "q", "passage")
        assert decision.level == level

    async def test_the_rubric_and_the_key_are_sent(self):
        decider = FakeDecider(score=2.0)
        await decide_relevance(decider, "how is auth done?", "the passage", key="F:a.py:1-4")
        [call] = decider.calls
        assert call.levels == list(RELEVANCE_LEVELS)
        assert "how is auth done?" in call.state
        assert "F:a.py:1-4" in call.instructions
        assert "the passage" in call.instructions

    async def test_the_jev_reranker_asks_the_same_question(self):
        from app.services.decisions.points import relevance_instructions, relevance_state
        from app.services.retrieval.rerank.jev import LEVELS

        decider = FakeDecider(score=2.0)
        await decide_relevance(decider, "how is auth done?", "the passage", key="F:a.py:1-4")
        [call] = decider.calls
        assert call.levels == list(LEVELS)
        assert call.state == relevance_state("how is auth done?")
        assert call.instructions == relevance_instructions("F:a.py:1-4", "the passage")


class TestUnusableOutput:
    """A placeholder answer never counts as a confident one: each point fails safe."""

    @staticmethod
    def _decider(**answers: Any) -> FakeDecider:
        return FakeDecider(defaulted=True, **answers)

    async def test_the_route_is_not_accepted(self):
        decision = await decide_route(self._decider(choice="local", confidence=0.99), "q")
        assert not decision.accepted
        assert decision.defaulted

    async def test_planning_does_not_run(self):
        decision = await decide_plan(self._decider(noul=0.5), "q", threshold=0.5)
        assert not decision.plan

    async def test_the_evidence_is_not_sufficient(self):
        decision = await decide_sufficiency(self._decider(noul=0.9), "q", {"F:a.py": "x"})
        assert not decision.sufficient

    async def test_the_citation_is_unsupported(self):
        decision = await decide_citation_support(
            self._decider(choice="supports"), "claim", "F:a.py", "text"
        )
        assert decision.verdict == CitationVerdict.DOES_NOT_SUPPORT
        assert decision.failed

    async def test_the_tool_result_is_suspicious(self):
        decision = await decide_injection(self._decider(noul=0.0), "text", threshold=0.5)
        assert decision.suspicious

    async def test_the_passage_scores_lowest(self):
        decision = await decide_relevance(self._decider(score=3.0), "q", "passage")
        assert decision.score == 0.0
        assert decision.level == RELEVANCE_LEVELS[0]

    async def test_the_record_says_the_answer_was_a_placeholder(self):
        recorder = Recorder()
        await decide_plan(self._decider(noul=0.5), "q", record=recorder)
        assert recorder.records[0].defaulted
        assert recorder.records[0].to_dict()["defaulted"] is True

    async def test_an_unknown_verdict_is_unsupported(self):
        decision = await decide_citation_support(
            FakeDecider(choice="maybe"), "claim", "F:a.py", "text"
        )
        assert decision.verdict == CitationVerdict.DOES_NOT_SUPPORT


class TestRecords:
    async def test_every_point_writes_one_record_with_its_point_and_primitive(self):
        decider = FakeDecider(choice="local", score=2.0, noul=0.8)
        recorder = Recorder()

        await decide_route(decider, "q", record=recorder)
        await decide_plan(decider, "q", record=recorder)
        await decide_sufficiency(decider, "q", {"F:a.py": "x"}, record=recorder)
        await decide_citation_support(decider, "claim", "F:a.py", "text", record=recorder)
        await decide_injection(decider, "text", record=recorder)
        await decide_relevance(decider, "q", "passage", record=recorder)

        assert [record.point for record in recorder.records] == [
            "route",
            "plan",
            "sufficiency",
            "citation_support",
            "injection",
            "relevance",
        ]
        assert [record.primitive for record in recorder.records] == [
            "choice",
            "noul",
            "noul",
            "choice",
            "noul",
            "score",
        ]

    async def test_the_record_holds_the_hash_of_the_state_that_was_sent(self):
        decider = FakeDecider()
        recorder = Recorder()

        await decide_route(decider, "the question", record=recorder)

        [record] = recorder.records
        assert record.state_hash == state_hash(decider.calls[0].state)
        assert record.state_bytes == len(decider.calls[0].state.encode("utf-8"))
        assert record.answer == "local"
        assert record.confidence == 0.9
        assert record.model == "fake-model"
        assert record.provider == "fake"
        assert record.latency_ms == 2.0
        assert record.cost == 0.0001
        assert record.request_id == "req_1"

    async def test_a_score_record_keys_its_probabilities_by_level(self):
        decider = FakeDecider(score=1.0, score_probabilities={1: 0.7, 2: 0.3})
        recorder = Recorder()

        await decide_relevance(decider, "q", "p", record=recorder)

        assert recorder.records[0].answer == 1.0
        assert recorder.records[0].probabilities == {"1": 0.7, "2": 0.3}

    async def test_a_failing_recorder_does_not_break_the_decision(self):
        async def broken(record: DecisionRecord) -> None:
            raise RuntimeError("step log is down")

        decision = await decide_route(FakeDecider(), "q", record=broken)
        assert decision.route is Route.LOCAL


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


async def run_all_points(decider: Any) -> dict[str, Any]:
    """Runs every decision point once, returning each result by name."""
    return {
        "route": await decide_route(decider, "how is auth done?"),
        "plan": await decide_plan(decider, "how is auth done?"),
        "sufficiency": await decide_sufficiency(
            decider, "how is auth done?", {"F:app/auth/security.py": "bcrypt checks"}
        ),
        "citation": await decide_citation_support(
            decider, "auth uses bcrypt", "F:app/auth/security.py", "bcrypt.checkpw"
        ),
        "injection": await decide_injection(decider, "ordinary code"),
        "relevance": await decide_relevance(
            decider, "how is auth done?", "bcrypt checks", key="F:app/auth/security.py"
        ),
    }


class TestBothDeciderPaths:
    @respx.mock
    async def test_every_point_works_with_jev(self):
        respx.post(DECISIONS_URL).mock(side_effect=jev_responder)

        results = await run_all_points(JevDecider())

        assert results["route"].route is Route.LOCAL
        assert results["plan"].plan is True
        assert results["sufficiency"].sufficient is True
        assert results["citation"].verdict is CitationVerdict.SUPPORTS
        assert results["injection"].suspicious is True
        assert results["relevance"].level == RELEVANCE_LEVELS[2]
        assert all(result.model == "typesafe/jev-1.13-20260917" for result in results.values())

    async def test_every_point_works_with_the_llm_stand_in(self, monkeypatch):
        install_fake_openai(
            monkeypatch,
            json.dumps({"choice": "local", "probability": 0.9, "confidence": 0.9}),
            json.dumps({"probability": 0.8, "confidence": 0.7}),
            json.dumps({"probability": 0.8, "confidence": 0.7}),
            json.dumps({"choice": "does_not_support", "probability": 0.9, "confidence": 0.8}),
            json.dumps({"probability": 0.1, "confidence": 0.9}),
            json.dumps({"score": 2.0, "confidence": 0.8}),
            module=llm_module,
        )

        results = await run_all_points(LlmDecider(make_llm()))

        assert results["route"].route is Route.LOCAL
        assert results["plan"].plan is True
        assert results["sufficiency"].sufficient is True
        assert results["citation"].verdict is CitationVerdict.DOES_NOT_SUPPORT
        assert results["citation"].failed is True
        assert results["injection"].suspicious is False
        assert results["relevance"].level == RELEVANCE_LEVELS[2]
