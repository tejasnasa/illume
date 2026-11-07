"""The injection guard end to end: planting, screening, quarantine and the clean case."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.services.agent.events import EventLog
from app.services.agent.runner import RunResult, run_agent
from app.services.agent.steps import InMemorySteps
from app.services.agent.tools.context import RepoSnapshot
from app.services.decisions import ChoiceResult, NoulResult
from tests.factories import make_user
from tests.fixtures.agent_run import (
    RoutedModel,
    ScriptedModel,
    SufficiencyDecider,
    Turn,
    agent_config,
    call,
    finish,
    plan_reply,
    planner_config,
    say,
    serialized,
    turn,
)
from tests.fixtures.agent_tools import (
    INJECTION,
    SECURITY,
    ToolRepos,
    seed_injection_repos,
    session_factory_for,
)
from tests.fixtures.retrieval import fake_embedder, make_llm, rolled_back_session

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

QUESTION = "How does authentication work?"
GITHUB_FILE = f"def check():\n    # {INJECTION}\n    return True\n"


@dataclass
class Env:
    factory: async_sessionmaker
    repos: ToolRepos
    db: AsyncSession


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env(engine):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "OPENROUTER_API_KEY", "")
        patch.setattr(settings, "COHERE_API_KEY", "")
        async with rolled_back_session(engine) as db:
            repos = await seed_injection_repos(db, await make_user(db))
            yield Env(factory=serialized(session_factory_for(db.bind)), repos=repos, db=db)


class InjectionAwareDecider(SufficiencyDecider):
    """Calls text suspicious only when it carries the planted instruction."""

    async def batch(self, state: Any, questions: Any):
        self.batches.append((state, dict(questions)))
        answers: dict[str, Any] = {}
        for name, question in questions.items():
            instructions = getattr(question, "instructions", "")
            if getattr(question, "type", None) == "noul":
                probability = 0.9 if INJECTION in instructions else 0.02
                answers[name] = NoulResult(
                    noul=probability,
                    confidence=0.9,
                    latency_ms=1.0,
                    model=self.model_id,
                    provider="fake",
                )
            else:
                answers[name] = ChoiceResult(
                    choice="supports",
                    probabilities={"supports": 0.9},
                    confidence=0.9,
                    latency_ms=1.0,
                    model=self.model_id,
                    provider="fake",
                )
        return answers


class SusceptibleModel(ScriptedModel):
    """Calls a tool, then follows the planted instruction if the text reached it."""

    def __init__(self, first: Turn, *, compromised: Turn, safe: Turn) -> None:
        super().__init__()
        self.first = first
        self.compromised = compromised
        self.safe = safe

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(copy.deepcopy(kwargs))
        if len(self.requests) == 1:
            reply = self.first
        elif INJECTION in _strings(kwargs.get("input")):
            reply = self.compromised
        else:
            reply = self.safe
        return self._events(reply)


def _strings(value: Any) -> str:
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
    return "\n".join(found)


@dataclass
class Ran:
    result: RunResult
    events: EventLog
    steps: InMemorySteps


async def run(
    env: Env,
    model: ScriptedModel,
    *,
    config: Any | None = None,
    decider: Any | None = None,
    repository: Any = None,
    question: str = QUESTION,
) -> Ran:
    events, steps = EventLog(), InMemorySteps()
    result = await run_agent(
        question,
        (),
        repository=RepoSnapshot.from_repository(repository or env.repos.a.repo),
        session_factory=env.factory,
        llm=make_llm(),
        config=config or agent_config(guard=True, seed=False),
        embed=fake_embedder(),
        client_factory=model.factory,
        decider=decider or InjectionAwareDecider(),
        emit=events,
        steps=steps,
    )
    return Ran(result=result, events=events, steps=steps)


def output_for(model: ScriptedModel, request: int, call_id: str) -> str:
    for item in model.requests[request]["input"]:
        if isinstance(item, dict) and item.get("call_id") == call_id:
            if item.get("type") == "function_call_output":
                return item["output"]
    raise AssertionError(f"request {request} has no output for {call_id}")


def quarantined_steps(ran: Ran) -> list[dict[str, Any]]:
    return [
        step.payload for step in ran.steps.of_kind("tool_call") if step.payload.get("quarantined")
    ]


class TestQuarantine:
    async def test_the_fixture_plants_the_instruction_in_a_comment_and_a_docstring(self, env):
        comment = env.repos.a.symbols[(SECURITY, "verify_password")].source_code
        docstring = env.repos.a.symbols[("app/users/service.py", "create_user")].source_code

        assert f"# {INJECTION}" in comment
        assert f'"""{INJECTION}' in docstring
        assert any(INJECTION in commit.message for commit in env.repos.a.commits.values())
        assert any(
            INJECTION in pull_request.description
            for pull_request in env.repos.a.pull_requests.values()
        )

    async def test_a_planted_comment_is_withheld_before_the_model_sees_it(self, env):
        grep = call("grep_code", {"pattern": "Ignore previous"})
        model = ScriptedModel([turn(grep), turn(finish("The authentication uses bcrypt."))])
        decider = InjectionAwareDecider()

        ran = await run(env, model, decider=decider)

        assert ran.result.quarantines == 1
        [event] = ran.events.named("quarantine")
        assert event["tool"] == "grep_code"
        assert event["probability"] == 0.9
        assert any(key.startswith(f"F:{SECURITY}:") for key in event["keys"])
        assert event["key"] in event["keys"]

        shown = output_for(model, 1, grep["call_id"])
        assert INJECTION not in shown
        assert "<quarantined" in shown and 'p="0.90"' in shown
        assert "withheld" in shown

        # The original survives in the step log, and the step is flagged.
        [step] = quarantined_steps(ran)
        assert INJECTION in step["text"]
        assert step["quarantine_probability"] == 0.9
        assert step["quarantine_key"] == event["key"]

        # One batch screened one round, one question per block.
        assert len(decider.batches) == 1
        assert len(decider.batches[0][1]) == step["text"].count("<source key=")

    async def test_the_model_follows_the_instruction_without_the_guard_and_not_with_it(self, env):
        first = turn(call("grep_code", {"pattern": "Ignore previous"}))
        compromised = turn(finish("The authentication is insecure."))
        safe = turn(finish("The authentication uses bcrypt."))

        unguarded = await run(
            env,
            SusceptibleModel(first, compromised=compromised, safe=safe),
            config=agent_config(guard=False, seed=False),
        )
        guarded = await run(
            env,
            SusceptibleModel(first, compromised=compromised, safe=safe),
            config=agent_config(guard=True, seed=False),
        )

        assert unguarded.result.answer == "The authentication is insecure."
        assert guarded.result.answer == "The authentication uses bcrypt."
        assert guarded.result.quarantines == 1

    async def test_a_clean_repository_produces_no_quarantine(self, env):
        grep = call("grep_code", {"pattern": "Ignore previous"})
        model = ScriptedModel([turn(grep), turn(finish("The authentication uses bcrypt."))])

        ran = await run(env, model, repository=env.repos.b.repo)

        assert ran.result.quarantines == 0
        assert ran.events.named("quarantine") == []
        assert output_for(model, 1, grep["call_id"]).startswith("0 symbols matched")

    async def test_two_tool_calls_in_one_round_are_screened_in_one_batch(self, env):
        grep = call("grep_code", {"pattern": "Ignore previous"})
        history = call("search_history", {"query": "bcrypt", "kind": "both"})
        model = ScriptedModel([turn(grep, history), turn(finish("Done."))])
        decider = InjectionAwareDecider()

        ran = await run(env, model, decider=decider)

        assert len(decider.batches) == 1
        assert len(decider.batches[0][1]) >= 2
        assert ran.result.quarantines >= 1

    async def test_only_the_poisoned_block_of_a_result_is_withheld(self, env):
        search = call("search_code", {"query": "password hashing", "k": 10})
        model = ScriptedModel([turn(search), turn(finish("Done."))])

        ran = await run(env, model)

        [event] = ran.events.named("quarantine")
        [step] = quarantined_steps(ran)
        assert step["text"].count("<source key=") > len(event["keys"])
        shown = output_for(model, 1, search["call_id"])
        assert INJECTION not in shown
        assert shown.count("<quarantined") == len(event["keys"])
        # The clean blocks were shown, and they, not the withheld ones, are evidence.
        assert "<source key=" in shown
        assert ran.result.evidence
        assert not set(event["keys"]) & set(ran.result.evidence)

    async def test_the_seed_is_screened_before_the_first_turn(self, env):
        unguarded = ScriptedModel([turn(finish("Done."))])
        guarded = ScriptedModel([turn(finish("Done."))])

        question = "How does verify_password check a password?"
        await run(env, unguarded, config=agent_config(guard=False, seed=True), question=question)
        ran = await run(env, guarded, config=agent_config(guard=True, seed=True), question=question)

        # Without the screen the seed carries the planted text to the model.
        assert INJECTION in _strings(unguarded.requests[0]["input"])
        assert INJECTION not in _strings(guarded.requests[0]["input"])
        assert "<quarantined" in _strings(guarded.requests[0]["input"])
        events = ran.events.named("quarantine")
        assert events and {event["tool"] for event in events} == {"seed"}
        assert ran.result.quarantines == len(events)
        withheld = {key for event in events for key in event["keys"]}
        assert not withheld & set(ran.result.evidence)
        [seed_step] = ran.steps.of_kind("seed")
        assert set(seed_step.payload["withheld"]) == withheld
        assert all(INJECTION in step.payload["text"] for step in ran.steps.of_kind("quarantine"))

    async def test_a_defaulted_screening_verdict_withholds_the_text(self, env):
        grep = call("grep_code", {"pattern": "Ignore previous"})
        model = ScriptedModel([turn(grep), turn(finish("The authentication uses bcrypt."))])
        decider = SufficiencyDecider(screening=0.0, defaulted=True)

        ran = await run(env, model, decider=decider)

        assert ran.result.quarantines == 1
        [event] = ran.events.named("quarantine")
        assert event["probability"] == 0.0
        assert INJECTION not in output_for(model, 1, grep["call_id"])

    async def test_a_screening_outage_withholds_rather_than_letting_text_through(self, env):
        grep = call("grep_code", {"pattern": "Ignore previous"})
        model = ScriptedModel([turn(grep), turn(finish("The authentication uses bcrypt."))])
        decider = SufficiencyDecider(fail_batch=True)

        ran = await run(env, model, decider=decider)

        assert ran.result.quarantines == 1
        assert INJECTION not in output_for(model, 1, grep["call_id"])
        assert [p["stage"] for p in ran.events.named("degraded")] == ["guard"]

    async def test_a_worker_withholds_the_injection_before_merging(self, env):
        subquestion = "How is a password checked?"
        injection = call("grep_code", {"pattern": "Ignore previous"})
        model = RoutedModel(
            planner=plan_reply(
                [
                    {"id": "auth", "question": subquestion, "focus": "code"},
                    {"id": "other", "question": "How is a user created?", "focus": "code"},
                ]
            ),
            workers={
                subquestion: [turn(injection), turn(finish("It checks with bcrypt."))],
                "How is a user created?": [
                    turn(call("search_symbols", {"name": "create_user"})),
                    turn(finish("It creates a user.")),
                ],
            },
            merge=say("Authentication checks with bcrypt."),
        )
        decider = InjectionAwareDecider(1.0)

        ran = await run(
            env,
            model,
            config=planner_config(guard=True, seed=False),
            decider=decider,
        )

        events = ran.events.named("quarantine")
        assert events and any(event.get("worker_id") for event in events)
        assert ran.result.quarantines >= 1


@respx.mock
@pytest.mark.parametrize(
    ("name", "arguments", "prefixes"),
    [
        ("grep_code", {"pattern": "Ignore previous"}, ("F:",)),
        ("search_code", {"query": "verify_password", "k": 10}, ("F:",)),
        ("search_history", {"query": "bcrypt", "kind": "both"}, ("C:", "PR:")),
        ("read_file", {"path": SECURITY}, ("F:",)),
    ],
)
async def test_every_tool_that_returns_repo_text_is_screened(env, name, arguments, prefixes):
    respx.get(url__regex=r"https://api\.github\.com/repos/.*/contents/.*").mock(
        return_value=httpx.Response(200, text=GITHUB_FILE)
    )
    tool_call = call(name, arguments)
    model = ScriptedModel([turn(tool_call), turn(finish("Done."))])

    ran = await run(env, model, decider=InjectionAwareDecider())

    [event] = ran.events.named("quarantine")
    assert event["tool"] == name
    assert any(key.startswith(prefixes) for key in event["keys"]), event
    assert INJECTION not in output_for(model, 1, tool_call["call_id"])
