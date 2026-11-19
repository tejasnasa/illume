"""``ask_illume``: Illume's own answer over MCP, through the real transport.

The tool drives the same ``RunSession`` the web chat does, so these tests check
what it adds (its schema, the ``source`` marker, no chat history, progress,
disconnect-as-cancel, its limits) and that every gate and every charge matches the
streaming route's. The model, embedder and decider are scripted; the database and
the run slots' Redis are real. Data is created before ``mcp_client`` is requested,
because a client's token checks share the test's one connection.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.mcp import ask, limits
from app.mcp.ask import INPUT_SCHEMA, MAX_QUESTION_CHARS, citation_url
from app.mcp.limits import MCP_ASK_PER_HOUR, MCP_CALLS_PER_MINUTE, window_key
from app.models import AgentRun, ChatMessage
from app.services import llm_config
from app.services.agent.session import RunKit
from app.services.agent.slots import slot_key
from app.services.entitlements import FREE_CHAT_MESSAGES
from tests.factories import make_ingested_repo
from tests.fixtures.agent_run import PlanDecider, ScriptedModel, call, finish, turn
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    Hold,
    RawRequest,
    World,
    install,
    only_run,
    slot_count,
    step_rows,
    stream,
    turns_of,
    wait_until,
)
from tests.fixtures.retrieval import RETRIEVAL_FIXTURE, fake_embedder, seed_repo
from tests.helpers import authenticate
from tests.integration.api.test_agent_stream_auto import Router

pytestmark = pytest.mark.integration

SECURITY_PATH = "app/auth/security.py"
DEEP_ANSWER = "Passwords are checked in app/auth/security.py."


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    """A key in a developer's environment must not turn on the model-backed stages."""
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")


@pytest.fixture
def server_key(monkeypatch):
    """The operator's free-tier credential is configured."""
    stub = SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)


@pytest.fixture
def no_server_key(monkeypatch):
    stub = SimpleNamespace(AI_API_KEY="", AI_MODEL="", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)


async def make_world(db_session, user, *, byok: bool, **fields: Any) -> World:
    """Puts the token's user on a tier and seeds the repository the tests ask about."""
    user.ai_api_key = "sk-user-secret" if byok else None
    user.ai_provider = "openai" if byok else None
    user.ai_model = "gpt-4o-mini" if byok else None
    user.ai_supports_tools = True if byok else None
    for name, value in fields.items():
        setattr(user, name, value)
    seeded = await seed_repo(db_session, user, RETRIEVAL_FIXTURE, name="ask-mine")
    await db_session.flush()
    return World(user=user, seeded=seeded)


@pytest.fixture
async def world(db_session, mcp_user) -> World:
    return await make_world(db_session, mcp_user, byok=True)


@pytest.fixture
async def free_world(db_session, mcp_user, server_key) -> World:
    return await make_world(db_session, mcp_user, byok=False)


def use(mcp_run_kit, world: World | None, model: Any, **kit: Any) -> Any:
    """Gives the server's runs a scripted model and an embedder.

    With a ``world`` the question embeds next to one of its symbols, so retrieval
    finds something to answer from; without one it finds nothing.
    """
    if world is not None:
        vector = list(world.seeded.symbol_embeddings[(SECURITY_PATH, "verify_password")].embedding)
        kit.setdefault("embed", fake_embedder({QUESTION: vector}))
    kit.setdefault("embed", fake_embedder())
    kit.setdefault("client_factory", model.factory)
    mcp_run_kit.kit = RunKit(**kit)
    return model


def deep_model() -> ScriptedModel:
    return ScriptedModel(
        [turn(call("search_symbols", {"name": "verify_password"})), turn(finish(DEEP_ANSWER))]
    )


async def ask_tool(client: Any, world: World, mode: str | None = None, **extra: Any):
    arguments: dict[str, Any] = {"repo": str(world.repo.repo_number), "question": QUESTION}
    if mode is not None:
        arguments["mode"] = mode
    return await client.call_tool("ask_illume", {**arguments, **extra})


async def used(db_session, user) -> int:
    await db_session.refresh(user)
    return user.free_chat_messages_used


# --- the tool's definition -------------------------------------------------------------


