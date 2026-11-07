"""Who may run what on the stream route, and what a run costs the free tier.

Mirrors the chat route's quota rules: a free-tier user is charged one message for
an answer that was generated, and nothing for a run that failed, was cancelled or
found no context. A key of the user's own never touches the counter. Agent presets
need that key (one run is tens of model calls on the operator's), and a model that
cannot call tools is refused before anything is spent.

Priority tests: these are the money cases.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from app.core.config import settings
from app.core.database import get_async_db
from app.services import llm_config
from app.services.entitlements import FREE_CHAT_MESSAGES
from app.services.retrieval.config import (
    HYBRID,
    PRESETS,
    PipelineConfig,
    QueryConfig,
    RerankConfig,
)
from tests.factories import fake_vector
from tests.fixtures.agent_run import ScriptedModel, SufficiencyDecider, finish, turn
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    Committed,
    install,
    make_world,
    only_run,
    runs_of,
    stream,
    stream_url,
    turns_of,
)
from tests.fixtures.retrieval import fake_embedder
from tests.helpers import authenticate

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")


@pytest.fixture
def server_key(monkeypatch):
    """The operator's free-tier credential is configured."""
    stub = SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)


@pytest.fixture
def no_server_key(monkeypatch):
    stub = SimpleNamespace(AI_API_KEY="", AI_MODEL="", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)


@pytest.fixture
async def free_world(client, db_session, server_key):
    return await make_world(client, db_session, byok=False)


@pytest.fixture
async def world(client, db_session):
    return await make_world(client, db_session)


async def used(db_session, user) -> int:
    await db_session.refresh(user)
    return user.free_chat_messages_used


class TestFreeTier:
    async def test_an_agent_preset_is_refused_and_no_model_is_called(
        self, app, client, db_session, free_world, monkeypatch
    ):
        model = ScriptedModel([turn(finish("never"))])
        probe = ScriptedModel()
        monkeypatch.setattr("app.services.tool_support.AsyncOpenAI", probe.factory)
        install(app, db_session, model, decider=SufficiencyDecider(1.0))

        for preset in ("deep_agent", "deep_agent_workers"):
            response = await client.post(
                stream_url(free_world.repo), json={"question": QUESTION, "preset": preset}
            )

            assert response.status_code == 402
            assert "own API key" in response.json()["detail"]

        assert model.requests == []
        assert probe.requests == []
        assert await runs_of(db_session, free_world.repo) == []
        assert await used(db_session, free_world.user) == 0

    async def test_a_single_shot_answer_is_charged_exactly_one_message(
        self, app, client, db_session, free_world
    ):
        install(app, db_session, AnyModel())

        _, events = await stream(client, free_world.repo, preset="hybrid")

        assert events[-1]["type"] == "done"
        assert await used(db_session, free_world.user) == 1
        assert (await only_run(db_session, free_world.repo)).status == "done"

    async def test_several_model_calls_are_still_one_message(
        self, app, client, db_session, free_world, monkeypatch
    ):
        # Rewriting the question, reranking and answering each reach the model.
        many = PipelineConfig(
            name="many_calls",
            query=QueryConfig(condense=True, transform="hyde"),
            channels=HYBRID.channels,
            rerank=RerankConfig(kind="llm", candidate_pool=10, top_n=5),
        )
        monkeypatch.setitem(PRESETS, "many_calls", many)
        model = AnyModel()
        for module in ("app.services.retrieval.query", "app.services.retrieval.rerank.llm"):
            monkeypatch.setattr(f"{module}.AsyncOpenAI", model.factory)
        install(app, db_session, model)

        _, events = await stream(
            client,
            free_world.repo,
            preset="many_calls",
            history=[
                {"role": "user", "content": "What is this?"},
                {"role": "assistant", "content": "A web API."},
            ],
        )

        assert events[-1]["type"] == "done"
        assert len(model.requests) >= 3
        assert await used(db_session, free_world.user) == 1

    async def test_a_run_that_finds_no_context_is_not_charged(
        self, app, client, db_session, server_key
    ):
        from tests.factories import make_ingested_repo, make_user

        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await authenticate(client, user)
        model = AnyModel()
        install(app, db_session, model)

        _, events = await stream(client, repo, preset="classic")

        assert events[-1]["type"] == "done"
        assert events[-1]["data"]["stop_reason"] == "no_context"
        assert "No relevant code" in events[-1]["data"]["answer"]
        assert model.requests == []
        assert await used(db_session, user) == 0
        assert len(await turns_of(db_session, repo)) == 1

    async def test_a_failed_run_is_not_charged(self, app, client, db_session, free_world):
        failure = APIConnectionError(request=httpx.Request("POST", "https://x"))
        install(app, db_session, ScriptedModel([turn(error=failure)]))

        _, events = await stream(client, free_world.repo, preset="hybrid")

        assert events[-1]["type"] == "error"
        assert await used(db_session, free_world.user) == 0
        assert await turns_of(db_session, free_world.repo) == []

    async def test_a_provider_status_error_is_not_charged_either(
        self, app, client, db_session, free_world
    ):
        response = httpx.Response(503, request=httpx.Request("POST", "https://x"))
        failure = APIStatusError("overloaded", response=response, body=None)
        install(app, db_session, ScriptedModel([turn(error=failure)]))

        _, events = await stream(client, free_world.repo, preset="hybrid")

        assert events[-1]["data"]["kind"] == "provider"
        assert await used(db_session, free_world.user) == 0

    async def test_the_sixth_question_after_the_allowance_is_refused_without_a_model_call(
        self, app, client, db_session, server_key
    ):
        world = await make_world(
            client, db_session, byok=False, free_chat_messages_used=FREE_CHAT_MESSAGES
        )
        model = AnyModel()
        install(app, db_session, model)

        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "hybrid"}
        )

        assert response.status_code == 402
        assert "free chat questions" in response.json()["detail"]
        assert model.requests == []
        assert await runs_of(db_session, world.repo) == []

    async def test_no_key_at_all_is_a_402(self, app, client, db_session, no_server_key):
        world = await make_world(client, db_session, byok=False)
        model = AnyModel()
        install(app, db_session, model)

        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "hybrid"}
        )

        assert response.status_code == 402
        assert "Add your own API key" in response.json()["detail"]
        assert model.requests == []


