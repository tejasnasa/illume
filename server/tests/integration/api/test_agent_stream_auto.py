"""The ``auto`` preset on the stream route: one routing decision picks the preset.

The decision is a scripted decider. What is checked is the contract: each route
resolves to its preset, every reason to distrust the route lands on ``structural``,
the decision is streamed and recorded, and the request is validated like any other.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings
from app.services import llm_config
from app.services.agent import auto as auto_module
from app.services.agent.auto import ROUTE_PRESETS, resolve_auto
from app.services.decisions import ChoiceResult, Route
from app.services.rag import ChatMessage
from tests.fixtures.agent_run import ScriptedModel, finish, turn
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    install,
    make_world,
    of_type,
    only_run,
    runs_of,
    step_rows,
    stream,
    stream_url,
    types_of,
)

pytestmark = pytest.mark.integration


class Router:
    """A decider that answers a route question with a fixed label and probability."""

    kind = "fake"
    model_id = "fake-router"

    def __init__(
        self,
        label: str = "relational",
        probability: float = 0.9,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.label = label
        self.probability = probability
        self.error = error
        self.delay = delay
        self.calls: list[tuple[Any, str, Any]] = []

    async def choice(self, state: Any, instructions: str, options: Any) -> ChoiceResult:
        self.calls.append((state, instructions, options))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        rest = (1 - self.probability) / (len(options) - 1)
        return ChoiceResult(
            choice=self.label,
            probabilities={
                name: self.probability if name == self.label else rest for name in options
            },
            confidence=0.5,
            latency_ms=3.0,
            model="fake-router-1",
            provider="fake",
        )

    async def noul(self, state: Any, instructions: str):
        raise AssertionError("routing asks one choice")

    async def score(self, state: Any, instructions: str, levels: Any):
        raise AssertionError("routing asks one choice")

    async def batch(self, state: Any, questions: Any):
        raise AssertionError("routing asks one choice")


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")


@pytest.fixture
async def world(client, db_session):
    return await make_world(client, db_session)


@pytest.fixture
async def free_world(client, db_session, monkeypatch):
    stub = SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)
    return await make_world(client, db_session, byok=False)


def model_for(preset: str) -> ScriptedModel:
    """A model that can answer whichever preset the route resolves to."""
    if preset == "deep_agent":
        return ScriptedModel([turn(finish("The whole repository is described."))])
    return AnyModel("An answer.")


class TestTheMapping:
    @pytest.mark.parametrize(
        ("label", "preset"),
        [
            ("local", "hybrid_rerank"),
            ("relational", "structural"),
            ("history", "structural"),
            ("global", "deep_agent"),
            ("out_of_scope", "classic"),
        ],
    )
    async def test_each_label_runs_its_preset(self, app, client, db_session, world, label, preset):
        install(app, db_session, model_for(preset), decider=Router(label, 0.9))

        _, events = await stream(client, world.repo, preset="auto")

        assert types_of(events)[0] == "run_started" and types_of(events)[-1] == "done"
        assert events[0]["data"]["preset"] == preset
        [route] = of_type(events, "route")
        assert route["data"]["route"] == label
        assert route["data"]["resolved_preset"] == preset
        assert route["data"]["fallback_reason"] is None
        assert route["data"]["confidence"] == pytest.approx(0.9)
        assert set(route["data"]["probabilities"]) == {r.value for r in Route}
        run = await only_run(db_session, world.repo)
        assert run.preset == preset and run.status == "done"

    def test_the_table_covers_every_route(self):
        assert set(ROUTE_PRESETS) == set(Route)


class TestFallbacks:
    async def run_auto(self, app, client, db_session, world, decider, **body):
        install(app, db_session, AnyModel("An answer."), decider=decider)
        return await stream(client, world.repo, preset="auto", **body)

    async def assert_structural(self, events, db_session, world, reason):
        assert events[0]["data"]["preset"] == "structural"
        [route] = of_type(events, "route")
        assert route["data"]["resolved_preset"] == "structural"
        assert route["data"]["fallback_reason"] == reason
        assert types_of(events)[-1] == "done"
        run = await only_run(db_session, world.repo)
        assert run.preset == "structural" and run.status == "done"

    async def test_low_confidence_falls_back(self, app, client, db_session, world):
        _, events = await self.run_auto(app, client, db_session, world, Router("global", 0.55))

        await self.assert_structural(events, db_session, world, "low_confidence")
        assert of_type(events, "route")[0]["data"]["route"] == "global"

    async def test_the_threshold_itself_is_trusted(self, app, client, db_session, world):
        _, events = await self.run_auto(app, client, db_session, world, Router("local", 0.6))

        assert of_type(events, "route")[0]["data"]["resolved_preset"] == "hybrid_rerank"

    async def test_a_failing_decision_falls_back(self, app, client, db_session, world):
        decider = Router(error=RuntimeError("the decision API is down"))

        _, events = await self.run_auto(app, client, db_session, world, decider)

        await self.assert_structural(events, db_session, world, "error")

    async def test_a_slow_decision_falls_back(self, app, client, db_session, world, monkeypatch):
        monkeypatch.setattr(auto_module, "ROUTE_TIMEOUT_SECONDS", 0.05)

        _, events = await self.run_auto(
            app, client, db_session, world, Router("local", 0.9, delay=5)
        )

        await self.assert_structural(events, db_session, world, "timeout")

    async def test_no_decision_key_falls_back(self, app, client, db_session, world):
        install(app, db_session, AnyModel("An answer."))

        _, events = await stream(client, world.repo, preset="auto")

        await self.assert_structural(events, db_session, world, "unavailable")
        assert of_type(events, "route")[0]["data"]["route"] is None

    async def test_a_model_without_tools_cannot_take_the_agent_route(
        self, app, client, db_session, world
    ):
        world.user.ai_supports_tools = False
        await db_session.flush()

        _, events = await self.run_auto(app, client, db_session, world, Router("global", 0.95))

        await self.assert_structural(events, db_session, world, "no_tool_support")
        assert of_type(events, "route")[0]["data"]["route"] == "global"

    async def test_a_model_without_tools_still_gets_the_other_routes(
        self, app, client, db_session, world
    ):
        world.user.ai_supports_tools = False
        await db_session.flush()

        _, events = await self.run_auto(app, client, db_session, world, Router("local", 0.95))

        assert of_type(events, "route")[0]["data"]["resolved_preset"] == "hybrid_rerank"


class TestWhatIsSentAndKept:
    async def test_the_decision_is_recorded_as_a_step_and_an_event(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel("An answer."), decider=Router("relational", 0.82))

        _, events = await stream(client, world.repo, preset="auto")

        run = await only_run(db_session, world.repo)
        rows = await step_rows(db_session, run.id)
        [step] = [r for r in rows if r.kind == "decision"]
        assert step.name == "route"
        assert step.payload["requested_preset"] == "auto"
        assert step.payload["resolved_preset"] == "structural"
        assert step.payload["route"] == "relational"
        assert step.payload["decision"]["point"] == "route"
        assert step.payload["decision"]["model"] == "fake-router-1"
        [event_row] = [r for r in rows if r.kind == "event" and r.name == "route"]
        assert event_row.payload["resolved_preset"] == "structural"
        # The route is announced right after the run starts, before any work.
        assert types_of(events)[:2] == ["run_started", "route"]

    async def test_the_decision_sees_the_question_and_only_the_last_user_turn(
        self, app, client, db_session, world
    ):
        decider = Router("local", 0.9)
        install(app, db_session, AnyModel("An answer."), decider=decider)
        history = [
            {"role": "user", "content": "FIRST-QUESTION"},
            {"role": "assistant", "content": "FIRST-ANSWER"},
            {"role": "user", "content": "SECOND-QUESTION"},
            {"role": "assistant", "content": "SECOND-ANSWER"},
        ]

        await stream(client, world.repo, preset="auto", history=history)

        [(state, _, _)] = decider.calls
        assert QUESTION in state and "SECOND-QUESTION" in state
        assert "FIRST-QUESTION" not in state and "ANSWER" not in state

    async def test_a_plain_preset_asks_no_routing_question(self, app, client, db_session, world):
        decider = Router()
        install(app, db_session, AnyModel("An answer."), decider=decider)

        _, events = await stream(client, world.repo, preset="hybrid")

        assert decider.calls == []
        assert "route" not in types_of(events)


class TestRequestRules:
    async def test_the_free_tier_cannot_use_auto(self, app, client, db_session, free_world):
        decider = Router()
        install(app, db_session, AnyModel("An answer."), decider=decider)

        response = await client.post(
            stream_url(free_world.repo), json={"question": QUESTION, "preset": "auto"}
        )

        assert response.status_code == 402
        assert decider.calls == []
        assert await runs_of(db_session, free_world.repo) == []

    async def test_overrides_apply_to_the_resolved_preset(self, app, client, db_session, world):
        install(app, db_session, model_for("deep_agent"), decider=Router("global", 0.9))

        _, events = await stream(
            client,
            world.repo,
            preset="auto",
            overrides={"agent": {"max_iterations": 5}},
        )

        assert types_of(events)[-1] == "done"
        run = await only_run(db_session, world.repo)
        assert run.preset == "deep_agent"
        assert run.config["agent"]["max_iterations"] == 5

    async def test_overrides_are_validated_against_the_resolved_preset(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel("An answer."), decider=Router("relational", 0.9))

        response = await client.post(
            stream_url(world.repo),
            json={
                "question": QUESTION,
                "preset": "auto",
                "overrides": {"agent": {"max_iterations": 5}},
            },
        )

        assert response.status_code == 422
        assert "no agent settings" in response.json()["detail"]
        assert await runs_of(db_session, world.repo) == []

    async def test_a_channel_override_reaches_the_resolved_single_shot_preset(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel("An answer."), decider=Router("local", 0.9))

        _, events = await stream(
            client, world.repo, preset="auto", overrides={"channels": ["dense", "lexical"]}
        )

        assert types_of(events)[-1] == "done"
        run = await only_run(db_session, world.repo)
        assert {c["kind"] for c in run.config["channels"]} == {"dense", "lexical"}

    async def test_an_unknown_preset_is_still_refused(self, app, client, db_session, world):
        install(app, db_session, AnyModel("An answer."))

        response = await client.post(
            stream_url(world.repo), json={"question": QUESTION, "preset": "automatic"}
        )

        assert response.status_code == 422


class TestResolveAuto:
    async def test_an_unusable_label_is_a_low_confidence_fallback(self):
        class Odd(Router):
            async def choice(self, state, instructions, options):
                result = await super().choice(state, instructions, options)
                return ChoiceResult(**{**result.__dict__, "choice": "mystery", "probabilities": {}})

        resolved = await resolve_auto("q", [ChatMessage(role="user", content="a")], decider=Odd())

        assert resolved.resolved_preset == "structural"
        assert resolved.fallback_reason == "low_confidence"