class TestDefinition:
    async def test_it_is_listed_with_a_strict_schema_and_honest_annotations(self, mcp_client):
        tool = next(t for t in (await mcp_client.list_tools()).tools if t.name == "ask_illume")

        assert tool.title == "Ask Illume"
        assert tool.input_schema == INPUT_SCHEMA
        assert tool.input_schema["additionalProperties"] is False
        assert tool.input_schema["required"] == ["repo", "question"]
        assert tool.input_schema["properties"]["mode"]["enum"] == ["quick", "auto", "deep"]
        assert tool.input_schema["properties"]["mode"]["default"] == "quick"
        question = tool.input_schema["properties"]["question"]
        assert (question["minLength"], question["maxLength"]) == (1, MAX_QUESTION_CHARS)
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is False
        assert tool.annotations.open_world_hint is True
        assert tool.annotations.title == "Ask Illume"

    async def test_the_server_registers_the_schema_for_argument_checks(self, mcp_app):
        assert mcp_app.server.get_tool_input_schema("ask_illume") == INPUT_SCHEMA

    @pytest.mark.parametrize(
        "arguments",
        [
            {"question": QUESTION},
            {"repo": "1"},
            {"repo": "1", "question": "   "},
            {"repo": "1", "question": "q", "mode": "thorough"},
            {"repo": "1", "question": "x" * (MAX_QUESTION_CHARS + 1)},
        ],
    )
    async def test_bad_arguments_are_an_error_result(self, mcp_client, arguments):
        try:
            result = await mcp_client.call_tool("ask_illume", arguments)
        except Exception:
            # The SDK may reject a schema violation before the handler runs.
            return

        assert result.is_error is True


# --- quick, auto and deep ----------------------------------------------------------------


