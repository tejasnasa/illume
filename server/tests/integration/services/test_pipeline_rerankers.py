"""``retrieve`` applies each reranker kind, records its calls, and degrades when it fails."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Literal

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.decisions import DECISIONS_URL
from app.services.retrieval import pipeline as pipeline_module
from app.services.retrieval.config import HYBRID, DiversifyConfig, PipelineConfig, RerankConfig
from app.services.retrieval.diversify import diversify
from app.services.retrieval.pipeline import retrieve
from app.services.retrieval.rerank import RerankCall
from app.services.retrieval.rerank.cohere import COHERE_RERANK_URL
from tests.factories import make_user
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    RecordingEmit,
    hash_vector,
    make_context,
    render_symbol_chunk,
    seed_repo,
)

pytestmark = pytest.mark.integration

QUESTION = "how does verify_password check bcrypt checkpw"
VERIFY_VECTOR = hash_vector(
    render_symbol_chunk("app/auth/security.py", DEFAULT_SPEC.files[0].symbols[0])
)


def config_for(kind: Literal["none", "cohere", "llm", "jev"], top_n: int = 4) -> PipelineConfig:
    return HYBRID.model_copy(
        update={
            "rerank": RerankConfig(kind=kind, candidate_pool=12, top_n=top_n),
            "diversify": DiversifyConfig(total=20),
        }
    )


@pytest.fixture
async def seeded(db_session):
    return await seed_repo(db_session, await make_user(db_session), DEFAULT_SPEC)


class Reversing:
    """A reranker that returns the pool backwards with a visible score."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = [
            RerankCall(provider=kind, model="m", cost=0.5, detail={"n": 1}, response={"raw": kind})
        ]

    async def rerank(self, question, candidates, top_n):
        ordered = list(reversed(candidates))[:top_n]
        return [
            replace(candidate, rerank_score=float(len(ordered) - place))
            for place, candidate in enumerate(ordered)
        ]


@pytest.mark.parametrize("kind", ["cohere", "llm", "jev"])
async def test_each_kind_is_applied_and_its_calls_recorded(db_session, seeded, monkeypatch, kind):
    monkeypatch.setattr(pipeline_module, "get_reranker", lambda k, **_: Reversing(k))
    config = config_for(kind)
    ctx = make_context(db_session, seeded.repo, {QUESTION: VERIFY_VECTOR})
    result = await retrieve(config, QUESTION, ctx=ctx)

    assert not result.trace.reranker_degraded
    assert result.trace.reranker == kind
    expected_head = [c.key for c in reversed(result.pool)][:4]
    assert [c.key for c in result.candidates] == expected_head
    assert all(c.rerank_score is not None for c in result.candidates)
    # The raw calls reach the trace in JSON-serialisable form.
    assert result.trace.rerank_calls == (
        {
            "provider": kind,
            "model": "m",
            "cost": 0.5,
            "detail": {"n": 1},
            "response": {"raw": kind},
        },
    )
    json.dumps(result.trace.rerank_calls)


async def test_a_raising_reranker_degrades_and_keeps_what_it_recorded(
    db_session, seeded, monkeypatch
):
    class Exploding(Reversing):
        async def rerank(self, question, candidates, top_n):
            raise RuntimeError("provider down")

    monkeypatch.setattr(pipeline_module, "get_reranker", lambda k, **_: Exploding(k))
    emit = RecordingEmit()
    ctx = make_context(db_session, seeded.repo, {QUESTION: VERIFY_VECTOR})
    ctx.emit = emit
    config = config_for("jev")
    result = await retrieve(config, QUESTION, ctx=ctx)

    assert result.trace.reranker_degraded
    expected = diversify(list(result.pool[:4]), config.diversify)
    assert [c.key for c in result.candidates] == [c.key for c in expected]
    assert emit.degraded == [
        {"stage": "rerank", "reranker": "jev", "reason": "RuntimeError: provider down"}
    ]
    assert len(result.trace.rerank_calls) == 1


async def test_an_unavailable_reranker_degrades(db_session, seeded, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    emit = RecordingEmit()
    ctx = make_context(db_session, seeded.repo, {QUESTION: VERIFY_VECTOR})
    ctx.emit = emit
    result = await retrieve(config_for("cohere"), QUESTION, ctx=ctx)

    assert result.trace.reranker_degraded
    assert "OPENROUTER_API_KEY" in emit.degraded[0]["reason"]
    assert result.trace.rerank_calls == ()


@respx.mock
async def test_cohere_end_to_end_orders_the_pool(db_session, seeded, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "co-key")

    def respond(request: httpx.Request) -> httpx.Response:
        documents = json.loads(request.content)["documents"]
        # Rate a passage higher the later it was fused, so the order flips.
        results = [
            {"index": i, "relevance_score": i / len(documents)} for i in range(len(documents))
        ]
        return httpx.Response(200, json={"results": results})

    respx.post(COHERE_RERANK_URL).mock(side_effect=respond)
    ctx = make_context(db_session, seeded.repo, {QUESTION: VERIFY_VECTOR})
    result = await retrieve(config_for("cohere", top_n=3), QUESTION, ctx=ctx)

    assert not result.trace.reranker_degraded
    assert [c.key for c in result.candidates] == [c.key for c in reversed(result.pool)][:3]
    assert result.trace.rerank_calls[0]["provider"] == "cohere"


@respx.mock
async def test_jev_end_to_end_orders_by_score(db_session, seeded, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-key")

    def respond(request: httpx.Request) -> httpx.Response:
        questions = json.loads(request.content)["questions"]
        answers = {
            name: {"score": 3.0 if "hash_password" in q["instructions"] else 1.0}
            for name, q in questions.items()
        }
        return httpx.Response(200, json={"answers": answers, "model": "typesafe/jev-1.13-x"})

    respx.post(DECISIONS_URL).mock(side_effect=respond)
    ctx = make_context(db_session, seeded.repo, {QUESTION: VERIFY_VECTOR})
    result = await retrieve(config_for("jev", top_n=5), QUESTION, ctx=ctx)

    assert not result.trace.reranker_degraded
    scores = [c.rerank_score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 3.0
    assert result.trace.rerank_calls[0]["model"] == "typesafe/jev-1.13-x"
