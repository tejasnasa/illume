"""The single agent end to end, against the retrieval fixture and a scripted model.

The model is :class:`~tests.fixtures.agent_run.ScriptedModel`: it replays fixed
Responses outputs and records every request, so each test asserts both what the
agent did (the nodes it ran, the evidence it kept, the events and steps it
produced, why it stopped) and what it sent to the model. The tools are the real
ones, reading real rows in the test database; only the model, the decider and
the clock are faked.

Two copies of the fixture repository are seeded once per module. The tests ask
about copy A.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from openai import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models import AstSymbol
from app.services.agent import window as window_module
from app.services.agent.errors import RunError
from app.services.agent.events import EventLog
from app.services.agent.runner import TIMED_OUT_ANSWER, RunResult, run_agent
from app.services.agent.state import (
    ClaimCheck,
    ClaimVerdict,
    StopReason,
    VerificationReport,
)
from app.services.agent.steps import InMemorySteps
from app.services.agent.tools import REGISTRY, ToolRegistry
from app.services.agent.tools.context import RepoSnapshot, ToolContext
from app.services.agent.tools.output import ToolOutput
from app.services.agent.tools.registry import Tool, ToolInput, ToolResult
from app.services.decisions import Route, RouteDecision
from app.services.retrieval.config import DEEP_AGENT, DEFAULT_CONTEXT_WINDOW
from tests.factories import make_user
from tests.fixtures.agent_run import (
    FakeClock,
    ScriptedModel,
    SufficiencyDecider,
    agent_config,
    call,
    finish,
    message,
    never,
    reasoning,
    say,
    serialized,
    turn,
    with_hard_cancel,
)
from tests.fixtures.agent_tools import (
    SECURITY,
    ToolRepos,
    seed_tool_repos,
    session_factory_for,
)
from tests.fixtures.retrieval import fake_embedder, make_llm, rolled_back_session

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

QUESTION = "Where is `verify_password` defined?"


@dataclass
class Env:
    factory: async_sessionmaker
    repos: ToolRepos
    db: AsyncSession

    @property
    def symbol_key(self) -> str:
        symbol = self.repos.a.symbols[(SECURITY, "verify_password")]
        return f"F:{SECURITY}:{symbol.start_line}-{symbol.end_line}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env(engine):
    """Seeds both repositories once, on a session that is rolled back at the end."""
    with pytest.MonkeyPatch.context() as patch:
        # A key in a developer's environment must not turn on the model-backed stages.
        patch.setattr(settings, "OPENROUTER_API_KEY", "")
        patch.setattr(settings, "COHERE_API_KEY", "")
        async with rolled_back_session(engine) as db:
            repos = await seed_tool_repos(db, await make_user(db))
            yield Env(factory=serialized(session_factory_for(db.bind)), repos=repos, db=db)


@dataclass
class Ran:
    result: RunResult
    events: EventLog
    steps: InMemorySteps


def run_kwargs(env: Env, model: ScriptedModel, **overrides: Any) -> dict[str, Any]:
    """The arguments of a run over repository A with the scripted model."""
    arguments: dict[str, Any] = {
        "repository": RepoSnapshot.from_repository(env.repos.a.repo),
        "session_factory": env.factory,
        "llm": make_llm(),
        "config": agent_config(),
        "embed": fake_embedder(),
        "client_factory": model.factory,
    }
    arguments.update(overrides)
    return arguments


async def run(
    env: Env,
    model: ScriptedModel,
    *,
    question: str = QUESTION,
    history: tuple[Any, ...] = (),
    **overrides: Any,
) -> Ran:
    events, steps = EventLog(), InMemorySteps()
    overrides.setdefault("emit", events)
    overrides.setdefault("steps", steps)
    result = await run_agent(question, history, **run_kwargs(env, model, **overrides))
    return Ran(result=result, events=overrides["emit"], steps=overrides["steps"])


def nodes_run(ran: Ran) -> list[str]:
    return [p["node"] for p in ran.events.named("node") if p["phase"] == "started"]


def outputs_in(model: ScriptedModel, request: int, call_id: str) -> str:
    """The text the model was shown for one call, in one request."""
    for item in model.requests[request]["input"]:
        if isinstance(item, dict) and item.get("call_id") == call_id:
            if item.get("type") == "function_call_output":
                return item["output"]
    raise AssertionError(f"request {request} has no output for {call_id}")


def search(name: str = "verify_password", **extra: Any) -> dict[str, Any]:
    return call("search_symbols", {"name": name, **extra})


# --- the loop ------------------------------------------------------------------------------


class TestHappyPath:
    async def test_two_turns_search_then_finish(self, env):
        key = env.symbol_key
        first = turn(
            reasoning("rs_1"),
            message("Let me look."),
            search(),
            call("get_importers", {"path": SECURITY}),
            input_tokens=1000,
        )
        model = ScriptedModel(
            [first, turn(finish(f"`verify_password` is defined in {SECURITY} [{key}]."))]
        )

        ran = await run(env, model)

        result = ran.result
        assert result.status == "completed"
        assert result.stop_reason is StopReason.FINISHED
        assert result.answer.startswith("`verify_password` is defined")
        assert result.cited == (key,)
        assert result.unresolved == ()
        assert result.iterations == 2
        assert result.tool_calls == 2
        assert key in result.evidence
        assert "search_symbols" in result.evidence[key].found_by
        assert nodes_run(ran) == [
            "route",
            "seed",
            "agent",
            "tools",
            "agent",
            "tools",
            "gate",
            "synthesize",
            "verify",
        ]
        # The agent's own answer is used: no third model call is made.
        assert len(model.requests) == 2
        assert len(model.synthesis_requests) == 0

    async def test_the_request_is_stateless_and_carries_the_tools(self, env):
        model = ScriptedModel([turn(finish("done"))])

        await run(env, model)

        request = model.agent_requests[0]
        assert request["model"] == "test-model"
        assert request["stream"] is True
        assert request["tool_choice"] == "auto"
        assert request["parallel_tool_calls"] is True
        assert request["max_output_tokens"] > 0
        assert request["reasoning"] == {"effort": "low"}
        assert "previous_response_id" not in request
        assert "store" not in request
        names = [tool["name"] for tool in request["tools"]]
        assert "finish" in names and "search_code" in names
        assert all(tool["strict"] is False for tool in request["tools"])
        assert model.client_inits == [{"api_key": "sk-test"}]

    async def test_the_system_prompt_names_the_repository_and_the_rules(self, env):
        model = ScriptedModel([turn(finish("done"))])

        await run(env, model)

        system = model.requests[0]["input"][0]
        assert system["role"] == "system"
        assert env.repos.a.repo.name in system["content"]
        assert "call graph" in system["content"]
        assert "<source>" in system["content"]
        assert "[F:app/main.py:10-24]" in system["content"]

    async def test_the_second_request_replays_the_conversation_unchanged(self, env):
        thought = reasoning("rs_7")
        first_call = search()
        model = ScriptedModel(
            [turn(thought, first_call, input_tokens=500), turn(finish("done"))],
        )

        await run(env, model)

        replayed = model.requests[1]["input"]
        first = model.requests[0]["input"]
        # Everything sent the first time is sent again, in the same order.
        assert replayed[: len(first)] == first
        added = replayed[len(first) :]
        assert added[0]["id"] == "rs_7" and added[0]["type"] == "reasoning"
        assert added[1]["type"] == "function_call"
        assert added[1]["call_id"] == first_call["call_id"]
        assert added[1]["arguments"] == first_call["arguments"]
        assert added[2]["type"] == "function_call_output"
        assert added[2]["call_id"] == first_call["call_id"]

    async def test_history_is_replayed_as_conversation_turns(self, env):
        from app.services.agent.state import ChatTurn

        model = ScriptedModel([turn(finish("done"))])
        history = (
            ChatTurn("user", "What is this repo?"),
            ChatTurn("assistant", "A small web API."),
        )

        await run(env, model, history=history)

        sent = model.requests[0]["input"]
        assert sent[1] == {"role": "user", "content": "What is this repo?"}
        assert sent[2] == {"role": "assistant", "content": "A small web API."}
        assert sent[3] == {"role": "user", "content": QUESTION}

    async def test_interim_text_is_streamed_as_thinking(self, env):
        model = ScriptedModel(
            [turn(message("Checking the auth module."), search()), turn(finish("done"))]
        )

        ran = await run(env, model)

        text = "".join(p["text"] for p in ran.events.named("thinking"))
        assert text == "Checking the auth module."

    async def test_events_open_and_close_the_run(self, env):
        model = ScriptedModel([turn(search()), turn(finish("The answer."))])

        ran = await run(env, model)

        names = ran.events.names()
        assert names[0] == "run_started"
        assert names[-1] == "run_finished"
        assert names.count("answer") == 1
        started = ran.events.named("run_started")[0]
        assert started["limits"]["context_window"] == DEFAULT_CONTEXT_WINDOW
        assert started["limits"]["max_input_tokens"] == 1_500_000
        finished = ran.events.named("run_finished")[0]
        assert finished["status"] == "completed" and finished["stop_reason"] == "finished"
        assert [p["tool"] for p in ran.events.named("tool_call")] == ["search_symbols", "finish"]
        assert ran.events.named("nodes")[0]["paths"] == [SECURITY]

    async def test_a_failing_listener_does_not_fail_the_run(self, env):
        async def broken(event: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("the connection closed")

        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model, emit=broken)

        assert ran.result.status == "completed"

    async def test_the_result_records_how_it_was_produced(self, env):
        config = agent_config()
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model, config=config)

        result = ran.result
        assert result.prompt_version == "agent-3"
        assert result.config_hash == config.config_hash()
        assert result.model == "test-model"
        assert result.limits["max_iterations"] == 12
        assert ran.steps.result is result

    async def test_the_confidence_note_is_kept(self, env):
        model = ScriptedModel([turn(finish("Partly.", note="Could not find the tests."))])

        ran = await run(env, model)

        assert ran.result.confidence_note == "Could not find the tests."

    async def test_a_cited_key_the_run_never_saw_is_reported_unresolved(self, env):
        key = env.symbol_key
        model = ScriptedModel(
            [turn(search()), turn(finish(f"Found [{key}] and also [F:nowhere/else.py:1-2]."))]
        )

        ran = await run(env, model)

        assert ran.result.cited == (key,)
        assert ran.result.unresolved == ("F:nowhere/else.py:1-2",)

    async def test_the_deep_agent_preset_answers_end_to_end(self, env):
        key = env.symbol_key
        model = ScriptedModel(
            [
                turn(search(), call("get_file_info", {"path": SECURITY})),
                turn(finish(f"It lives in {SECURITY} [{key}].")),
            ]
        )
        decider = SufficiencyDecider(0.95)

        ran = await run(env, model, config=DEEP_AGENT, decider=decider)

        assert ran.result.status == "completed"
        assert ran.result.stop_reason is StopReason.FINISHED
        assert ran.result.cited == (key,)
        assert len(decider.calls) == 1
        assert "gate" in nodes_run(ran)


class TestSeed:
    async def test_the_first_retrieval_is_put_in_front_of_the_agent(self, env):
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model)

        seeded = [step for step in ran.steps.of_kind("seed") if step.payload.get("keys")]
        assert len(seeded) == 1
        keys = seeded[0].payload["keys"]
        assert env.symbol_key in keys
        sent = model.requests[0]["input"]
        seed_item = sent[-1]
        assert seed_item["role"] == "user"
        assert f'<source key="{env.symbol_key}"' in seed_item["content"]
        assert 'provenance="repo"' in seed_item["content"]
        for key in keys:
            assert ran.result.evidence[key].found_by[0] == "seed"
        assert ran.events.named("seed")[0]["keys"] == keys

    async def test_the_seed_can_be_turned_off(self, env):
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model, config=agent_config(seed=False))

        assert ran.steps.of_kind("seed") == []
        assert model.requests[0]["input"][-1] == {"role": "user", "content": QUESTION}
        assert ran.result.evidence == {}

    async def test_evidence_keeps_the_first_step_and_every_finder(self, env):
        key = env.symbol_key
        model = ScriptedModel(
            [
                turn(search()),
                turn(call("read_symbol", {"name": "verify_password"})),
                turn(finish("done")),
            ]
        )

        ran = await run(env, model)

        evidence = ran.result.evidence[key]
        assert evidence.found_by[0] == "seed"
        assert "search_symbols" in evidence.found_by and "read_symbol" in evidence.found_by
        seed_step = ran.steps.of_kind("seed")[0].index
        assert evidence.first_step == seed_step
        # The full body from read_symbol replaces the shorter search excerpt.
        assert "bcrypt.checkpw" in evidence.text

    async def test_a_failing_seed_is_not_fatal(self, env, monkeypatch):
        async def broken(*args: Any, **kwargs: Any):
            raise RuntimeError("search is down")

        monkeypatch.setattr("app.services.agent.nodes.seed.retrieve", broken)
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model)

        assert ran.result.status == "completed"
        degraded = ran.events.named("degraded")
        assert [p["stage"] for p in degraded] == ["seed"]
        assert "search is down" in degraded[0]["reason"]

    async def test_the_route_decision_is_reported(self, env):
        decision = RouteDecision(
            route=Route.RELATIONAL,
            accepted=True,
            confidence=0.8,
            probabilities={"relational": 0.8},
            model="fake",
        )
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model, route=decision)

        assert ran.events.named("route") == [
            {
                "route": "relational",
                "accepted": True,
                "confidence": 0.8,
                "probabilities": {"relational": 0.8},
                "model": "fake",
            }
        ]
        assert ran.result.route is decision


# --- the gate ------------------------------------------------------------------------------


class TestGate:
    async def test_a_sufficient_verdict_lets_the_finish_answer_through(self, env):
        decider = SufficiencyDecider(0.9)
        model = ScriptedModel([turn(search()), turn(finish("The answer."))])

        ran = await run(env, model, config=agent_config(gate=True), decider=decider)

        assert ran.result.answer == "The answer."
        assert ran.result.stop_reason is StopReason.FINISHED
        assert len(model.requests) == 2
        assert len(decider.calls) == 1
        assert "Question:" in decider.calls[0][0] and "<source key=" in decider.calls[0][0]
        verdicts = [p["verdict"] for p in ran.events.named("gate")]
        assert verdicts == ["sufficient"]

    async def test_an_insufficient_verdict_sends_the_agent_back_with_feedback(self, env):
        decider = SufficiencyDecider(0.42, 0.9)
        model = ScriptedModel(
            [
                turn(search()),
                turn(finish("A thin answer.")),
                turn(call("get_importers", {"path": SECURITY})),
                turn(finish("A better answer.")),
            ]
        )

        ran = await run(env, model, config=agent_config(gate=True), decider=decider)

        assert ran.result.answer == "A better answer."
        assert ran.result.stop_reason is StopReason.FINISHED
        assert len(model.requests) == 4
        feedback = model.requests[2]["input"][-1]
        assert feedback["role"] == "user"
        assert "insufficient (p = 0.42)" in feedback["content"]
        assert "State what is missing" in feedback["content"]
        assert [p["verdict"] for p in ran.events.named("gate")] == ["insufficient", "sufficient"]
        assert nodes_run(ran).count("gate") == 2

    async def test_the_gate_cannot_trap_the_loop(self, env):
        decider = SufficiencyDecider(0.1)
        model = ScriptedModel(
            [
                turn(search()),
                turn(finish("First.")),
                turn(finish("Second.")),
                turn(finish("Third.")),
                say("Closing answer from the evidence."),
            ]
        )

        ran = await run(env, model, config=agent_config(gate=True), decider=decider)

        assert ran.result.stop_reason is StopReason.GATE_EXHAUSTED
        assert ran.result.answer == "Closing answer from the evidence."
        assert len(decider.calls) == 2
        assert len(model.synthesis_requests) == 1
        assert [p["verdict"] for p in ran.events.named("gate")][-1] == "exhausted"

    async def test_a_placeholder_answer_fails_safe(self, env):
        decider = SufficiencyDecider(0.99, defaulted=True)
        model = ScriptedModel(
            [turn(search()), turn(finish("Thin.")), turn(finish("Thinner.")), turn(finish("Z."))]
            + [say("Closing.")]
        )

        ran = await run(env, model, config=agent_config(gate=True), decider=decider)

        assert [p["verdict"] for p in ran.events.named("gate")][:2] == [
            "insufficient",
            "insufficient",
        ]
        assert ran.result.stop_reason is StopReason.GATE_EXHAUSTED

    async def test_a_gate_that_is_off_never_asks(self, env):
        decider = SufficiencyDecider(0.0)
        model = ScriptedModel([turn(search()), turn(finish("Fine."))])

        ran = await run(env, model, config=agent_config(gate=False), decider=decider)

        assert ran.result.answer == "Fine."
        assert decider.calls == []
        assert ran.events.named("gate") == []

    async def test_decisions_are_written_to_the_step_log(self, env):
        decider = SufficiencyDecider(0.3, 0.8)
        model = ScriptedModel(
            [turn(search()), turn(finish("A.")), turn(search("hash_password")), turn(finish("B."))]
        )

        ran = await run(env, model, config=agent_config(gate=True), decider=decider)

        decisions = ran.steps.of_kind("decision")
        assert [d.payload["point"] for d in decisions] == ["sufficiency", "sufficiency"]
        assert [d.payload["answer"] for d in decisions] == [0.3, 0.8]
        assert decisions[0].payload["model"] == "fake-decider"
        assert len(decisions[0].payload["state_hash"]) == 64
        assert [s.payload["verdict"] for s in ran.steps.of_kind("gate")] == [
            "insufficient",
            "sufficient",
        ]

    async def test_a_text_reply_goes_through_the_gate_then_is_written_up(self, env):
        decider = SufficiencyDecider(0.9)
        model = ScriptedModel([turn(search()), say("It is in security.py."), say("Written up.")])

        ran = await run(env, model, config=agent_config(gate=True), decider=decider)

        assert ran.result.stop_reason is StopReason.TEXT_REPLY
        assert ran.result.answer == "Written up."
        assert len(decider.calls) == 1
        closing = model.synthesis_requests[0]
        assert closing["input"][0]["role"] == "system"
        assert "<source key=" in closing["input"][0]["content"]
        assert "tools" not in closing or not closing.get("tools")
        assert ran.events.named("answer_delta")

    async def test_a_gate_that_cannot_answer_does_not_block(self, env):
        class Broken(SufficiencyDecider):
            async def noul(self, state, instructions):
                raise RuntimeError("the decision service is down")

        model = ScriptedModel([turn(search()), turn(finish("Done."))])

        ran = await run(env, model, config=agent_config(gate=True), decider=Broken())

        assert ran.result.answer == "Done."
        assert [p["stage"] for p in ran.events.named("degraded")] == ["gate"]

    async def test_without_a_decider_the_gate_is_off_and_says_so(self, env, monkeypatch):
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(
            "app.services.agent.runner.get_decider",
            lambda *a, **k: (_ for _ in ()).throw(
                __import__("app.services.decisions", fromlist=["x"]).DeciderUnavailable("none")
            ),
        )
        model = ScriptedModel([turn(search()), turn(finish("Done."))])

        ran = await run(env, model, config=agent_config(gate=True))

        assert ran.result.answer == "Done."
        assert [p["stage"] for p in ran.events.named("degraded")] == ["gate"]


# --- budgets -------------------------------------------------------------------------------


class TestBudgets:
    async def test_iterations(self, env):
        model = ScriptedModel(
            [
                turn(search()),
                turn(search("hash_password")),
                turn(search("get_user")),
                say("Closing."),
            ]
        )

        ran = await run(env, model, config=agent_config(max_iterations=3))

        assert ran.result.stop_reason is StopReason.MAX_ITERATIONS
        assert ran.result.iterations == 3
        assert ran.result.answer == "Closing."
        assert len(model.agent_requests) == 3 and len(model.synthesis_requests) == 1
        limits = [p for p in ran.events.named("degraded") if p.get("stage") == "budget"]
        assert [(p["limit"], p["used"], p["allowed"]) for p in limits] == [("max_iterations", 3, 3)]

    async def test_tool_calls(self, env):
        names = ["verify_password", "hash_password", "get_user", "RateLimiter"]
        model = ScriptedModel(
            [
                turn(*(search(name) for name in names[:3])),
                turn(*(search(name) for name in names[1:])),
                say("Closing."),
            ]
        )

        ran = await run(env, model, config=agent_config(max_tool_calls=4))

        assert ran.result.stop_reason is StopReason.MAX_TOOL_CALLS
        assert ran.result.tool_calls == 4
        statuses = [s.payload["status"] for s in ran.steps.of_kind("tool_call")]
        assert statuses == ["ok", "ok", "ok", "ok", "skipped", "skipped"]
        # The calls that were not run still get an output, so the conversation stays valid.
        skipped = ran.steps.of_kind("tool_call")[-1].payload["call_id"]
        assert skipped is not None
        assert len(model.agent_requests) == 2 and len(model.synthesis_requests) == 1
        limits = [p for p in ran.events.named("degraded") if p.get("stage") == "budget"]
        assert limits[0]["limit"] == "max_tool_calls"

    async def test_wall_clock(self, env):
        clock = FakeClock()

        async def slow() -> None:
            clock.advance(11)

        model = ScriptedModel([turn(search(), before=slow), say("Closing.")])

        ran = await run(env, model, config=agent_config(max_seconds=10), clock=clock)

        assert ran.result.stop_reason is StopReason.MAX_SECONDS
        assert ran.result.answer == "Closing."
        assert len(model.agent_requests) == 1
        assert ran.result.limits_reached == ("max_seconds",)

    async def test_input_tokens_come_from_the_reported_usage(self, env):
        model = ScriptedModel(
            [
                turn(search(), input_tokens=6_000),
                turn(search("hash_password"), input_tokens=6_000),
                say("Closing."),
            ]
        )

        ran = await run(env, model, config=agent_config(max_input_tokens=10_000))

        assert ran.result.stop_reason is StopReason.MAX_INPUT_TOKENS
        assert len(model.agent_requests) == 2
        # Two agent turns and the closing call, as reported.
        assert ran.result.input_tokens == 6_000 + 6_000 + 100
        assert ran.result.limits["max_input_tokens"] == 10_000
        limits = [p for p in ran.events.named("degraded") if p.get("stage") == "budget"]
        assert limits[0]["limit"] == "max_input_tokens" and limits[0]["allowed"] == 10_000

    async def test_the_default_context_window_is_250000(self, env):
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model)

        assert ran.result.limits["context_window"] == 250_000
        assert ran.result.limits["max_input_tokens"] == 1_500_000

    async def test_the_users_context_window_replaces_the_default(self, env):
        model = ScriptedModel([turn(finish("done"))])

        ran = await run(env, model, context_window=128_000)

        assert ran.result.limits["context_window"] == 128_000

    async def test_a_run_under_its_limit_is_not_cut_short(self, env):
        model = ScriptedModel(
            [turn(search(), input_tokens=100_000), turn(finish("Done."), input_tokens=100_000)]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.FINISHED
        assert ran.result.input_tokens == 200_000
        assert ran.result.limits_reached == ()

    @pytest.mark.parametrize("window", [0, 31_999, 1_000_001])
    async def test_an_impossible_context_window_is_refused(self, env, window):
        model = ScriptedModel([])

        with pytest.raises(ValidationError):
            await run(env, model, context_window=window)

        assert model.requests == []

    async def test_the_hard_limit_cancels_a_stuck_call(self, env):
        model = ScriptedModel([turn(search(), before=never)])
        config = with_hard_cancel(agent_config(), 1)

        ran = await run(env, model, config=config)

        assert ran.result.stop_reason is StopReason.HARD_TIMEOUT
        assert ran.result.status == "completed"
        assert ran.result.answer.startswith(TIMED_OUT_ANSWER)
        assert len(model.requests) == 1
        hard = [p for p in ran.events.named("degraded") if p.get("limit") == "hard_cancel_seconds"]
        assert len(hard) == 1

    async def test_a_limit_is_announced_once(self, env):
        model = ScriptedModel([turn(search()), say("Closing.")])

        ran = await run(env, model, config=agent_config(max_iterations=1))

        budget = [p for p in ran.events.named("degraded") if p.get("stage") == "budget"]
        assert len(budget) == 1

    async def test_the_graph_step_limit_still_produces_an_answer(self, env, monkeypatch):
        monkeypatch.setattr("app.services.agent.runner.recursion_limit", lambda iterations: 6)
        model = ScriptedModel(
            [
                turn(search()),
                turn(search("hash_password")),
                say("Closing."),
            ]
        )

        ran = await run(env, model)

        assert ran.result.status == "completed"
        assert ran.result.stop_reason is StopReason.RECURSION
        assert ran.result.answer == "Closing."
        assert len(model.synthesis_requests) == 1


# --- cancellation and provider failures ----------------------------------------------------


class TestCancellation:
    async def test_cancelling_marks_the_run_and_stops_model_calls(self, env):
        entered = asyncio.Event()

        async def hold() -> None:
            entered.set()
            await never()

        model = ScriptedModel([turn(search()), turn(search("hash_password"), before=hold)])
        events, steps = EventLog(), InMemorySteps()
        task = asyncio.create_task(
            run_agent(QUESTION, (), **run_kwargs(env, model, emit=events, steps=steps))
        )
        await entered.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert steps.result is not None
        assert steps.result.status == "cancelled"
        assert steps.result.stop_reason is StopReason.CANCELLED
        assert steps.result.answer == ""
        assert events.named("run_finished")[-1]["status"] == "cancelled"
        # The first turn's work is kept, and nothing was asked of the model after the cancel.
        assert len(model.requests) == 2
        assert [s.kind for s in steps.steps].count("model_call") == 1
        assert events.named("answer") == []


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.example.com/v1"))


PROVIDER_FAILURES = [
    pytest.param(
        RateLimitError("slow down", response=_response(429), body=None),
        "provider",
        "Provider returned an error:",
        id="429",
    ),
    pytest.param(
        InternalServerError("upstream broke", response=_response(500), body=None),
        "provider",
        "Provider returned an error:",
        id="500",
    ),
    pytest.param(
        APITimeoutError(request=httpx.Request("POST", "https://api.example.com/v1")),
        "unreachable",
        "Could not reach the LLM provider:",
        id="timeout",
    ),
    pytest.param(
        AuthenticationError("bad key", response=_response(401), body=None),
        "auth",
        "Provider rejected the API key:",
        id="401",
    ),
]


class TestProviderFailures:
    @pytest.mark.parametrize(("failure", "kind", "message"), PROVIDER_FAILURES)
    async def test_a_failure_on_the_third_call_fails_the_run_and_keeps_its_steps(
        self, env, failure, kind, message
    ):
        model = ScriptedModel([turn(search()), turn(search("hash_password")), turn(error=failure)])

        ran = await run(env, model)

        result = ran.result
        assert result.status == "failed"
        assert result.stop_reason is StopReason.ERROR
        assert result.answer == ""
        assert isinstance(result.error, RunError)
        assert result.error.kind == kind
        assert result.error.message.startswith(message)
        assert result.error.status == 502

        errors = ran.events.named("error")
        assert errors == [{"kind": kind, "message": result.error.message, "status": 502}]
        assert ran.events.names()[-1] == "run_finished"
        assert ran.events.named("run_finished")[0]["status"] == "failed"
        assert ran.events.named("answer") == []

        # The two turns before the failure stay in the log, and so does the failure.
        assert len(ran.steps.of_kind("model_call")) == 2
        assert [s.payload["tool"] for s in ran.steps.of_kind("tool_call")] == [
            "search_symbols",
            "search_symbols",
        ]
        assert ran.steps.of_kind("error")[0].payload["exception"] == type(failure).__name__
        assert ran.steps.result is result

    async def test_a_failure_while_writing_the_closing_answer_fails_the_run(self, env):
        failure = InternalServerError("upstream broke", response=_response(500), body=None)
        model = ScriptedModel([turn(search()), turn(error=failure)])

        ran = await run(env, model, config=agent_config(max_iterations=1))

        assert ran.result.status == "failed"
        assert ran.result.error is not None and ran.result.error.kind == "provider"

    async def test_a_stream_that_reports_failure_is_a_provider_error(self, env):
        class Failing(ScriptedModel):
            async def _events(self, reply):
                from types import SimpleNamespace

                yield SimpleNamespace(
                    type="response.failed",
                    response=SimpleNamespace(error=SimpleNamespace(message="overloaded")),
                )

        ran = await run(env, Failing([turn(search())]))

        assert ran.result.status == "failed"
        assert ran.result.error is not None
        assert ran.result.error.message == "Provider returned an error: overloaded"


# --- the model misbehaving -----------------------------------------------------------------

BAD_CALLS = [
    pytest.param(
        lambda: call("search_symbols", '{"name": "verify_pass'),
        "not valid JSON",
        id="malformed-json",
    ),
    pytest.param(
        lambda: call("get_callers", {"name": "verify_password"}),
        "There is no tool named `get_callers`",
        id="unknown-tool",
    ),
    pytest.param(
        lambda: call("search_symbols", {}),
        "argument `name` is required",
        id="missing-argument",
    ),
    pytest.param(
        lambda: call("search_symbols", {"name": "verify_password", "bogus": 1}),
        "`bogus` is not an argument of this tool",
        id="extra-argument",
    ),
    pytest.param(
        lambda: call("search_symbols", ["verify_password"]),
        "must be a JSON object",
        id="not-an-object",
    ),
]


class TestModelMisbehaviour:
    @pytest.mark.parametrize(("bad", "expected"), BAD_CALLS)
    async def test_a_bad_call_becomes_an_error_result_and_the_loop_continues(
        self, env, bad, expected
    ):
        broken = bad()
        model = ScriptedModel([turn(broken), turn(finish("Recovered."))])

        ran = await run(env, model)

        assert expected in outputs_in(model, 1, broken["call_id"])
        assert ran.result.stop_reason is StopReason.FINISHED
        assert ran.result.answer == "Recovered."
        step = ran.steps.of_kind("tool_call")[0]
        assert step.payload["status"] != "ok"

    @pytest.mark.parametrize(("bad", "expected"), BAD_CALLS)
    async def test_three_in_a_row_end_the_run(self, env, bad, expected):
        model = ScriptedModel(
            [turn(bad()), turn(bad()), turn(bad()), say("Closing with what exists.")]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.TOOL_ERRORS
        assert ran.result.status == "completed"
        assert ran.result.answer == "Closing with what exists."
        assert len(model.agent_requests) == 3 and len(model.synthesis_requests) == 1

    async def test_a_success_resets_the_count(self, env):
        model = ScriptedModel(
            [
                turn(call("search_symbols", {})),
                turn(call("search_symbols", {})),
                turn(search()),
                turn(call("search_symbols", {})),
                turn(call("search_symbols", {})),
                turn(finish("Never hit three in a row.")),
            ]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.FINISHED

    async def test_failures_in_one_turn_are_one_strike(self, env):
        model = ScriptedModel(
            [
                turn(*(call("search_symbols", {}) for _ in range(3))),
                turn(*(call("search_symbols", {}) for _ in range(3))),
                turn(finish("Two strikes, still going.")),
            ]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.FINISHED

    async def test_one_success_in_a_turn_clears_the_strikes(self, env):
        model = ScriptedModel(
            [
                turn(call("search_symbols", {})),
                turn(call("search_symbols", {})),
                turn(call("search_symbols", {}), search()),
                turn(call("search_symbols", {})),
                turn(call("search_symbols", {})),
                turn(finish("Never three failed turns in a row.")),
            ]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.FINISHED

    async def test_a_tool_outside_the_allowlist_is_unknown(self, env):
        model = ScriptedModel([turn(call("read_file", {"path": SECURITY})), turn(finish("ok"))])
        config = agent_config(tools=("search_symbols",))

        ran = await run(env, model, config=config)

        assert [t["name"] for t in model.agent_requests[0]["tools"]] == ["search_symbols", "finish"]
        text = outputs_in(model, 1, model.requests[1]["input"][-2]["call_id"])
        assert "There is no tool named `read_file`" in text
        assert ran.steps.of_kind("tool_call")[0].payload["status"] == "unknown_tool"

    async def test_text_with_no_tool_call_and_nothing_gathered_is_asked_again(self, env):
        model = ScriptedModel([say("I think it is in security.py."), turn(finish("Fine."))])

        ran = await run(env, model, config=agent_config(seed=False))

        nudge = model.requests[1]["input"][-1]
        assert nudge["role"] == "user" and "without calling a tool" in nudge["content"]
        assert ran.result.stop_reason is StopReason.FINISHED
        assert nodes_run(ran)[:5] == ["route", "seed", "agent", "agent", "tools"]

    async def test_three_text_replies_in_a_row_end_the_run(self, env):
        model = ScriptedModel([say("a"), say("b"), say("c"), say("Closing.")])

        ran = await run(env, model, config=agent_config(seed=False))

        assert ran.result.stop_reason is StopReason.TOOL_ERRORS
        assert ran.result.answer == "Closing."

    async def test_an_empty_reply_is_asked_again(self, env):
        model = ScriptedModel([turn(reasoning()), turn(finish("Fine."))])

        ran = await run(env, model)

        assert "Your reply was empty" in model.requests[1]["input"][-1]["content"]
        assert ran.result.stop_reason is StopReason.FINISHED

    async def test_finish_with_no_answer_is_refused(self, env):
        model = ScriptedModel([turn(call("finish", {})), turn(finish("Now with an answer."))])

        ran = await run(env, model)

        assert ran.result.answer == "Now with an answer."


def _registry_with(*tools: Tool[Any, Any]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(REGISTRY.get("finish"))
    for tool in tools:
        registry.register(tool)
    return registry


class _NoInput(ToolInput):
    pass


class _TextOutput(ToolOutput):
    text: str = "ok"

    def render(self) -> str:
        return self.text


class TestToolsThatFail:
    async def test_a_raising_tool_is_caught_and_its_class_is_logged(self, env):
        async def boom(ctx: ToolContext, args: _NoInput) -> _TextOutput:
            raise ValueError("kaboom: private detail")

        registry = _registry_with(
            Tool(
                name="boom",
                description="Always fails.",
                input_model=_NoInput,
                output_model=_TextOutput,
                handler=boom,
                cost="free",
                timeout_s=5,
            )
        )
        broken = call("boom", {})
        model = ScriptedModel([turn(broken), turn(finish("Carried on."))])

        ran = await run(env, model, registry=registry)

        shown = outputs_in(model, 1, broken["call_id"])
        assert "internal error (ValueError)" in shown
        assert "private detail" not in shown
        payload = ran.steps.of_kind("tool_call")[0].payload
        assert payload["status"] == "error"
        assert payload["error_type"] == "ValueError"
        assert ran.events.named("tool_result")[0]["error_type"] == "ValueError"
        assert ran.result.answer == "Carried on."

    async def test_a_slow_tool_times_out_with_a_typed_result(self, env):
        async def slow(ctx: ToolContext, args: _NoInput) -> _TextOutput:
            await never()
            return _TextOutput()

        registry = _registry_with(
            Tool(
                name="slow",
                description="Never returns.",
                input_model=_NoInput,
                output_model=_TextOutput,
                handler=slow,
                cost="free",
                timeout_s=0.05,
            )
        )
        stuck = call("slow", {})
        model = ScriptedModel([turn(stuck), turn(finish("Gave up on it."))])

        ran = await run(env, model, registry=registry)

        assert "did not finish within" in outputs_in(model, 1, stuck["call_id"])
        assert ran.steps.of_kind("tool_call")[0].payload["status"] == "timeout"

    async def test_calls_in_one_turn_run_at_the_same_time(self, env):
        started = {"a": asyncio.Event(), "b": asyncio.Event()}

        def waiting(me: str, other: str):
            async def handler(ctx: ToolContext, args: _NoInput) -> _TextOutput:
                started[me].set()
                # Only completes if the other call has started too.
                await asyncio.wait_for(started[other].wait(), timeout=2)
                return _TextOutput(text=f"{me} saw {other}")

            return handler

        tools = [
            Tool(
                name=f"wait_{me}",
                description="Waits for its partner.",
                input_model=_NoInput,
                output_model=_TextOutput,
                handler=waiting(me, other),
                cost="free",
                timeout_s=5,
            )
            for me, other in (("a", "b"), ("b", "a"))
        ]
        first, second = call("wait_a", {}), call("wait_b", {})
        model = ScriptedModel([turn(first, second), turn(finish("Both ran."))])

        ran = await run(env, model, registry=_registry_with(*tools))

        assert outputs_in(model, 1, first["call_id"]) == "a saw b"
        assert outputs_in(model, 1, second["call_id"]) == "b saw a"
        assert ran.result.answer == "Both ran."

    async def test_a_screen_can_replace_a_result_before_the_model_sees_it(self, env):
        async def screen(result: ToolResult) -> ToolResult:
            if result.tool == "search_symbols":
                return result.model_copy(update={"text": "[withheld]"})
            return result

        searched = search()
        model = ScriptedModel([turn(searched), turn(finish("Done."))])

        ran = await run(env, model, screen=screen)

        assert outputs_in(model, 1, searched["call_id"]) == "[withheld]"
        assert ran.result.status == "completed"


# --- a verifier hook -----------------------------------------------------------------------


class TestVerifierHook:
    async def test_failed_claims_send_the_agent_back_once(self, env):
        reports = []

        async def verifier(state: Any) -> VerificationReport:
            reports.append(state["answer"])
            return VerificationReport(
                claims=(
                    ClaimCheck(
                        index=1,
                        claim="It uses argon2.",
                        verdict=ClaimVerdict.UNSUPPORTED,
                    ),
                )
            )

        model = ScriptedModel(
            [turn(finish("It uses argon2.")), turn(finish("It uses bcrypt [F:x:1-2]."))]
        )

        ran = await run(env, model, verifier=verifier)

        assert reports == ["It uses argon2.", "It uses bcrypt [F:x:1-2]."]
        repair = model.requests[1]["input"][-1]
        assert "does not support" in repair["content"] and "It uses argon2." in repair["content"]
        assert ran.result.answer == ("It uses bcrypt [F:x:1-2]. [[verify:unsupported]]")
        assert nodes_run(ran).count("verify") == 2

    async def test_without_a_verifier_the_answer_passes_through(self, env):
        model = ScriptedModel([turn(finish("Done."))])

        ran = await run(env, model)

        assert nodes_run(ran)[-1] == "verify"
        assert ran.result.answer == "Done."


# --- the repository changing under a run ---------------------------------------------------


class TestSyncDuringARun:
    async def test_a_replaced_row_is_reported_and_the_run_still_answers(self, env):
        db_session = env.db
        repos = env.repos
        old = repos.a.symbols[(SECURITY, "verify_password")]
        old_id, old_key = old.id, env.symbol_key

        async def sync_lands() -> None:
            """What a sync does: the symbol's row is replaced by a new one."""
            await db_session.execute(delete(AstSymbol).where(AstSymbol.id == old_id))
            db_session.add(
                AstSymbol(
                    file_id=repos.a.files[SECURITY].id,
                    name="verify_password",
                    kind="function",
                    start_line=old.start_line,
                    end_line=old.end_line,
                    source_code="def verify_password(plain, hashed):\n    return True\n",
                )
            )
            await db_session.flush()

        stale = call("read_symbol", {"symbol_id": str(old_id)})
        by_name = call("read_symbol", {"name": "verify_password"})
        by_path = call("list_symbols", {"path": SECURITY})
        model = ScriptedModel(
            [
                turn(search()),
                turn(stale, by_name, by_path, before=sync_lands),
                turn(finish(f"Defined in {SECURITY} [{old_key}].")),
            ]
        )

        try:
            ran = await run(env, model)
        finally:
            # The module's repository is shared, so put the original row back.
            await db_session.execute(
                delete(AstSymbol).where(
                    AstSymbol.file_id == repos.a.files[SECURITY].id,
                    AstSymbol.name == "verify_password",
                )
            )
            db_session.add(
                AstSymbol(
                    id=old_id,
                    file_id=repos.a.files[SECURITY].id,
                    name="verify_password",
                    kind="function",
                    start_line=old.start_line,
                    end_line=old.end_line,
                    source_code=old.source_code,
                )
            )
            await db_session.flush()

        assert "no longer in the index" in outputs_in(model, 2, stale["call_id"])
        assert "return True" in outputs_in(model, 2, by_name["call_id"])
        assert "verify_password" in outputs_in(model, 2, by_path["call_id"])
        assert ran.result.status == "completed"
        assert ran.result.stop_reason is StopReason.FINISHED
        # Keys are built from paths and lines, so the key found before the sync still resolves.
        assert ran.result.cited == (old_key,)
        assert ran.result.unresolved == ()
        statuses = [s.payload["status"] for s in ran.steps.of_kind("tool_call")]
        assert statuses == ["ok", "ok", "ok", "ok", "ok"]


