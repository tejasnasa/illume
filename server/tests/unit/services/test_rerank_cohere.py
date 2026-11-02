"""The Cohere reranker: request shape, result ordering and failures."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.retrieval.rerank import RerankError, RerankerUnavailable, get_reranker
from app.services.retrieval.rerank.cohere import COHERE_RERANK_URL, CohereReranker
from tests.fixtures.retrieval import make_candidate

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def cohere_key(monkeypatch):
    monkeypatch.setattr(settings, "COHERE_API_KEY", "co-test-key")


def pool(count: int = 4):
    return [make_candidate(f"F:f{i}.py", f"text {i}", file_path=f"f{i}.py") for i in range(count)]


def results(*pairs: tuple[int, float]) -> dict:
    return {"id": "r1", "results": [{"index": i, "relevance_score": s} for i, s in pairs]}


@respx.mock
async def test_request_shape_and_auth_header():
    route = respx.post(COHERE_RERANK_URL).mock(
        return_value=httpx.Response(200, json=results((2, 0.9), (0, 0.4)))
    )
    candidates = pool()
    candidates[1] = make_candidate("F:long.py", "x" * 9000, file_path="long.py")

    await get_reranker("cohere").rerank("how is auth done?", candidates, 2)

    request = route.calls.last.request
    assert str(request.url) == "https://api.cohere.com/v2/rerank"
    assert request.headers["authorization"] == "Bearer co-test-key"
    body = json.loads(request.content)
    assert body["model"] == "rerank-v3.5"
    assert body["query"] == "how is auth done?"
    assert body["top_n"] == 2
    assert len(body["documents"]) == 4
    assert body["documents"][0] == "text 0"
    assert len(body["documents"][1]) == 4000


@respx.mock
async def test_results_are_ordered_by_score_and_carry_it():
    respx.post(COHERE_RERANK_URL).mock(
        return_value=httpx.Response(200, json=results((3, 0.2), (1, 0.8), (0, 0.5)))
    )
    candidates = pool()
    ranked = await CohereReranker().rerank("q", candidates, 3)

    assert [c.key for c in ranked] == ["F:f1.py", "F:f0.py", "F:f3.py"]
    assert [c.rerank_score for c in ranked] == [0.8, 0.5, 0.2]
    # The inputs are not mutated.
    assert all(c.rerank_score is None for c in candidates)


@respx.mock
async def test_top_n_cuts_the_result_and_never_exceeds_the_pool():
    route = respx.post(COHERE_RERANK_URL).mock(
        return_value=httpx.Response(200, json=results((0, 0.9), (1, 0.8), (2, 0.7)))
    )
    ranked = await CohereReranker().rerank("q", pool(3), 20)
    assert len(ranked) == 3
    assert json.loads(route.calls.last.request.content)["top_n"] == 3

    ranked = await CohereReranker().rerank("q", pool(3), 1)
    assert [c.key for c in ranked] == ["F:f0.py"]


@respx.mock
async def test_the_raw_response_is_kept_on_the_reranker():
    payload = results((1, 0.9))
    respx.post(COHERE_RERANK_URL).mock(return_value=httpx.Response(200, json=payload))
    reranker = CohereReranker()
    await reranker.rerank("q", pool(), 1)

    assert [call.response for call in reranker.calls] == [payload]
    assert reranker.calls[0].provider == "cohere"


@respx.mock
async def test_bad_indices_are_ignored_but_no_usable_result_raises():
    respx.post(COHERE_RERANK_URL).mock(
        return_value=httpx.Response(200, json=results((9, 0.9), (1, 0.5), (1, 0.4), (-1, 0.3)))
    )
    ranked = await CohereReranker().rerank("q", pool(), 4)
    assert [c.key for c in ranked] == ["F:f1.py"]

    respx.post(COHERE_RERANK_URL).mock(return_value=httpx.Response(200, json=results((9, 0.9))))
    with pytest.raises(RerankError, match="no usable results"):
        await CohereReranker().rerank("q", pool(), 4)


async def test_a_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")
    with pytest.raises(RerankerUnavailable, match="COHERE_API_KEY"):
        get_reranker("cohere")


@pytest.mark.parametrize("status", [400, 401, 429, 500])
@respx.mock
async def test_http_errors_raise(status):
    respx.post(COHERE_RERANK_URL).mock(
        return_value=httpx.Response(status, json={"message": "nope"})
    )
    with pytest.raises(RerankError, match=str(status)):
        await CohereReranker().rerank("q", pool(), 2)


@respx.mock
async def test_timeouts_and_bad_bodies_raise():
    respx.post(COHERE_RERANK_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(RerankError, match="timed out"):
        await CohereReranker().rerank("q", pool(), 2)

    respx.post(COHERE_RERANK_URL).mock(return_value=httpx.Response(200, content="<html>"))
    with pytest.raises(RerankError, match="not JSON"):
        await CohereReranker().rerank("q", pool(), 2)

    respx.post(COHERE_RERANK_URL).mock(return_value=httpx.Response(200, json={"results": "x"}))
    with pytest.raises(RerankError, match="results"):
        await CohereReranker().rerank("q", pool(), 2)


async def test_an_empty_pool_makes_no_request():
    with respx.mock:
        assert await CohereReranker().rerank("q", [], 5) == []