class TestQuestionLimit:
    async def test_a_question_at_the_limit_is_answered(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        use(mcp_run_kit, world, AnyModel("An answer."))

        result = await ask_tool(mcp_client, world, question="x" * MAX_QUESTION_CHARS)

        assert result.is_error is not True

    async def test_a_question_over_the_limit_is_an_error_and_no_run(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        use(mcp_run_kit, world, AnyModel("An answer."))

        try:
            result = await ask_tool(mcp_client, world, question="x" * (MAX_QUESTION_CHARS + 1))
        except Exception:
            # The SDK may reject a schema violation before the handler runs.
            result = None

        assert result is None or result.is_error is True
        assert await _runs(db_session, world.user) == []


class TestModes:
    async def test_quick_on_the_free_tier_answers_with_classic_and_records_the_run(
        self, db_session, mcp_run_kit, free_world, mcp_client
    ):
        model = use(mcp_run_kit, free_world, AnyModel("Passwords are checked in security.py."))

        result = await ask_tool(mcp_client, free_world)

        assert result.is_error is not True
        data = result.structured_content
        assert data["answer"] == "Passwords are checked in security.py."
        assert data["preset"] == "classic"
        assert data["citations"], "the retrieved sources are cited"
        assert result.content[0].text.startswith(data["answer"])
        assert len(model.requests) == 1
        run = await only_run(db_session, free_world.repo)
        assert (run.status, run.preset, run.answer) == ("done", "classic", data["answer"])
        assert run.config["source"] == "mcp"
        assert run.user_id == free_world.user.id

    async def test_quick_with_an_own_key_uses_hybrid_rerank(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        use(mcp_run_kit, world, AnyModel("An answer."))

        result = await ask_tool(mcp_client, world, "quick")

        assert result.structured_content["preset"] == "hybrid_rerank"
        assert (await only_run(db_session, world.repo)).preset == "hybrid_rerank"

    async def test_the_mode_defaults_to_quick(self, db_session, mcp_run_kit, world, mcp_client):
        use(mcp_run_kit, world, AnyModel("An answer."))

        result = await ask_tool(mcp_client, world)

        assert result.structured_content["preset"] == "hybrid_rerank"

    @pytest.mark.parametrize(
        ("label", "preset"), [("local", "hybrid_rerank"), ("relational", "structural")]
    )
    async def test_auto_resolves_and_records_the_route_like_the_web_chat(
        self, db_session, mcp_run_kit, world, mcp_client, label, preset
    ):
        use(mcp_run_kit, world, AnyModel("An answer."), decider=Router(label, 0.9))

        result = await ask_tool(mcp_client, world, "auto")

        assert result.is_error is not True
        assert result.structured_content["preset"] == preset
        run = await only_run(db_session, world.repo)
        assert (run.preset, run.status) == (preset, "done")
        assert run.config["source"] == "mcp"
        [route] = [
            s
            for s in await step_rows(db_session, run.id)
            if s.kind == "decision" and s.name == "route"
        ]
        assert route.payload["requested_preset"] == "auto"
        assert route.payload["resolved_preset"] == preset

    async def test_deep_runs_the_agent_and_persists_its_steps(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        model = use(mcp_run_kit, world, deep_model(), decider=PlanDecider(1.0))

        result = await ask_tool(mcp_client, world, "deep")

        assert result.is_error is not True
        assert result.structured_content["answer"] == DEEP_ANSWER
        assert result.structured_content["preset"] == "deep_agent"
        run = await only_run(db_session, world.repo)
        assert (run.status, run.preset, run.config["source"]) == ("done", "deep_agent", "mcp")
        assert run.tool_calls and run.tool_calls >= 1
        steps = await step_rows(db_session, run.id)
        assert any(s.kind == "event" and s.name == "tool_call" for s in steps)
        assert len(model.agent_requests) == 2


# --- what a run records ----------------------------------------------------------------


class TestRecording:
    async def test_no_chat_history_is_written(self, db_session, mcp_run_kit, world, mcp_client):
        use(mcp_run_kit, world, deep_model(), decider=PlanDecider(1.0))

        result = await ask_tool(mcp_client, world, "deep")

        assert result.is_error is not True
        assert await turns_of(db_session, world.repo) == []
        mine = select(ChatMessage).where(ChatMessage.user_id == world.user.id)
        rows = (await db_session.execute(mine)).scalars().all()
        assert list(rows) == []
        run = await only_run(db_session, world.repo)
        assert run.chat_message_id is None and run.status == "done"

    async def test_usage_matches_what_the_model_reported(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        model = use(
            mcp_run_kit,
            world,
            ScriptedModel(
                [
                    turn(call("search_symbols", {"name": "verify_password"}), input_tokens=300),
                    turn(finish(DEEP_ANSWER), input_tokens=500, output_tokens=40),
                ]
            ),
            decider=PlanDecider(1.0),
        )

        result = await ask_tool(mcp_client, world, "deep")

        usage = result.structured_content["usage"]
        assert usage["input_tokens"] == 800
        assert usage["output_tokens"] > 0
        run = await only_run(db_session, world.repo)
        assert run.usage["input_tokens"] == usage["input_tokens"]
        assert run.usage["output_tokens"] == usage["output_tokens"]
        assert len(model.requests) == 2

    async def test_the_citation_links_follow_the_chat_cards(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        symbol = world.symbol_key
        use(
            mcp_run_kit,
            world,
            ScriptedModel(
                [
                    turn(call("search_symbols", {"name": "verify_password"})),
                    turn(finish(f"It is in app/auth/security.py [{symbol}].")),
                ]
            ),
            decider=PlanDecider(1.0),
        )

        result = await ask_tool(mcp_client, world, "deep")

        repo = world.repo
        ref = repo.ingested_commit_sha or repo.ingested_branch or "master"
        [citation] = [c for c in result.structured_content["citations"] if c["key"] == symbol]
        assert citation["path"] == "app/auth/security.py"
        start, end = citation["lines"].split("-")
        assert citation["url"] == (
            f"{repo.github_url}/blob/{ref}/app/auth/security.py#L{start}-L{end}"
        )
        assert citation["url"] in result.content[0].text

    @pytest.mark.parametrize(
        ("citation", "expected"),
        [
            (
                {"source_type": "symbol", "file_path": "a/b.py", "start_line": 3, "end_line": 9},
                "https://github.com/o/r/blob/abc/a/b.py#L3-L9",
            ),
            (
                {"source_type": "file", "file_path": "a/b.py"},
                "https://github.com/o/r/blob/abc/a/b.py",
            ),
            ({"source_type": "commit", "commit_hash": "f00"}, "https://github.com/o/r/commit/f00"),
            ({"source_type": "pull_request", "pr_number": 7}, "https://github.com/o/r/pull/7"),
            ({"source_type": "document", "file_path": "README.md"}, None),
        ],
    )
    def test_citation_urls_by_source_type(self, citation, expected):
        assert citation_url(citation, "https://github.com/o/r", "abc", "main") == expected

    def test_the_link_falls_back_to_the_branch_and_then_master(self):
        citation = {"source_type": "file", "file_path": "x.py"}

        assert (
            citation_url(citation, "https://g/o/r", None, "main") == "https://g/o/r/blob/main/x.py"
        )
        assert (
            citation_url(citation, "https://g/o/r", None, None) == "https://g/o/r/blob/master/x.py"
        )


# --- gates ---------------------------------------------------------------------------------


class TestGates:
    async def test_no_credential_is_an_error_and_no_run(
        self, db_session, mcp_run_kit, mcp_user, no_server_key, mcp_connect, auth_headers
    ):
        world = await make_world(db_session, mcp_user, byok=False)
        model = use(mcp_run_kit, None, AnyModel())

        async with mcp_connect(**auth_headers) as client:
            result = await ask_tool(client, world)

        assert result.is_error is True
        assert "API key" in result.content[0].text
        assert model.requests == []
        assert await _runs(db_session, world.user) == []

    @pytest.mark.parametrize("mode", ["auto", "deep"])
    async def test_auto_and_deep_need_an_own_key(
        self, db_session, mcp_run_kit, free_world, mcp_client, mode
    ):
        model = use(mcp_run_kit, free_world, AnyModel(), decider=Router("global", 0.9))

        result = await ask_tool(mcp_client, free_world, mode)

        assert result.is_error is True
        assert "own API key" in result.content[0].text
        assert model.requests == []
        assert await _runs(db_session, free_world.user) == []
        assert await used(db_session, free_world.user) == 0

    async def test_an_exhausted_free_tier_is_an_error_and_no_run(
        self, db_session, mcp_run_kit, mcp_user, server_key, mcp_connect, auth_headers
    ):
        world = await make_world(
            db_session, mcp_user, byok=False, free_chat_messages_used=FREE_CHAT_MESSAGES
        )
        model = use(mcp_run_kit, None, AnyModel())

        async with mcp_connect(**auth_headers) as client:
            result = await ask_tool(client, world)

        assert result.is_error is True
        assert "free" in result.content[0].text
        assert "settings" in result.content[0].text
        assert model.requests == []
        assert await _runs(db_session, world.user) == []

    async def test_a_claim_that_finds_the_allowance_spent_is_an_error_with_no_model_call(
        self, db_session, mcp_run_kit, mcp_user, server_key, mcp_connect, auth_headers, monkeypatch
    ):
        world = await make_world(
            db_session, mcp_user, byok=False, free_chat_messages_used=FREE_CHAT_MESSAGES
        )
        # Past the early check, as a concurrent request would get.
        monkeypatch.setattr("app.mcp.ask.FREE_CHAT_MESSAGES", FREE_CHAT_MESSAGES + 1)
        model = use(mcp_run_kit, None, AnyModel())

        async with mcp_connect(**auth_headers) as client:
            result = await ask_tool(client, world)

        assert result.is_error is True
        assert "free" in result.content[0].text
        assert model.requests == []
        assert await used(db_session, world.user) == FREE_CHAT_MESSAGES
        run = await only_run(db_session, world.repo)
        assert (run.status, run.stop_reason) == ("failed", "free_tier_exhausted")

    async def test_two_runs_in_flight_refuse_a_third_and_a_normal_run_gives_its_slot_back(
        self, db_session, mcp_run_kit, world, mcp_client, redis_client
    ):
        use(mcp_run_kit, world, AnyModel("An answer."))
        expiry = time.time() + 60
        await redis_client.zadd(slot_key(world.user.id), {"a": expiry, "b": expiry})
        await redis_client.expire(slot_key(world.user.id), 60)
        try:
            refused = await ask_tool(mcp_client, world)

            assert refused.is_error is True
            assert "in progress" in refused.content[0].text
            assert await _runs(db_session, world.user) == []
            assert await slot_count(redis_client, world.user) == 2
        finally:
            await redis_client.delete(slot_key(world.user.id))

        answered = await ask_tool(mcp_client, world)

        assert answered.is_error is not True
        assert await slot_count(redis_client, world.user) == 0

    async def test_a_repository_that_is_not_the_callers_is_not_found(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        from tests.factories import make_user

        stranger = await make_user(db_session, ai_api_key="sk-stranger")
        theirs, _ = await make_ingested_repo(db_session, stranger)
        use(mcp_run_kit, world, AnyModel())

        result = await mcp_client.call_tool(
            "ask_illume", {"repo": str(theirs.id), "question": QUESTION}
        )

        assert result.is_error is True
        assert "No repository matches" in result.content[0].text
        assert await _runs(db_session, world.user, stranger) == []


async def _slot_free(redis_client, user) -> bool:
    return await slot_count(redis_client, user) == 0


async def _runs(db_session, *users) -> list[AgentRun]:
    """The runs owned by ``users``; rows other suites committed to the database are ignored."""
    owners = [user.id for user in users]
    query = select(AgentRun).where(AgentRun.user_id.in_(owners))
    return list((await db_session.execute(query)).scalars().all())


# --- billing ---------------------------------------------------------------------------------


class TestFreeTierCharge:
    async def test_a_generated_answer_costs_exactly_one_message(
        self, db_session, mcp_run_kit, free_world, mcp_client
    ):
        use(mcp_run_kit, free_world, AnyModel())

        first = await ask_tool(mcp_client, free_world)
        second = await ask_tool(mcp_client, free_world)

        assert first.is_error is not True and second.is_error is not True
        assert await used(db_session, free_world.user) == 2

    async def test_a_run_that_finds_no_relevant_code_is_not_charged(
        self, db_session, mcp_run_kit, mcp_user, server_key, mcp_connect, auth_headers
    ):
        mcp_user.ai_api_key = None
        repo, _ = await make_ingested_repo(db_session, mcp_user)
        use(mcp_run_kit, None, AnyModel())

        async with mcp_connect(**auth_headers) as client:
            result = await client.call_tool(
                "ask_illume", {"repo": str(repo.repo_number), "question": QUESTION}
            )

        assert result.is_error is not True
        assert await used(db_session, mcp_user) == 0
        assert (await only_run(db_session, repo)).stop_reason == "no_context"

    async def test_an_own_key_never_touches_the_counter(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        use(mcp_run_kit, None, AnyModel())

        await ask_tool(mcp_client, world)

        assert await used(db_session, world.user) == 0


# --- parity with the streaming route ---------------------------------------------------------


class TestParityWithTheStreamRoute:
    """The same account state is allowed or refused alike by both entrances."""

    @pytest.mark.parametrize(
        ("state", "mode", "preset", "allowed"),
        [
            ("free", "quick", "classic", True),
            ("free_exhausted", "quick", "classic", False),
            ("free", "deep", "deep_agent", False),
            ("free", "auto", "auto", False),
            ("own_key", "quick", "hybrid_rerank", True),
            ("own_key", "deep", "deep_agent", True),
            ("own_key", "auto", "auto", True),
            ("own_key_no_tools", "deep", "deep_agent", False),
            ("no_key", "quick", "classic", False),
            ("slots_full", "quick", "hybrid_rerank", False),
        ],
    )
    async def test_the_same_state_gets_the_same_decision(
        self,
        app,
        client,
        db_session,
        mcp_run_kit,
        mcp_user,
        mcp_connect,
        auth_headers,
        redis_client,
        monkeypatch,
        state,
        mode,
        preset,
        allowed,
    ):
        if state == "no_key":
            monkeypatch.setattr(
                llm_config,
                "settings",
                SimpleNamespace(AI_API_KEY="", AI_MODEL="", AI_BASE_URL=""),
            )
        else:
            monkeypatch.setattr(
                llm_config,
                "settings",
                SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL=""),
            )
        byok = state.startswith("own_key") or state == "slots_full"
        world = await make_world(
            db_session,
            mcp_user,
            byok=byok,
            free_chat_messages_used=(
                FREE_CHAT_MESSAGES if state == "free_exhausted" else FREE_CHAT_MESSAGES - 2
            ),
        )
        if state == "own_key_no_tools":
            mcp_user.ai_supports_tools = False
            await db_session.flush()
        model = (
            ScriptedModel([], repeat=lambda n: turn(finish("A deep answer.")))
            if mode != "quick"
            else AnyModel("An answer.")
        )
        decider = Router("local", 0.9)
        kit = RunKit(embed=fake_embedder(), client_factory=model.factory, decider=decider)
        mcp_run_kit.kit = kit
        install(app, db_session, model, decider=decider)
        await authenticate(client, mcp_user)
        if state == "slots_full":
            expiry = time.time() + 60
            await redis_client.zadd(slot_key(mcp_user.id), {"a": expiry, "b": expiry})
            await redis_client.expire(slot_key(mcp_user.id), 60)

        try:
            async with mcp_connect(**auth_headers) as mcp:
                via_mcp = await ask_tool(mcp, world, mode)
            web, events = await stream(client, world.repo, preset=preset)
        finally:
            await redis_client.delete(slot_key(mcp_user.id))

        web_allowed = web.status_code == 200 and events[-1]["type"] == "done"
        assert (via_mcp.is_error is not True) is web_allowed is allowed


# --- progress, cancellation and limits ----------------------------------------------------------


class TestProgress:
    async def test_a_progress_token_gets_notifications_before_the_result(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        use(mcp_run_kit, world, deep_model(), decider=PlanDecider(1.0))
        seen: list[tuple[float, str | None]] = []

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            seen.append((progress, message))

        result = await mcp_client.call_tool(
            "ask_illume",
            {"repo": str(world.repo.repo_number), "question": QUESTION, "mode": "deep"},
            progress_callback=on_progress,
        )

        assert result.is_error is not True
        assert seen, "the call reported progress"
        messages = [message for _, message in seen]
        assert any("Run started" in (m or "") for m in messages)
        assert any("search_symbols" in (m or "") for m in messages)
        counters = [progress for progress, _ in seen]
        assert counters == sorted(set(counters)), "progress only increases"

    async def test_without_a_token_the_call_still_answers(
        self, db_session, mcp_run_kit, world, mcp_client
    ):
        use(mcp_run_kit, world, AnyModel("An answer."))

        result = await ask_tool(mcp_client, world)

        assert result.structured_content["answer"] == "An answer."


class TestCancellation:
    async def _raw_call(self, mcp_app, auth_headers, world, mode: str) -> RawRequest:
        body = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "ask_illume",
                "arguments": {
                    "repo": str(world.repo.repo_number),
                    "question": QUESTION,
                    "mode": mode,
                },
                "_meta": {"progressToken": "t1"},
            },
        }
        raw = RawRequest(mcp_app.app, SimpleNamespace(cookies={}), "/mcp", body)
        raw._scope["headers"] = [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
            (b"content-length", str(len(raw._body)).encode()),
            (b"authorization", auth_headers["authorization"].encode()),
        ]
        return raw

    @pytest.mark.parametrize("mode", ["quick", "deep"])
    async def test_a_disconnect_stops_the_run_and_frees_the_slot(
        self, db_session, mcp_app, mcp_run_kit, world, auth_headers, redis_client, mode, monkeypatch
    ):
        from app.services.agent import session as run_session

        settled = asyncio.Event()
        finalize = run_session.finalize_run

        async def finalize_and_signal(*args: Any, **kwargs: Any):
            try:
                return await finalize(*args, **kwargs)
            finally:
                if kwargs.get("status") == "cancelled":
                    settled.set()

        monkeypatch.setattr(run_session, "finalize_run", finalize_and_signal)
        hold = Hold()
        if mode == "deep":
            model = ScriptedModel([turn(finish("never"), before=hold)])
        else:
            model = AnyModel()
            original = model.create

            async def held(**kwargs: Any):
                await hold()
                return await original(**kwargs)

            model.create = held  # type: ignore[method-assign]
        use(mcp_run_kit, world, model, decider=PlanDecider(1.0))
        raw = await self._raw_call(mcp_app, auth_headers, world, mode)

        raw.start()
        await asyncio.wait_for(hold.reached.wait(), 15)
        assert await slot_count(redis_client, world.user) == 1
        await raw.hang_up()
        # The transport hands the cancellation to the call after the response is gone.
        await wait_until(lambda: _slot_free(redis_client, world.user))
        # The slot is given back just before the run row is settled; wait for that write.
        await asyncio.wait_for(settled.wait(), 15)

        run = await only_run(db_session, world.repo)
        assert run.status == "cancelled"
        assert await slot_count(redis_client, world.user) == 0
        assert await turns_of(db_session, world.repo) == []

    async def test_a_raw_call_without_a_disconnect_answers(
        self, db_session, mcp_app, mcp_run_kit, world, auth_headers
    ):
        use(mcp_run_kit, world, AnyModel("An answer."))
        raw = await self._raw_call(mcp_app, auth_headers, world, "quick")

        raw.start()
        await wait_until(lambda: raw.text.count("An answer.") > 0, timeout=20)
        await raw.hang_up()

        assert raw.status == 200
        assert "An answer." in raw.text


class TestTimeout:
    async def test_a_run_that_outlives_the_cap_is_stopped_and_reported(
        self, db_session, mcp_run_kit, world, mcp_client, redis_client, monkeypatch
    ):
        monkeypatch.setattr(ask, "SINGLE_SHOT_TIMEOUT_SECONDS", 0.3)
        hold = Hold()
        model = AnyModel()
        original = model.create

        async def held(**kwargs: Any):
            await hold()
            return await original(**kwargs)

        model.create = held  # type: ignore[method-assign]
        use(mcp_run_kit, world, model)

        result = await ask_tool(mcp_client, world)

        assert result.is_error is True
        assert "in time" in result.content[0].text
        run = await only_run(db_session, world.repo)
        assert run.status == "cancelled"
        assert await slot_count(redis_client, world.user) == 0

    def test_an_agent_run_waits_a_little_past_its_own_hard_limit(self):
        from app.services.retrieval.config import PRESETS

        config = PRESETS["deep_agent"]
        assert config.agent is not None

        assert ask.run_timeout(config) == (
            config.agent.hard_cancel_seconds + ask.AGENT_TIMEOUT_MARGIN_SECONDS
        )
        assert ask.run_timeout(PRESETS["classic"]) == ask.SINGLE_SHOT_TIMEOUT_SECONDS


class TestAskLimit:
    async def test_the_hourly_limit_is_an_error_with_a_retry_time(
        self, db_session, mcp_run_kit, world, mcp_client, mcp_redis
    ):
        model = use(mcp_run_kit, world, AnyModel())
        redis = mcp_redis.client()
        key = window_key("ask", world.user.id, 3600, limits._now())
        await redis.set(key, MCP_ASK_PER_HOUR)

        result = await ask_tool(mcp_client, world)

        assert result.is_error is True
        assert "retry in" in result.content[0].text
        assert "ask_illume runs per hour" in result.content[0].text
        assert model.requests == []
        assert await _runs(db_session, world.user) == []

    async def test_each_call_counts_toward_the_hour_and_the_minute(
        self, db_session, mcp_run_kit, world, mcp_client, mcp_redis
    ):
        use(mcp_run_kit, world, AnyModel())

        await ask_tool(mcp_client, world)

        redis = mcp_redis.client()
        now = limits._now()
        assert int(await redis.get(window_key("ask", world.user.id, 3600, now))) == 1
        assert int(await redis.get(window_key("calls", world.user.id, 60, now))) >= 1

    async def test_the_per_minute_limit_applies_too(
        self, db_session, mcp_run_kit, world, mcp_client, mcp_redis
    ):
        use(mcp_run_kit, world, AnyModel())
        redis = mcp_redis.client()
        await redis.set(window_key("calls", world.user.id, 60, limits._now()), MCP_CALLS_PER_MINUTE)

        result = await ask_tool(mcp_client, world)

        assert result.is_error is True
        assert "per minute" in result.content[0].text
