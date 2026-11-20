"""The adapters: one generation record per run, errors never scored, and ``auto`` composed."""

import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.agent.auto import FALLBACK_PRESET, ROUTE_PRESETS
from app.services.agent.tools.context import RepoSnapshot
from app.services.retrieval.citations import code_key
from app.services.retrieval.config import RerankConfig
from app.services.retrieval.rerank.cohere import COHERE_RERANK_URL
from evals.arms import AUTO, EVAL_INSTRUCTION, Arm, get_arm, question_with_instruction
from evals.run.adapters import (
    AUTO_ARM_BY_PRESET,
    FALLBACK_ARM,
    RERANKER_DEGRADED,
    arm_for_preset,
    compose_auto,
    route_item,
    run_agent_arm,
    run_single_shot,
)
from evals.run.clone_tools import build_clone_registry
from evals.run.metering import Meter
from evals.run.records import Generation, RouteRecord, Usage
from tests.evals.run_helpers import PlainModel, RouteDecider, make_gold_item
from tests.factories import make_user
from tests.fixtures import sample_repo
from tests.fixtures.agent_run import (
    ScriptedModel,
    Turn,
    agent_config,
    call,
    finish,
    say,
    serialized,
    turn,
)
from tests.fixtures.agent_tools import session_factory_for
from tests.fixtures.retrieval import (
    DEFAULT_SPEC,
    fake_embedder,
    hash_vector,
    make_context,
    make_llm,
    render_symbol_chunk,
    seed_repo,
)

pytestmark = pytest.mark.integration

SECURITY = "app/auth/security.py"
SERVICE = "app/users/service.py"
QUESTION = "how does verify_password check bcrypt checkpw"
VERIFY_SPEC = DEFAULT_SPEC.files[0].symbols[0]
VERIFY_KEY = code_key(SECURITY, VERIFY_SPEC.start_line, VERIFY_SPEC.end_line)
VERIFY_VECTOR = hash_vector(render_symbol_chunk(SECURITY, VERIFY_SPEC))
ASKED = question_with_instruction(QUESTION)
ANSWER = f"verify_password compares with bcrypt [{VERIFY_KEY}].\n\nFiles:\n- {SECURITY}"


@pytest.fixture
async def seeded(db_session):
    return await seed_repo(db_session, await make_user(db_session), DEFAULT_SPEC)


@pytest.fixture
def item():
    return make_gold_item(QUESTION)


def ctx_factory(db, seeded):
    @asynccontextmanager
    async def open_context():
        yield make_context(db, seeded.repo, {ASKED: VERIFY_VECTOR})

    return open_context


@pytest.fixture
def no_network():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


async def shoot(db, seeded, item, arm_name, model, *, meter=None, **kwargs):
    return await run_single_shot(
        item,
        get_arm(arm_name),
        ctx_factory=ctx_factory(db, seeded),
        llm=make_llm(),
        meter=meter or Meter(),
        client_factory=model.factory,
        **kwargs,
    )


