"""Metering: usage is read from every call path, cached tokens included, and attributed."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
import respx
from openai import AsyncOpenAI

from app.services.retrieval import query as query_module
from app.services.retrieval import single_shot
from app.services.retrieval.embedding import EMBEDDING_MODEL
from app.services.retrieval.rerank.cohere import COHERE_RERANK_URL, CohereReranker
from app.services.retrieval.rerank.jev import JevReranker
from evals.run.metering import (
    Meter,
    costs_from_decision,
    costs_from_decisions,
    costs_from_trace,
    metered_client_factory,
    metered_rerankers,
    patched_direct_clients,
)
from tests.evals.run_helpers import PlainModel
from tests.fixtures.agent_run import ScriptedModel, say
from tests.fixtures.retrieval import make_candidate

pytestmark = pytest.mark.unit


class TestClients:
    async def test_a_plain_response_records_cached_tokens_and_the_reported_model(self):
        meter = Meter()
        model = PlainModel([say("hi")], cached_tokens=40)
        client = metered_client_factory(meter, model.factory)(
            api_key="k", base_url="https://api.deepseek.example/v1"
        )

        response = await client.responses.create(model="asked-for", input=[])

        assert response.output_text == "hi"
        (usage,) = meter.usages
        assert (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens) == (100, 40, 20)
        assert usage.kind == "generate"
        assert usage.model == "test-model"  # what the response reported, not what was asked
        assert usage.provider == "api.deepseek.example"
        assert usage.latency_ms >= 0

    async def test_a_streamed_response_is_metered_from_its_completed_event(self):
        meter = Meter()
        model = ScriptedModel([say("streamed answer")])
        client = metered_client_factory(meter, model.factory, kind="agent")()

        stream = await client.responses.create(model="m", input=[], stream=True)
        events = [event async for event in stream]

        assert events[-1].type == "response.completed"
        (usage,) = meter.usages
        assert usage.kind == "agent" and usage.provider == "openai"
        assert (usage.input_tokens, usage.output_tokens) == (100, 20)
        assert meter.unmetered == []

    async def test_a_stream_that_never_completes_is_noted_as_unmetered(self):
        async def events():
            yield SimpleNamespace(type="response.output_text.delta", delta="x")

        async def create(**kwargs):
            return events()

        meter = Meter()
        client = metered_client_factory(
            meter, lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create))
        )()

        stream = await client.responses.create(model="m", input=[], stream=True)
        async for _ in stream:
            pass

        assert meter.usages == []
        assert meter.unmetered == ["stream_without_usage:generate"]

    async def test_embeddings_are_metered_from_prompt_tokens(self):
        async def create(**kwargs):
            return SimpleNamespace(
                data=[],
                model=EMBEDDING_MODEL,
                usage=SimpleNamespace(prompt_tokens=12, total_tokens=12),
            )

        meter = Meter()
        client = metered_client_factory(
            meter, lambda **kw: SimpleNamespace(embeddings=SimpleNamespace(create=create))
        )()

        await client.embeddings.create(model=EMBEDDING_MODEL, input=["a"])

        (usage,) = meter.usages
        assert (usage.kind, usage.input_tokens, usage.output_tokens) == ("embed", 12, 0)
        assert usage.model == EMBEDDING_MODEL

    async def test_a_reported_cost_is_kept(self):
        async def create(**kwargs):
            return SimpleNamespace(
                model="m",
                output_text="",
                usage=SimpleNamespace(input_tokens=1, output_tokens=1, cost=0.5),
            )

        meter = Meter()
        client = metered_client_factory(
            meter, lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create))
        )()
        await client.responses.create(model="m", input=[])
        assert meter.total_cost() == 0.5

    async def test_a_response_without_usage_is_noted_as_unmetered(self):
        async def create(**kwargs):
            return SimpleNamespace(model="m", output_text="")

        meter = Meter()
        client = metered_client_factory(
            meter, lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create))
        )()
        await client.responses.create(model="m", input=[])
        assert meter.usages == [] and meter.unmetered == ["response_without_usage:generate"]

    def test_a_scope_forwards_to_its_parent(self):
        parent = Meter()
        child = parent.scope()
        child.note_unmetered("x")
        usage = costs_from_decision({"provider": "p", "model": "m", "cost": 0.1})
        child.record(usage)
        assert child.usages == parent.usages == [usage]
        assert parent.unmetered == ["x"]


class TestDirectClients:
    async def test_the_modules_that_build_their_own_client_are_metered_and_restored(self):
        from app.services.decisions import llm as decision_module
        from app.services.retrieval import embedding as embedding_module
        from app.services.retrieval.rerank import llm as rerank_module

        modules = (query_module, embedding_module, decision_module, rerank_module)
        meter = Meter()
        model = PlainModel([say('{"snippet": "def f(): pass"}')])

        with patched_direct_clients(meter, model.factory):
            assert all(module.AsyncOpenAI is not AsyncOpenAI for module in modules)
            client = query_module.AsyncOpenAI(api_key="k")
            await client.responses.create(
                model="m", input=[], text={"format": {"name": "hypothetical_snippet"}}
            )

        assert [usage.kind for usage in meter.usages] == ["hyde"]
        assert all(module.AsyncOpenAI is AsyncOpenAI for module in modules)

    async def test_each_module_tags_its_own_kind(self):
        from app.services.decisions import llm as decision_module
        from app.services.retrieval.rerank import llm as rerank_module

        meter = Meter()
        model = PlainModel([say("1"), say("2"), say("3"), say("4")])
        with patched_direct_clients(meter, model.factory):
            await decision_module.AsyncOpenAI(api_key="k").responses.create(model="m", input=[])
            await rerank_module.AsyncOpenAI(api_key="k").responses.create(model="m", input=[])
            await query_module.AsyncOpenAI(api_key="k").responses.create(
                model="m", input=[], text={"format": {"name": "query_rewrites"}}
            )
            await query_module.AsyncOpenAI(api_key="k").responses.create(
                model="m", input=[], text={"format": {"name": "standalone_question"}}
            )

        assert [usage.kind for usage in meter.usages] == [
            "decision",
            "rerank",
            "rewrite",
            "rewrite",
        ]

    async def test_the_patch_is_removed_when_the_block_fails(self):
        with pytest.raises(RuntimeError):
            with patched_direct_clients(Meter()):
                raise RuntimeError("boom")
        assert query_module.AsyncOpenAI is AsyncOpenAI

    async def test_overlapping_blocks_attribute_each_call_to_its_own_meter(self):
        both_inside = asyncio.Event()
        arrived = []

        async def generation(label: str, meter: Meter):
            model = PlainModel([say(label)])
            with patched_direct_clients(meter, model.factory):
                arrived.append(label)
                if len(arrived) == 2:
                    both_inside.set()
                await both_inside.wait()
                client = query_module.AsyncOpenAI(api_key="k")
                await client.responses.create(model=label, input=[])

        first, second = Meter(), Meter()
        await asyncio.gather(generation("one", first), generation("two", second))

        # The model name reported is the scripted "test-model"; the requested one is not kept,
        # so tell the meters apart by the number of entries each received.
        assert len(first.usages) == 1 and len(second.usages) == 1
        assert query_module.AsyncOpenAI is AsyncOpenAI

    async def test_the_answerers_own_factory_is_not_patched_over(self):
        # single_shot takes its client from the factory it is given, not a module name.
        assert single_shot.AsyncOpenAI is AsyncOpenAI
        with patched_direct_clients(Meter()):
            assert single_shot.AsyncOpenAI is AsyncOpenAI


class TestRerankCosts:
    def test_trace_costs_become_rerank_usages_and_llm_calls_are_not_counted_twice(self):
        trace = SimpleNamespace(
            rerank_calls=(
                {"provider": "cohere", "model": "cohere/rerank-5-fast", "cost": 0.002},
                {"provider": "jev", "model": "jev-snapshot", "cost": 0.00004},
                {"provider": "llm", "model": "m", "cost": None},
            )
        )
        usages = costs_from_trace(trace)
        assert [(u.provider, u.kind, u.reported_cost_usd) for u in usages] == [
            ("cohere", "rerank", 0.002),
            ("jev", "rerank", 0.00004),
        ]

    def test_a_batched_decision_request_is_charged_once(self):
        record = {
            "provider": "typesafe",
            "model": "jev",
            "cost": 0.01,
            "request_id": "r1",
            "tokens_in": 100,
            "tokens_out": 4,
        }
        usages = costs_from_decisions([record, record, {**record, "request_id": "r2"}])
        assert [u.reported_cost_usd for u in usages] == [0.01, None, 0.01]
        assert [u.input_tokens for u in usages] == [100, 0, 100]

    async def test_the_cohere_reranker_is_metered_inside_the_block_only(self):
        meter = Meter()
        candidates = [make_candidate("F:a.py:1-2", "a"), make_candidate("F:b.py:1-2", "b")]

        def respond(request: httpx.Request) -> httpx.Response:
            results = [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]
            return httpx.Response(200, json={"results": results, "usage": {"cost": 0.002}})

        original = CohereReranker.rerank
        with respx.mock(assert_all_called=False) as router:
            router.post(COHERE_RERANK_URL).mock(side_effect=respond)
            with metered_rerankers(meter):
                ranked = await CohereReranker(api_key="k").rerank("q", candidates, 2)
            await CohereReranker(api_key="k").rerank("q", candidates, 2)

        assert [c.key for c in ranked] == ["F:b.py:1-2", "F:a.py:1-2"]
        (usage,) = meter.usages  # the call outside the block is not recorded
        assert (usage.provider, usage.kind, usage.reported_cost_usd) == ("cohere", "rerank", 0.002)
        assert CohereReranker.rerank is original and JevReranker.rerank is not None

    async def test_a_failed_rerank_records_no_cost_and_still_raises(self):
        meter = Meter()
        with respx.mock(assert_all_called=False) as router:
            router.post(COHERE_RERANK_URL).respond(500, json={"error": "down"})
            with metered_rerankers(meter), pytest.raises(Exception, match="status 500"):
                await CohereReranker(api_key="k").rerank("q", [make_candidate("F:a.py:1-2")], 1)
        assert meter.usages == []
        assert meter.unmetered == []