class TestOwnKey:
    async def test_a_run_on_the_users_own_key_never_touches_the_counter(
        self, app, client, db_session, server_key
    ):
        world = await make_world(client, db_session, free_chat_messages_used=3)
        install(app, db_session, AnyModel())

        for preset in ("hybrid", "classic"):
            await stream(client, world.repo, preset=preset)

        assert await used(db_session, world.user) == 3

    async def test_an_agent_run_on_the_users_own_key_is_free(self, app, client, db_session, world):
        install(
            app, db_session, ScriptedModel([turn(finish("done"))]), decider=SufficiencyDecider(1.0)
        )

        _, events = await stream(client, world.repo, preset="deep_agent")

        assert events[-1]["type"] == "done"
        assert await used(db_session, world.user) == 0

    async def test_the_runs_use_the_users_credential(self, app, client, db_session, world):
        model = AnyModel()
        install(app, db_session, model)

        await stream(client, world.repo, preset="hybrid")

        assert model.client_inits[0]["api_key"] == "sk-user-secret"


class TestQuotaUnderConcurrency:
    async def test_two_requests_at_the_last_free_message_cannot_overspend(
        self, app, client, engine, server_key
    ):
        """Each request has its own connection, so both can pass the check at nine."""
        import asyncio

        async def request_session():
            async with committed.maker() as session:
                yield session

        committed = Committed(engine)
        app.dependency_overrides[get_async_db] = request_session
        try:
            vector = fake_vector(0.5)
            user, repo = await committed.user_with_repo(
                byok=False, used=FREE_CHAT_MESSAGES - 1, question_vector=vector
            )
            await authenticate(client, user)
            install(
                app,
                None,
                AnyModel(),
                sessions=committed.maker,
                embed=fake_embedder({QUESTION: vector}),
            )

            responses = await asyncio.gather(
                *(
                    client.post(stream_url(repo), json={"question": QUESTION, "preset": "classic"})
                    for _ in range(2)
                )
            )

            assert {r.status_code for r in responses} <= {200, 402}
            assert 200 in {r.status_code for r in responses}
            assert await committed.used(user) == FREE_CHAT_MESSAGES
        finally:
            await committed.drop()