class TestSingleShot:
    async def test_classic_records_candidates_rank_provenance_usage_and_the_instruction(
        self, db_session, seeded, item, no_network
    ):
        meter = Meter()
        model = PlainModel([say(ANSWER)], cached_tokens=30)

        gen = await shoot(db_session, seeded, item, "classic", model, meter=meter)

        assert gen.status == "ok" and gen.error is None
        assert (gen.arm, gen.item_id, gen.repeat) == ("classic", item.id, 0)
        assert gen.answer == ANSWER
        assert gen.cited_keys == []  # the Classic shape cites nothing
        top = gen.candidates[0]
        assert (top.key, top.rank, top.source_type, top.file_path) == (
            VERIFY_KEY,
            1,
            "symbol",
            SECURITY,
        )
        assert [(hit.channel, hit.rank) for hit in top.channels] == [("dense", 1)]
        assert [c.rank for c in gen.candidates] == list(range(1, len(gen.candidates) + 1))
        assert VERIFY_KEY in [c.key for c in gen.pool]
        assert gen.channel_trace[0]["channel"] == "dense"
        assert gen.degraded == [] and gen.flagged is False

        (usage,) = gen.usages
        assert (usage.kind, usage.input_tokens, usage.cached_input_tokens) == ("generate", 100, 30)
        assert meter.usages == gen.usages
        assert model.requests[0]["input"][-1]["content"].endswith(f"\n\n{EVAL_INSTRUCTION}")
        assert gen.config_hash == get_arm("classic").config_hash()
        assert gen.model == "test-model" and gen.prompt_version.startswith("single-shot-")
        assert len(gen.record_key) == 64

    async def test_hybrid_records_cited_keys_and_the_channels_that_found_each_candidate(
        self, db_session, seeded, item, no_network
    ):
        gen = await shoot(db_session, seeded, item, "hybrid", PlainModel([say(ANSWER)]))

        assert gen.status == "ok"
        assert gen.cited_keys == [VERIFY_KEY]
        top = next(c for c in gen.candidates if c.key == VERIFY_KEY)
        assert {"dense", "lexical"} <= {hit.channel for hit in top.channels}
        assert {entry["channel"] for entry in gen.channel_trace} == {"dense", "lexical", "symbol"}
        assert VERIFY_KEY in [c.key for c in gen.pool]

    async def test_a_hyde_draft_is_metered_as_its_own_usage(
        self, db_session, seeded, item, no_network
    ):
        model = PlainModel(
            [say('{"snippet": "def verify_password(): bcrypt.checkpw()"}'), say(ANSWER)]
        )

        gen = await shoot(db_session, seeded, item, "hybrid_hyde", model)

        assert gen.status == "ok"
        assert [usage.kind for usage in gen.usages] == ["hyde", "generate"]
        assert model.requests[0]["text"]["format"]["name"] == "hypothetical_snippet"
        assert gen.degraded == []

    async def test_a_degraded_reranker_is_an_error_record_not_a_result(
        self, db_session, seeded, item, no_network, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

        gen = await shoot(db_session, seeded, item, "hybrid_rerank", PlainModel([say(ANSWER)]))

        assert gen.status == "error" and gen.error == RERANKER_DEGRADED
        assert gen.answer == ANSWER  # kept for diagnosis; the status keeps it from being scored
        assert [usage.kind for usage in gen.usages] == ["generate"]  # the spend is still recorded
        assert gen.degraded and gen.degraded[0]["stage"] == "rerank"

    async def test_a_working_reranker_adds_its_reported_cost(
        self, db_session, seeded, item, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")

        def respond_documents(request: httpx.Request) -> httpx.Response:
            documents = json.loads(request.content)["documents"]
            results = [{"index": i, "relevance_score": 1 - i / 100} for i in range(len(documents))]
            return httpx.Response(200, json={"results": results, "usage": {"cost": 0.002}})

        with respx.mock(assert_all_mocked=True) as router:
            router.post(COHERE_RERANK_URL).mock(side_effect=respond_documents)
            gen = await shoot(db_session, seeded, item, "hybrid_rerank", PlainModel([say(ANSWER)]))

        assert gen.status == "ok", gen.error
        rerank = [usage for usage in gen.usages if usage.kind == "rerank"]
        assert [(u.provider, u.reported_cost_usd) for u in rerank] == [("cohere", 0.002)]
        assert gen.reported_cost() == 0.002

    async def test_a_model_failure_is_an_error_record_with_the_spend_so_far(
        self, db_session, seeded, item, no_network
    ):
        model = PlainModel([Turn(error=RuntimeError("provider down"))])

        gen = await shoot(db_session, seeded, item, "classic", model)

        assert gen.status == "error" and gen.error == "RuntimeError: provider down"
        assert gen.answer == ""

    async def test_an_agent_arm_is_refused(self, db_session, seeded, item):
        with pytest.raises(ValueError, match="not a single-shot arm"):
            await shoot(db_session, seeded, item, "agent", PlainModel())


# --- the agent --------------------------------------------------------------------


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("agent-clone")
    sample_repo._git(root, "init", "-q", "-b", "main")
    (root / "app" / "auth").mkdir(parents=True)
    (root / SECURITY).write_text("def verify_password():\n    return True\n", encoding="utf-8")
    sample_repo.commit_all(root, "base")
    return root, sample_repo.head_sha(root)


def agent_arm(**config_updates) -> Arm:
    config = agent_config()
    if config_updates:
        config = config.model_copy(update=config_updates)
    return Arm("agent_test", config)


async def run_agent_for(db, seeded, item, clone, model, arm=None, **kwargs):
    root, base = clone
    return await run_agent_arm(
        item,
        arm or agent_arm(),
        repository=RepoSnapshot.from_repository(seeded.repo),
        session_factory=serialized(session_factory_for(db.bind)),
        llm=make_llm(),
        meter=kwargs.pop("meter", None) or Meter(),
        registry=build_clone_registry(root, base),
        client_factory=model.factory,
        embed=fake_embedder(),
        **kwargs,
    )


class TestAgent:
    async def test_a_run_records_steps_tools_evidence_stop_reason_and_tokens(
        self, db_session, seeded, item, clone, no_network
    ):
        model = ScriptedModel(
            [
                turn(
                    call("read_file", {"path": SECURITY}),
                    call("search_code", {"query": "verify_password bcrypt"}),
                ),
                turn(finish(ANSWER)),
            ]
        )

        gen = await run_agent_for(db_session, seeded, item, clone, model)

        assert gen.status == "ok", gen.error
        assert gen.stop_reason == "finished"
        assert gen.answer.endswith(f"- {SECURITY}")
        assert gen.cited_keys == [] or all(key.startswith("F:") for key in gen.cited_keys)

        calls = [step for step in gen.steps if step.kind == "tool_call"]
        assert {step.tool for step in calls} == {"read_file", "search_code", "finish"}
        read = next(step for step in calls if step.tool == "read_file")
        assert read.status == "ok" and f'"path": "{SECURITY}"' in read.arguments
        assert read.evidence_keys == [code_key(SECURITY, 1, 2)]
        assert read.worker_id is None
        assert any(step.kind == "seed" for step in gen.steps)
        assert gen.unavailable_tool_results == 0 and gen.flagged is False

        # The product's own counter and the harness's meter agree when nothing is missed.
        assert gen.run_tokens.input_tokens == gen.metered_tokens("agent")[0] == 200
        assert gen.run_tokens.output_tokens == gen.metered_tokens("agent")[1] == 40
        assert {usage.kind for usage in gen.usages} == {"agent"}
        assert gen.prompt_version and gen.config_hash == agent_arm().config_hash()
        # The question the agent saw carries the eval-only instruction.
        assert any(EVAL_INSTRUCTION in text for text in model.input_texts(0))

    async def test_a_file_the_clone_cannot_serve_is_counted_and_flags_the_run(
        self, db_session, seeded, item, clone, no_network
    ):
        model = ScriptedModel([turn(call("read_file", {"path": SERVICE})), turn(finish(ANSWER))])

        gen = await run_agent_for(db_session, seeded, item, clone, model)

        assert gen.status == "ok"
        assert gen.unavailable_tool_results == 1
        assert gen.flagged is True

    async def test_a_failed_run_is_an_error_record(
        self, db_session, seeded, item, clone, no_network
    ):
        model = ScriptedModel([Turn(error=RuntimeError("model down"))])

        gen = await run_agent_for(db_session, seeded, item, clone, model)

        assert gen.status == "error"
        assert gen.error.startswith("internal:")
        assert gen.stop_reason == "error"

    async def test_a_degraded_reranker_inside_the_run_is_an_error_record(
        self, db_session, seeded, item, clone, no_network, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        arm = agent_arm(rerank=RerankConfig(kind="cohere"))
        model = ScriptedModel([turn(finish(ANSWER))])

        gen = await run_agent_for(db_session, seeded, item, clone, model, arm=arm)

        assert gen.status == "error" and gen.error == RERANKER_DEGRADED

    async def test_the_cohere_cost_inside_a_run_is_metered(
        self, db_session, seeded, item, clone, monkeypatch
    ):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key")

        def respond(request: httpx.Request) -> httpx.Response:
            documents = json.loads(request.content)["documents"]
            results = [{"index": i, "relevance_score": 1 - i / 100} for i in range(len(documents))]
            return httpx.Response(200, json={"results": results, "usage": {"cost": 0.002}})

        arm = agent_arm(rerank=RerankConfig(kind="cohere"))
        model = ScriptedModel(
            [turn(call("search_code", {"query": "verify_password"})), turn(finish(ANSWER))]
        )
        with respx.mock(assert_all_mocked=True) as router:
            router.post(COHERE_RERANK_URL).mock(side_effect=respond)
            gen = await run_agent_for(db_session, seeded, item, clone, model, arm=arm)

        assert gen.status == "ok", gen.error
        rerank = [usage for usage in gen.usages if usage.kind == "rerank"]
        assert len(rerank) == 2  # the seed retrieval and the search_code call
        assert gen.reported_cost() == pytest.approx(0.004)

    async def test_a_single_shot_arm_is_refused(self, db_session, seeded, item, clone):
        with pytest.raises(ValueError, match="not an agent arm"):
            await run_agent_for(
                db_session, seeded, item, clone, ScriptedModel(), arm=get_arm("classic")
            )


# --- auto -------------------------------------------------------------------------


def generation(item_id: str, arm: str, **fields) -> Generation:
    base: dict[str, Any] = {
        "record_key": f"key-{item_id}-{arm}",
        "item_id": item_id,
        "arm": arm,
        "config_hash": f"hash-{arm}",
        "model": "m",
        "answer": f"answer from {arm}",
        "usages": [Usage(provider="p", model="m", kind="generate", reported_cost_usd=0.01)],
        "latency_ms": 100.0,
    }
    base.update(fields)
    return Generation(**base)


ROUTES = {
    "local": "hybrid_rerank",
    "relational": "structural_rerank",
    "history": "structural_rerank",
    "global": "agent",
    "out_of_scope": "classic",
}


class TestAuto:
    def test_every_preset_the_router_can_resolve_to_has_an_arm(self):
        presets = {*ROUTE_PRESETS.values(), FALLBACK_PRESET}
        assert presets <= set(AUTO_ARM_BY_PRESET)
        assert FALLBACK_ARM == "structural_rerank"
        with pytest.raises(KeyError, match="no evaluation arm"):
            arm_for_preset("something_new")

    @pytest.mark.parametrize(("route", "arm"), list(ROUTES.items()))
    async def test_a_route_resolves_to_the_arm_that_runs_its_preset(self, route, arm):
        item = make_gold_item(f"A {route} question")

        record = await route_item(item, decider=RouteDecider(route))

        assert (record.route, record.target_arm, record.fallback_reason) == (route, arm, None)
        (decision,) = record.usages
        assert (decision.kind, decision.provider, decision.reported_cost_usd) == (
            "decision",
            "fake",
            0.00004,
        )
        assert decision.input_tokens == 300

    async def test_a_failing_decider_falls_back_to_structural_rerank(self):
        record = await route_item(make_gold_item(), decider=RouteDecider(error=RuntimeError("x")))
        assert (record.target_arm, record.fallback_reason, record.route) == (
            "structural_rerank",
            "error",
            None,
        )
        assert record.usages == []

    async def test_a_decider_that_times_out_falls_back(self):
        record = await route_item(make_gold_item(), decider=RouteDecider(delay=1.0), timeout=0.05)
        assert (record.target_arm, record.fallback_reason) == ("structural_rerank", "timeout")

    async def test_a_low_confidence_route_falls_back_but_keeps_the_decision_cost(self):
        record = await route_item(make_gold_item(), decider=RouteDecider("global", 0.2))
        assert (record.route, record.target_arm, record.fallback_reason) == (
            "global",
            "structural_rerank",
            "low_confidence",
        )
        assert len(record.usages) == 1

    async def test_no_decision_model_falls_back_as_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        record = await route_item(make_gold_item())
        assert (record.target_arm, record.fallback_reason) == ("structural_rerank", "unavailable")

    def test_compose_copies_the_target_generation_with_the_decision_added(self):
        items = [make_gold_item(f"question {route}") for route in ROUTES]
        routes = [
            RouteRecord(
                item_id=item.id,
                route=route,
                confidence=0.9,
                resolved_preset="x",
                target_arm=arm,
                model="router",
                usages=[
                    Usage(
                        provider="jev",
                        model="router",
                        kind="decision",
                        reported_cost_usd=0.00004,
                        latency_ms=12.0,
                    )
                ],
            )
            for item, (route, arm) in zip(items, ROUTES.items(), strict=True)
        ]
        by_key = {
            (item.id, arm): generation(item.id, arm)
            for item in items
            for arm in set(ROUTES.values())
        }

        composed = compose_auto(routes, by_key)

        assert composed.missing == []
        assert [g.composed_from for g in composed.generations] == list(ROUTES.values())
        for gen, route in zip(composed.generations, routes, strict=True):
            assert gen.arm == AUTO and gen.route == route
            assert gen.answer == f"answer from {route.target_arm}"
            assert gen.config_hash == get_arm(AUTO).config_hash()
            assert [u.kind for u in gen.usages] == ["generate", "decision"]
            assert gen.reported_cost() == pytest.approx(0.01004)
            assert gen.latency_ms == 112.0
            assert gen.record_key != by_key[(route.item_id, route.target_arm)].record_key
        assert len({g.record_key for g in composed.generations}) == len(ROUTES)

    def test_a_missing_target_is_reported_not_raised(self):
        present, absent = make_gold_item("present"), make_gold_item("absent")
        routes = [
            RouteRecord(item_id=i.id, resolved_preset="x", target_arm="agent")
            for i in (present, absent)
        ]

        composed = compose_auto(routes, {(present.id, "agent"): generation(present.id, "agent")})

        assert [g.item_id for g in composed.generations] == [present.id]
        assert composed.missing == [(absent.id, "agent")]

    def test_a_target_that_errored_stays_an_error(self):
        item = make_gold_item()
        route = RouteRecord(item_id=item.id, resolved_preset="x", target_arm="classic")
        broken = generation(item.id, "classic", status="error", error="reranker_degraded")

        (gen,) = compose_auto([route], {(item.id, "classic"): broken}).generations

        assert gen.status == "error" and gen.error == "reranker_degraded" and gen.arm == AUTO
