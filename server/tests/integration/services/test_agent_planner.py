"""Parallel workers end to end: planning, fan-out, merging and what can go wrong.

The model is :class:`~tests.fixtures.agent_run.RoutedModel`: it answers each
branch from what the request is, so a test does not depend on which worker
reached it first. The tools, the database and the decider seam are the real
ones; only the model is scripted.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from openai import RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.services.agent.events import EventLog
from app.services.agent.runner import RunResult, run_agent
from app.services.agent.state import StopReason
from app.services.agent.steps import InMemorySteps
from app.services.agent.tools.context import RepoSnapshot
from tests.factories import make_user
from tests.fixtures.agent_run import (
    RoutedModel,
    SufficiencyDecider,
    Turn,
    call,
    finish,
    plan_reply,
    planner_config,
    say,
    serialized,
    turn,
    with_hard_cancel,
)
from tests.fixtures.agent_tools import SECURITY, ToolRepos, seed_tool_repos, session_factory_for
from tests.fixtures.retrieval import fake_embedder, make_llm, rolled_back_session

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

USERS = "app/users/service.py"

QUESTION = "Compare how a password is checked with how a user is created."
AUTH_QUESTION = "Where is `verify_password` defined?"
USER_QUESTION = "Where is `create_user` defined?"


@dataclass
class Env:
    factory: async_sessionmaker
    repos: ToolRepos
    db: AsyncSession

    @property
    def auth_key(self) -> str:
        symbol = self.repos.a.symbols[(SECURITY, "verify_password")]
        return f"F:{SECURITY}:{symbol.start_line}-{symbol.end_line}"

    @property
    def user_key(self) -> str:
        symbol = self.repos.a.symbols[(USERS, "create_user")]
        return f"F:{USERS}:{symbol.start_line}-{symbol.end_line}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env(engine):
    """Seeds both repositories once, on a session that is rolled back at the end."""
    with pytest.MonkeyPatch.context() as patch:
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


def run_kwargs(env: Env, model: Any, **overrides: Any) -> dict[str, Any]:
    """The arguments of a parallel run over repository A with the scripted model."""
    arguments: dict[str, Any] = {
        "repository": RepoSnapshot.from_repository(env.repos.a.repo),
        "session_factory": env.factory,
        "llm": make_llm(),
        "config": planner_config(),
        "embed": fake_embedder(),
        "client_factory": model.factory,
    }
    arguments.update(overrides)
    return arguments


async def run(
    env: Env,
    model: Any,
    *,
    question: str = QUESTION,
    **overrides: Any,
) -> Ran:
    events, steps = EventLog(), InMemorySteps()
    overrides.setdefault("emit", events)
    overrides.setdefault("steps", steps)
    result = await run_agent(question, (), **run_kwargs(env, model, **overrides))
    return Ran(result=result, events=overrides["emit"], steps=overrides["steps"])


def worker_nodes(ran: Ran) -> list[dict[str, Any]]:
    return [
        payload
        for payload in ran.events.named("node")
        if payload.get("node") == "worker" and payload.get("phase") == "started"
    ]


def plan(
    *,
    auth: str = AUTH_QUESTION,
    users: str = USER_QUESTION,
) -> Turn:
    return plan_reply(
        [
            {"id": "auth", "question": auth, "focus": "code"},
            {"id": "users", "question": users, "focus": "code"},
        ],
        hint="Name each function and the file it lives in.",
    )


def two_workers(env: Env, *, failure: BaseException | None = None) -> RoutedModel:
    """A model where one worker finds the password check and one finds user creation."""
    auth_key, user_key = env.auth_key, env.user_key
    return RoutedModel(
        planner=plan(),
        workers={
            AUTH_QUESTION: [
                turn(call("search_symbols", {"name": "verify_password"})),
                turn(finish(f"`verify_password` is defined in {SECURITY} [{auth_key}].")),
            ],
            USER_QUESTION: [
                turn(call("search_symbols", {"name": "create_user"})),
                (
                    turn(error=failure)
                    if failure is not None
                    else turn(finish(f"`create_user` is defined in {USERS} [{user_key}]."))
                ),
            ],
        },
        merge=say(message_answer(env)),
        fallback=[turn(finish("A single agent answered."))],
    )


def message_answer(env: Env) -> str:
    return (
        f"Passwords are checked in {SECURITY} [{env.auth_key}], and users are created in "
        f"{USERS} [{env.user_key}]."
    )


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.example.com/v1"))


# --- the fan-out ---------------------------------------------------------------


class TestFanOut:
    async def test_a_question_with_two_halves_runs_two_workers_and_merges(self, env):
        model = two_workers(env)

        ran = await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        result = ran.result
        assert result.status == "completed"
        assert result.stop_reason is StopReason.FINISHED
        assert result.answer.startswith("Passwords are checked")
        assert result.cited == (env.auth_key, env.user_key)
        assert result.plan is not None
        assert [sub.id for sub in result.plan.subquestions] == ["auth", "users"]
        assert [worker.status for worker in result.workers] == ["completed", "completed"]
        assert [worker.question for worker in result.workers] == [AUTH_QUESTION, USER_QUESTION]

        planned = ran.events.named("plan")
        assert planned and planned[0]["skipped"] is False
        assert [sub["focus"] for sub in planned[0]["subquestions"]] == ["code", "code"]

        # Every lane is named, and every agent turn belongs to one.
        assert {payload["worker_id"] for payload in worker_nodes(ran)} == {"w1", "w2"}
        assert [tag.split(":")[0] for tag in model.tags].count("worker") == 4
        agent_nodes = [p for p in ran.events.named("node") if p["node"] == "agent"]
        assert agent_nodes and all(payload.get("worker_id") for payload in agent_nodes)
        assert "fallback" not in model.tags

    async def test_every_worker_event_carries_its_worker_id(self, env):
        model = two_workers(env)

        ran = await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        model_calls = ran.events.named("model_call")
        tool_calls = ran.events.named("tool_call")
        # Two turns and one search plus one finish per worker.
        assert len(model_calls) == 4 and len(tool_calls) == 4
        assert all(payload.get("worker_id") in {"w1", "w2"} for payload in model_calls)
        assert all(payload.get("worker_id") in {"w1", "w2"} for payload in tool_calls)
        assert {payload["worker_id"] for payload in tool_calls} == {"w1", "w2"}
        # The merge and the plan are the run's, not a lane's.
        assert all("worker_id" not in payload for payload in ran.events.named("plan"))

    async def test_workers_start_from_the_shared_seed_plus_their_own_part(self, env):
        model = two_workers(env)

        await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        for question in (AUTH_QUESTION, USER_QUESTION):
            request = model.worker_requests(question)[0]
            seed_item = request["input"][-2]
            own_part = request["input"][-1]
            assert seed_item["role"] == "user"
            assert seed_item["content"].startswith("An initial search of the repository")
            assert question in own_part["content"]
            assert "Your part:" in own_part["content"]

    async def test_every_worker_keeps_the_runs_context_window(self, env):
        model = two_workers(env)

        ran = await run(
            env,
            model,
            config=planner_config(gate=True),
            decider=SufficiencyDecider(1.0, 0.95),
            context_window=128_000,
        )

        windows = {payload["context_window"] for payload in ran.events.named("model_call")}
        assert windows == {128_000}

    async def test_the_merge_sees_both_findings(self, env):
        model = two_workers(env)

        await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        merged = model.tagged("merge")[0]
        sent = "\n".join(_strings(merged["input"]))
        assert AUTH_QUESTION in sent and USER_QUESTION in sent
        assert "`verify_password` is defined" in sent
        assert "`create_user` is defined" in sent
        assert env.auth_key in sent and env.user_key in sent

    async def test_a_rejected_merge_is_continued_not_restarted(self, env):
        # The gate turns the merged answer down once; the agent that picks the
        # run up must see what the workers concluded, not just the seed.
        model = two_workers(env)

        ran = await run(
            env,
            model,
            config=planner_config(gate=True),
            decider=SufficiencyDecider(1.0, 0.0, 0.95),
        )

        assert ran.result.stop_reason is StopReason.FINISHED
        assert ran.result.answer == "A single agent answered."
        [resumed] = model.tagged("fallback")
        sent = "\n".join(_strings(resumed["input"]))
        assert message_answer(env) in sent


def _strings(value: Any) -> list[str]:
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


# --- skipping the plan ----------------------------------------------------------


class TestPlanningIsOptional:
    async def test_a_simple_question_goes_straight_to_the_single_agent(self, env):
        model = RoutedModel(
            planner=plan(),
            fallback=[
                turn(call("search_symbols", {"name": "verify_password"})),
                turn(finish("A single answer.")),
            ],
        )

        ran = await run(env, model, decider=SufficiencyDecider(0.0))

        assert ran.result.plan is None
        assert ran.result.workers == ()
        assert ran.result.answer == "A single answer."
        assert model.tagged("planner") == []
        assert model.tags == ["fallback", "fallback"]
        skipped = ran.events.named("plan")
        assert skipped == [
            {
                "skipped": True,
                "reason": "pre_check",
                "probability": 0.0,
                "threshold": 0.5,
                "model": "fake-decider",
            }
        ]

    async def test_a_plan_too_small_to_fan_out_is_skipped(self, env):
        model = RoutedModel(
            planner=plan_reply([{"id": "only", "question": AUTH_QUESTION, "focus": "code"}]),
            fallback=[turn(finish("A single answer."))],
        )

        ran = await run(env, model, decider=SufficiencyDecider(1.0))

        assert ran.result.plan is None
        assert ran.result.workers == ()
        assert ran.events.named("plan")[-1]["reason"] == "too_few_subquestions"
        assert model.tags == ["planner", "fallback"]

    async def test_a_failed_plan_falls_back_to_the_single_agent(self, env):
        model = RoutedModel(
            planner=turn(error=RuntimeError("the planning call broke")),
            fallback=[turn(finish("A single answer."))],
        )

        ran = await run(env, model, decider=SufficiencyDecider(1.0))

        assert ran.result.status == "completed"
        assert ran.result.plan is None
        assert ran.result.answer == "A single answer."
        assert [p["stage"] for p in ran.events.named("degraded")] == ["planner"]


# --- a worker that fails --------------------------------------------------------


class TestWorkerFailure:
    async def test_the_other_workers_finish_and_the_gap_is_named(self, env):
        failure = RateLimitError("slow down", response=_response(429), body=None)
        model = two_workers(env, failure=failure)

        ran = await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        result = ran.result
        assert result.status == "completed"
        assert result.stop_reason is StopReason.FINISHED
        assert {worker.status for worker in result.workers} == {"completed", "failed"}
        failed = next(worker for worker in result.workers if worker.status == "failed")
        assert failed.question == USER_QUESTION
        assert failed.error is not None and failed.error.startswith("provider:")

        reported = ran.events.named("worker_failed")
        assert [payload["subquestion"] for payload in reported] == [USER_QUESTION]
        # The failed part is in the answer, and the merge was told about it.
        assert USER_QUESTION in result.answer
        merged = "\n".join(_strings(model.tagged("merge")[0]["input"]))
        assert USER_QUESTION in merged
        assert "did not finish" in merged

    async def test_the_trace_names_the_worker_that_failed(self, env):
        failure = RateLimitError("slow down", response=_response(429), body=None)
        model = two_workers(env, failure=failure)

        ran = await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        errors = ran.steps.of_kind("error")
        assert [step.worker_id for step in errors] == ["w2"]
        workers = ran.steps.of_kind("worker")
        assert {step.worker_id for step in workers} == {"w1", "w2"}
        assert len({step.index for step in ran.steps.steps}) == len(ran.steps.steps)

    async def test_a_worker_that_times_out_is_partial_and_the_run_continues(self, env):
        model = RoutedModel(
            planner=plan(),
            workers={
                AUTH_QUESTION: [
                    turn(call("search_symbols", {"name": "verify_password"})),
                    turn(finish(f"`verify_password` is in {SECURITY} [{env.auth_key}].")),
                ],
                USER_QUESTION: [turn(error=TimeoutError())],
            },
            merge=say(message_answer(env)),
        )

        ran = await run(
            env, model, config=planner_config(gate=True), decider=SufficiencyDecider(1.0, 0.95)
        )

        assert ran.result.status == "completed"
        statuses = {worker.question: worker.status for worker in ran.result.workers}
        assert statuses == {AUTH_QUESTION: "completed", USER_QUESTION: "timed_out"}
        assert USER_QUESTION in ran.result.answer


# --- the shared budget ----------------------------------------------------------


class TestSharedBudget:
    async def test_two_workers_cannot_both_spend_the_last_tool_call(self, env):
        model = RoutedModel(
            planner=plan(),
            workers={
                AUTH_QUESTION: [turn(call("search_symbols", {"name": "verify_password"}))],
                USER_QUESTION: [turn(call("search_symbols", {"name": "create_user"}))],
            },
            merge=say("What was found."),
        )

        ran = await run(env, model, config=planner_config(max_tool_calls=1))

        assert ran.result.tool_calls == 1
        assert len(ran.result.workers) == 2
        assert all(worker.status == "partial" for worker in ran.result.workers)
        assert all(worker.stop_reason is StopReason.MAX_TOOL_CALLS for worker in ran.result.workers)
        statuses = sorted(step.payload["status"] for step in ran.steps.of_kind("tool_call"))
        assert statuses == ["ok", "skipped"]
        assert all(
            len(model.worker_requests(question)) == 1 for question in (AUTH_QUESTION, USER_QUESTION)
        )


# --- cancellation ---------------------------------------------------------------


class TestCancellation:
    async def test_cancelling_stops_every_worker(self, env):
        entered = asyncio.Event()
        waiting = 0
        lock = asyncio.Lock()

        async def hold() -> None:
            nonlocal waiting
            async with lock:
                waiting += 1
                if waiting == 2:
                    entered.set()
            await asyncio.Event().wait()

        model = RoutedModel(
            planner=plan(),
            workers={
                AUTH_QUESTION: [
                    turn(call("search_symbols", {"name": "verify_password"}), before=hold)
                ],
                USER_QUESTION: [turn(call("search_symbols", {"name": "create_user"}), before=hold)],
            },
            merge=say("Never reached."),
        )
        events, steps = EventLog(), InMemorySteps()
        task = asyncio.create_task(
            run_agent(QUESTION, (), **run_kwargs(env, model, emit=events, steps=steps))
        )
        requests_at_cancel = 0
        try:
            await asyncio.wait_for(entered.wait(), timeout=30)
            requests_at_cancel = len(model.requests)

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        # Nothing reached the model after the cancel.
        assert len(model.requests) == requests_at_cancel == 3
        assert steps.result is not None and steps.result.status == "cancelled"
        assert events.named("answer") == []

    async def test_the_hard_time_limit_stops_every_worker(self, env):
        model = RoutedModel(
            planner=plan(),
            workers={
                AUTH_QUESTION: [
                    turn(call("search_symbols", {"name": "verify_password"}), before=_never)
                ],
                USER_QUESTION: [
                    turn(call("search_symbols", {"name": "create_user"}), before=_never)
                ],
            },
            merge=say("Never reached."),
        )

        ran = await run(env, model, config=with_hard_cancel(planner_config(), 1))

        assert ran.result.status == "completed"
        assert ran.result.stop_reason is StopReason.HARD_TIMEOUT
        assert ran.result.answer.startswith("The investigation ran out of time")
        # Only the plan and the two worker calls were made; the merge never ran.
        assert model.tagged("merge") == []
        limits = [
            p for p in ran.events.named("degraded") if p.get("limit") == "hard_cancel_seconds"
        ]
        assert len(limits) == 1


async def _never() -> None:
    await asyncio.Event().wait()


# --- sessions -------------------------------------------------------------------


class TestWorkerSessions:
    async def test_each_worker_opens_its_own_session(self, env):
        seen: list[AsyncSession] = []

        @asynccontextmanager
        async def recording():
            async with env.factory() as session:
                seen.append(session)
                yield session

        model = two_workers(env)

        ran = await run(
            env,
            model,
            config=planner_config(gate=True),
            decider=SufficiencyDecider(1.0, 0.95),
            session_factory=recording,
        )

        # The two tool sessions belong to two different workers.
        assert {payload["worker_id"] for payload in ran.events.named("tool_result")} == {"w1", "w2"}
        # The brief, the shared seed, and one session per worker's tool call.
        assert len(seen) == 4
        assert len({id(session) for session in seen}) == len(seen)