# --- the context window --------------------------------------------------------------------


def too_long() -> BadRequestError:
    """The refusal a provider sends when the input exceeds the model's window."""
    request = httpx.Request("POST", "https://provider.test/v1/responses")
    return BadRequestError(
        "This model's maximum context length is 128000 tokens.",
        response=httpx.Response(400, request=request),
        body={"code": "context_length_exceeded"},
    )


def compacted_outputs(request: dict[str, Any]) -> list[str]:
    return [
        item["output"]
        for item in request["input"]
        if item.get("type") == "function_call_output" and item["output"].startswith("[Compacted")
    ]


class TestContextWindow:
    @pytest.fixture(autouse=True)
    def compact_short_results(self, monkeypatch):
        # The fixture repository's results are short; in a real run only
        # results worth shortening are stubbed.
        monkeypatch.setattr(window_module, "MIN_COMPACTED_CHARS", 1)

    async def test_older_tool_results_are_compacted_near_the_window(self, env):
        # The second call reports enough tokens that the third would pass 80%
        # of a 32k window, so the first turn's result is stubbed before it.
        model = ScriptedModel(
            [
                turn(search(), input_tokens=1_000),
                turn(search("hash_password"), input_tokens=26_000),
                turn(finish("Done.")),
            ]
        )
        config = agent_config(context_window=32_000, keep_recent_turns=1)

        ran = await run(env, model, config=config)

        assert ran.result.stop_reason is StopReason.FINISHED
        [event] = ran.events.named("compacted")
        assert event["trigger"] == "threshold" and event["replaced"] == 1
        assert event["estimated_tokens_after"] < event["estimated_tokens_before"]
        [stub] = compacted_outputs(model.agent_requests[2])
        assert "search_symbols" in stub and "verify_password" in stub
        assert SECURITY in stub
        # The newest result is still whole, and nothing was stubbed earlier.
        assert compacted_outputs(model.agent_requests[1]) == []
        assert ran.steps.of_kind("compact")
        # Evidence is untouched: the stubbed result can still be cited.
        assert any(SECURITY in key for key in ran.result.evidence)

    async def test_every_call_keeps_its_output_after_compaction(self, env):
        model = ScriptedModel(
            [
                turn(search(), search("hash_password"), input_tokens=1_000),
                turn(search("login"), input_tokens=26_000),
                turn(finish("Done.")),
            ]
        )
        config = agent_config(context_window=32_000, keep_recent_turns=1)

        await run(env, model, config=config)

        sent = model.agent_requests[2]["input"]
        calls = {i["call_id"] for i in sent if i.get("type") == "function_call"}
        outputs = {i["call_id"] for i in sent if i.get("type") == "function_call_output"}
        assert calls == outputs

    async def test_a_conversation_that_cannot_fit_ends_with_an_answer(self, env):
        # One result is already over the window and is the newest turn, which
        # compaction keeps whole, so the run stops and answers.
        model = ScriptedModel(
            [turn(search(), input_tokens=40_000), say("Closing from the evidence.")]
        )
        config = agent_config(context_window=32_000)

        ran = await run(env, model, config=config)

        assert ran.result.stop_reason is StopReason.CONTEXT_WINDOW
        assert ran.result.status == "completed"
        assert ran.result.answer == "Closing from the evidence."
        assert len(model.agent_requests) == 1 and len(model.synthesis_requests) == 1
        [full] = [p for p in ran.events.named("degraded") if p.get("stage") == "context"]
        assert full["limit"] == "context_window" and full["allowed"] == 32_000

    async def test_a_provider_refusal_compacts_and_retries_once(self, env):
        model = ScriptedModel(
            [
                turn(search()),
                turn(search("hash_password")),
                turn(error=too_long()),
                turn(finish("Done after compacting.")),
            ]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.FINISHED
        assert ran.result.answer == "Done after compacting."
        [event] = ran.events.named("compacted")
        assert event["trigger"] == "provider_refused"
        assert compacted_outputs(model.agent_requests[3])

    async def test_a_refusal_with_nothing_to_compact_ends_with_an_answer(self, env):
        model = ScriptedModel([turn(search()), turn(error=too_long()), say("Closing.")])

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.CONTEXT_WINDOW
        assert ran.result.status == "completed"
        assert ran.result.answer == "Closing."

    async def test_a_second_refusal_ends_with_an_answer(self, env):
        model = ScriptedModel(
            [
                turn(search()),
                turn(search("hash_password")),
                turn(error=too_long()),
                turn(error=too_long()),
                say("Closing."),
            ]
        )

        ran = await run(env, model)

        assert ran.result.stop_reason is StopReason.CONTEXT_WINDOW
        assert ran.result.answer == "Closing."

    async def test_other_bad_requests_still_fail_the_run(self, env):
        request = httpx.Request("POST", "https://provider.test/v1/responses")
        refused = BadRequestError(
            "Unsupported parameter: tool_choice",
            response=httpx.Response(400, request=request),
            body=None,
        )
        model = ScriptedModel([turn(error=refused)])

        ran = await run(env, model)

        assert ran.result.status == "failed"
        assert ran.events.named("compacted") == []
