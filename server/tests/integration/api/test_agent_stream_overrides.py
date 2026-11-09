"""Overrides on the stream route: what each caller may change, and what is refused.

The rules themselves are covered in isolation by the unit tests; these check that
the route enforces them before anything runs, and that what it accepts is what
the run uses and records.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import llm_config
from app.services.agent import session as session_module
from app.services.retrieval.config import DEEP_AGENT, MAX_CONTEXT_WINDOW, MIN_CONTEXT_WINDOW
from tests.fixtures.agent_run import PlanDecider, ScriptedModel, finish, turn
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    install,
    make_world,
    only_run,
    runs_of,
    stream,
    stream_url,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")


@pytest.fixture
async def world(client, db_session):
    return await make_world(client, db_session)


@pytest.fixture
async def free_world(client, db_session, monkeypatch):
    stub = SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)
    return await make_world(client, db_session, byok=False)


async def refused(client, world, overrides, preset="deep_agent"):
    return await client.post(
        stream_url(world.repo),
        json={"question": QUESTION, "preset": preset, "overrides": overrides},
    )


class TestRefused:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"agent": {"max_iterations": 21}},
            {"agent": {"max_tool_calls": 101}},
            {"agent": {"max_seconds": 241}},
            {"agent": {"hard_cancel_seconds": 301}},
            {"agent": {"max_input_tokens": 1_500_001}},
            {"agent": {"max_iterations": 10_000}},
            {"agent": {"context_window": MAX_CONTEXT_WINDOW + 1}},
            {"agent": {"context_window": MIN_CONTEXT_WINDOW - 1}},
        ],
    )
    async def test_a_budget_above_the_maximum_is_rejected_never_honoured(
        self, app, client, db_session, world, overrides
    ):
        model = ScriptedModel([turn(finish("never"))])
        install(app, db_session, model, decider=PlanDecider(1.0))

        response = await refused(client, world, overrides)

        assert response.status_code == 422
        assert model.requests == []
        assert await runs_of(db_session, world.repo) == []

    @pytest.mark.parametrize(
        "overrides",
        [
            {"channels": []},
            {"decider": "llm"},
            {"agent": {"tools": ["finish"]}},
            {"rerank": {"top_n": 3}},
            {"nonsense": True},
            {"agent": {"max_iterations": 3, "surprise": 1}},
        ],
    )
    async def test_fields_outside_the_allowlist_are_rejected(
        self, app, client, db_session, world, overrides
    ):
        install(app, db_session, ScriptedModel(), decider=PlanDecider(1.0))

        response = await refused(client, world, overrides)

        assert response.status_code == 422
        assert await runs_of(db_session, world.repo) == []

    async def test_a_caller_with_their_own_key_can_switch_channels_on(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel(), decider=PlanDecider(1.0))

        response, _ = await stream(
            client,
            world.repo,
            preset="hybrid",
            overrides={"channels": ["dense", "grep"]},
        )

        assert response.status_code == 200
        run = await only_run(db_session, world.repo)
        assert sorted(channel["kind"] for channel in run.config["channels"]) == ["dense", "grep"]

    async def test_settings_the_preset_lacks_are_rejected(self, app, client, db_session, world):
        install(app, db_session, AnyModel())

        response = await refused(client, world, {"agent": {"max_iterations": 2}}, preset="hybrid")

        assert response.status_code == 422
        assert "no agent settings" in response.json()["detail"]

    async def test_a_refusal_names_the_ceiling(self, app, client, db_session, world):
        install(app, db_session, AnyModel())

        response = await refused(client, world, {"agent": {"max_iterations": 21}})

        assert "cannot exceed 20" in response.json()["detail"]

    async def test_overrides_are_checked_after_ownership(self, app, client, db_session, world):
        import uuid

        install(app, db_session, AnyModel())

        response = await client.post(
            f"/api/v1/repository/{uuid.uuid4()}/chat/stream",
            json={"question": QUESTION, "preset": "deep_agent", "overrides": {"agent": {}}},
        )

        assert response.status_code == 404


class TestHonoured:
    async def test_a_tighter_budget_is_used_and_recorded(self, app, client, db_session, world):
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("done"))]),
            decider=PlanDecider(1.0),
        )

        _, events = await stream(
            client,
            world.repo,
            preset="deep_agent",
            overrides={"agent": {"max_iterations": 3}},
        )

        run = await only_run(db_session, world.repo)
        assert events[-1]["type"] == "done"
        assert run.config["agent"]["max_iterations"] == 3
        assert run.config_hash != DEEP_AGENT.config_hash()
        assert events[0]["data"]["config_hash"] == run.config_hash
        assert run.preset == "deep_agent"

    async def test_a_tight_iteration_limit_ends_the_run_at_that_limit(
        self, app, client, db_session, world
    ):
        from tests.fixtures.agent_run import call

        model = ScriptedModel(
            repeat=lambda n: turn(call("search_symbols", {"name": f"create_user{n}"}))
        )
        install(app, db_session, model, decider=PlanDecider(1.0))

        _, events = await stream(
            client,
            world.repo,
            preset="deep_agent",
            overrides={"agent": {"max_iterations": 2}},
        )

        assert events[-1]["data"]["stop_reason"] == "max_iterations"
        assert len(model.agent_requests) == 2

    async def test_the_users_context_window_is_passed_to_the_run(
        self, app, client, db_session, world, monkeypatch
    ):
        world.user.ai_context_window = 64_000
        await db_session.flush()
        seen: list[dict] = []
        real = session_module.run_agent

        async def spy(*args, **kwargs):
            seen.append(kwargs)
            return await real(*args, **kwargs)

        monkeypatch.setattr(session_module, "run_agent", spy)
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("done"))]),
            decider=PlanDecider(1.0),
        )

        await stream(client, world.repo, preset="deep_agent")

        assert seen[0]["context_window"] == 64_000

    async def test_a_request_window_wins_over_the_users_setting(
        self, app, client, db_session, world, monkeypatch
    ):
        world.user.ai_context_window = 64_000
        await db_session.flush()
        seen: list[dict] = []
        real = session_module.run_agent

        async def spy(*args, **kwargs):
            seen.append(kwargs)
            return await real(*args, **kwargs)

        monkeypatch.setattr(session_module, "run_agent", spy)
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("done"))]),
            decider=PlanDecider(1.0),
        )

        await stream(
            client,
            world.repo,
            preset="deep_agent",
            overrides={"agent": {"context_window": 48_000}},
        )

        assert seen[0]["context_window"] == 48_000

    async def test_without_a_user_setting_the_presets_window_is_kept(
        self, app, client, db_session, world, monkeypatch
    ):
        seen: list[dict] = []
        real = session_module.run_agent

        async def spy(*args, **kwargs):
            seen.append(kwargs)
            return await real(*args, **kwargs)

        monkeypatch.setattr(session_module, "run_agent", spy)
        install(
            app,
            db_session,
            ScriptedModel([turn(finish("done"))]),
            decider=PlanDecider(1.0),
        )

        await stream(client, world.repo, preset="deep_agent")

        assert seen[0]["context_window"] is None

    async def test_history_overrides_apply_to_a_single_shot_run(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel())

        _, events = await stream(
            client,
            world.repo,
            preset="hybrid",
            overrides={"query": {"history_messages": 0}, "diversify": {"total": 3}},
        )

        run = await only_run(db_session, world.repo)
        assert events[-1]["type"] == "done"
        assert run.config["query"]["history_messages"] == 0
        assert run.config["diversify"]["total"] == 3