class TestToolSupport:
    @staticmethod
    def probe(outcome):
        """A stand-in for the client the lazy probe builds."""
        calls: list[dict] = []

        class Fake:
            def __init__(self, **kwargs):
                self.responses = self

            async def create(self, **kwargs):
                calls.append(kwargs)
                if isinstance(outcome, BaseException):
                    raise outcome
                items = [SimpleNamespace(type="function_call")] if outcome else []
                return SimpleNamespace(output=items)

        return Fake, calls

    async def test_a_model_that_cannot_call_tools_is_refused_with_the_reason(
        self, app, client, db_session, world
    ):
        world.user.ai_supports_tools = False
        await db_session.flush()
        model = ScriptedModel([turn(finish("never"))])
        install(app, db_session, model, decider=SufficiencyDecider(1.0))

        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        assert response.status_code == 400
        assert "tool calling" in response.json()["detail"]
        assert model.requests == []
        assert await runs_of(db_session, world.repo) == []

    async def test_single_shot_presets_do_not_need_tools(self, app, client, db_session, world):
        world.user.ai_supports_tools = False
        await db_session.flush()
        install(app, db_session, AnyModel())

        _, events = await stream(client, world.repo, preset="hybrid")

        assert events[-1]["type"] == "done"

    async def test_an_unmeasured_model_is_probed_once_and_the_result_stored(
        self, app, client, db_session, world, monkeypatch
    ):
        world.user.ai_supports_tools = None
        await db_session.flush()
        fake, calls = self.probe(True)
        monkeypatch.setattr("app.services.tool_support.AsyncOpenAI", fake)
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("a")), turn(finish("b"))]),
            decider=SufficiencyDecider(1.0),
        )

        for _ in range(2):
            _, events = await stream(client, world.repo, preset="deep_agent")
            assert events[-1]["type"] == "done"

        assert len(calls) == 1
        await db_session.refresh(world.user)
        assert world.user.ai_supports_tools is True
        assert world.user.ai_tools_checked_at is not None

    async def test_a_probe_that_finds_no_tool_support_refuses_and_remembers(
        self, app, client, db_session, world, monkeypatch
    ):
        world.user.ai_supports_tools = None
        await db_session.flush()
        fake, calls = self.probe(False)
        monkeypatch.setattr("app.services.tool_support.AsyncOpenAI", fake)
        install(app, db_session, ScriptedModel(), decider=SufficiencyDecider(1.0))

        first = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )
        second = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        assert (first.status_code, second.status_code) == (400, 400)
        assert len(calls) == 1
        await db_session.refresh(world.user)
        assert world.user.ai_supports_tools is False

    async def test_a_probe_that_gets_no_answer_leaves_it_unmeasured_and_asks_again(
        self, app, client, db_session, world, monkeypatch
    ):
        world.user.ai_supports_tools = None
        await db_session.flush()
        outage = APIConnectionError(request=httpx.Request("POST", "https://x"))
        fake, calls = self.probe(outage)
        monkeypatch.setattr("app.services.tool_support.AsyncOpenAI", fake)
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("a")), turn(finish("b"))]),
            decider=SufficiencyDecider(1.0),
        )

        for _ in range(2):
            _, events = await stream(client, world.repo, preset="deep_agent")
            assert events[-1]["type"] == "done"

        assert len(calls) == 2
        await db_session.refresh(world.user)
        assert world.user.ai_supports_tools is None
        assert world.user.ai_tools_checked_at is None
