"""The Jev reranker: request shape, ordering, batching, bookkeeping and failures."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import DECISIONS_URL, DecisionError
from app.services.retrieval.rerank import RerankError, RerankerUnavailable, get_reranker
from app.services.retrieval.rerank.jev import (
    JEV_MODEL,
    LEVELS,
    MAX_PASSAGE_CHARS,
    MAX_REQUEST_BYTES,
    JevReranker,
)
from tests.fixtures.retrieval import make_candidate

pytestmark = pytest.mark.unit

SNAPSHOT = "typesafe/jev-1.13-20260917"


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")


def pool(count: int, text: str = "body"):
    return [make_candidate(f"F:f{i}.py", f"{text} {i}", file_path=f"f{i}.py") for i in range(count)]


def scorer(score_of: Callable[[int], float], cost: float = 0.001):
    """A respx side effect that scores question ``p<i>`` as ``score_of(i)``."""

    def respond(request: httpx.Request) -> httpx.Response:
        questions = json.loads(request.content)["questions"]
        answers = {
            name: {
                "score": score_of(int(name[1:])),
                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4},
                "legend": list(LEVELS),
                "confidence": 0.9,
            }
            for name in questions
        }
        return httpx.Response(
            200,
            json={
                "answers": answers,
                "model": SNAPSHOT,
                "provider": "typesafe",
                "usage": {"cost": cost, "input_tokens": 50, "output_tokens": 5},
                "id": "dec_1",
            },
        )

    return respond


class TestRequest:
    @respx.mock
    async def test_one_score_question_per_passage_with_the_four_levels(self):
        route = respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0))
        await JevReranker().rerank("how is auth done?", pool(3), 3)

        assert route.call_count == 1
        request = route.calls.last.request
        assert request.headers["authorization"] == "Bearer or-test-key"
        body = json.loads(request.content)
        assert body["model"] == JEV_MODEL == "typesafe/jev-1.14"
        assert "how is auth done?" in body["state"]
        assert list(body["questions"]) == ["p0", "p1", "p2"]
        for index, question in enumerate(body["questions"].values()):
            assert question["type"] == "score"
            assert question["criteria"] == [
                "unrelated",
                "mentions the topic",
                "partially answers",
                "directly answers",
            ]
            assert f"body {index}" in question["instructions"]
            assert "answers the question" in question["instructions"]

    @respx.mock
    async def test_session_id_only_when_the_caller_gives_one(self):
        route = respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0))

        await JevReranker().rerank("q", pool(2), 2)
        assert "session_id" not in json.loads(route.calls.last.request.content)

        await get_reranker("jev", session_id="run-9").rerank("q", pool(2), 2)
        assert json.loads(route.calls.last.request.content)["session_id"] == "run-9"

    @respx.mock
    async def test_long_passages_are_truncated(self):
        route = respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0))
        await JevReranker().rerank("q", [make_candidate("F:a.py", "z" * 10_000)], 1)

        instructions = json.loads(route.calls.last.request.content)["questions"]["p0"][
            "instructions"
        ]
        assert instructions.count("z") == MAX_PASSAGE_CHARS


class TestOrdering:
    @respx.mock
    async def test_sorted_by_score_highest_first_and_carried_as_the_rerank_score(self):
        scores = {0: 0.4, 1: 2.7, 2: 1.1, 3: 3.0}
        respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: scores[i]))
        ranked = await JevReranker().rerank("q", pool(4), 3)

        assert [c.key for c in ranked] == ["F:f3.py", "F:f1.py", "F:f2.py"]
        assert [c.rerank_score for c in ranked] == [3.0, 2.7, 1.1]

    @respx.mock
    async def test_ties_keep_the_fused_order(self):
        respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 2.0 if i in (1, 3) else 0.5))
        ranked = await JevReranker().rerank("q", pool(5), 5)
        assert [c.key for c in ranked] == [
            "F:f1.py",
            "F:f3.py",
            "F:f0.py",
            "F:f2.py",
            "F:f4.py",
        ]

    @respx.mock
    async def test_an_empty_pool_makes_no_request(self):
        assert await JevReranker().rerank("q", [], 3) == []


class TestBatching:
    @respx.mock
    async def test_a_large_pool_splits_into_requests_under_the_byte_budget(self):
        route = respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: float(i % 4)))
        candidates = pool(60, text="w" * 1200)
        ranked = await JevReranker().rerank("q", candidates, 60)

        assert route.call_count > 1
        seen: list[str] = []
        for call in route.calls:
            body = json.loads(call.request.content)
            text_bytes = len(body["state"].encode()) + sum(
                len(q["instructions"].encode())
                + sum(len(level.encode()) for level in q["criteria"])
                for q in body["questions"].values()
            )
            assert text_bytes <= MAX_REQUEST_BYTES
            seen.extend(body["questions"])
        # Every passage is asked about exactly once, under a unique name.
        assert sorted(seen, key=lambda n: int(n[1:])) == [f"p{i}" for i in range(60)]
        # Scores from different requests are sorted together.
        scores = [c.rerank_score for c in ranked]
        assert scores == sorted(scores, reverse=True)

    @respx.mock
    async def test_a_small_pool_is_one_request(self):
        route = respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0))
        await JevReranker().rerank("q", pool(10), 10)
        assert route.call_count == 1

    @respx.mock
    async def test_multibyte_text_is_measured_in_bytes(self):
        route = respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0))
        await JevReranker().rerank("q", pool(20, text="é" * 1400), 20)

        for call in route.calls:
            questions = json.loads(call.request.content)["questions"]
            total = sum(len(q["instructions"].encode()) for q in questions.values())
            assert total <= MAX_REQUEST_BYTES
        assert route.call_count > 1


class TestBookkeeping:
    @respx.mock
    async def test_the_cost_snapshot_and_raw_response_are_recorded(self):
        respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0, cost=0.0042))
        reranker = JevReranker()
        await reranker.rerank("q", pool(2), 2)

        [call] = reranker.calls
        assert call.provider == "jev"
        assert call.model == SNAPSHOT
        assert call.cost == pytest.approx(0.0042)
        assert call.detail["requested_model"] == JEV_MODEL
        assert call.response["id"] == "dec_1"
        assert set(call.response["answers"]) == {"p0", "p1"}
        assert reranker.total_cost == pytest.approx(0.0042)

    @respx.mock
    async def test_every_request_of_a_split_pool_is_recorded(self):
        respx.post(DECISIONS_URL).mock(side_effect=scorer(lambda i: 1.0, cost=0.01))
        reranker = JevReranker()
        await reranker.rerank("q", pool(60, text="w" * 1200), 5)

        assert len(reranker.calls) > 1
        assert reranker.total_cost == pytest.approx(0.01 * len(reranker.calls))


class TestFailures:
    async def test_a_missing_key_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        with pytest.raises(RerankerUnavailable, match="OPENROUTER_API_KEY"):
            get_reranker("jev")

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
            await JevReranker().rerank("q", pool(2), 2)

    @respx.mock
    async def test_a_timeout_raises(self):
        respx.post(DECISIONS_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
        with pytest.raises(DecisionError, match="timed out"):
            await JevReranker().rerank("q", pool(2), 2)

    @respx.mock
    async def test_a_malformed_body_raises(self):
        respx.post(DECISIONS_URL).mock(return_value=httpx.Response(200, json={"nothing": 1}))
        with pytest.raises(DecisionError, match="answers"):
            await JevReranker().rerank("q", pool(2), 2)

    @respx.mock
    async def test_one_failing_request_of_a_split_pool_fails_the_rerank(self):
        calls = {"n": 0}

        def flaky(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 2:
                return httpx.Response(429, json={})
            return scorer(lambda i: 1.0)(request)

        respx.post(DECISIONS_URL).mock(side_effect=flaky)
        with pytest.raises(DecisionError, match="rate-limited"):
            await JevReranker().rerank("q", pool(60, text="w" * 1200), 5)

    @respx.mock
    async def test_a_response_missing_a_passage_is_refused(self):
        def partial(request: httpx.Request) -> httpx.Response:
            response = scorer(lambda i: 1.0)(request)
            body = json.loads(response.content)
            body["answers"].pop("p1")
            return httpx.Response(200, json=body)

        respx.post(DECISIONS_URL).mock(side_effect=partial)
        with pytest.raises(DecisionError, match="no answer for 'p1'"):
            await JevReranker().rerank("q", pool(2), 2)


def test_rerank_error_is_exported():
    assert issubclass(RerankError, RuntimeError)
