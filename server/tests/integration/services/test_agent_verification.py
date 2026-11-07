"""Citation verification end to end: verdicts, repair rounds, marks and the report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.services.agent.events import EventLog
from app.services.agent.runner import RunResult, run_agent
from app.services.agent.state import ClaimVerdict
from app.services.agent.steps import InMemorySteps
from app.services.agent.tools.context import RepoSnapshot
from tests.factories import make_user
from tests.fixtures.agent_run import (
    RoutedModel,
    ScriptedModel,
    SufficiencyDecider,
    agent_config,
    call,
    finish,
    plan_reply,
    planner_config,
    say,
    serialized,
    turn,
)
from tests.fixtures.agent_tools import SECURITY, ToolRepos, seed_tool_repos, session_factory_for
from tests.fixtures.retrieval import fake_embedder, make_llm, rolled_back_session

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

QUESTION = "Where is `verify_password` defined?"
USERS = "app/users/service.py"


@dataclass
class Env:
    factory: async_sessionmaker
    repos: ToolRepos
    db: AsyncSession

    @property
    def symbol_key(self) -> str:
        symbol = self.repos.a.symbols[(SECURITY, "verify_password")]
        return f"F:{SECURITY}:{symbol.start_line}-{symbol.end_line}"

    @property
    def user_key(self) -> str:
        symbol = self.repos.a.symbols[(USERS, "create_user")]
        return f"F:{USERS}:{symbol.start_line}-{symbol.end_line}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env(engine):
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


async def run(
    env: Env,
    model: ScriptedModel,
    *,
    config: Any | None = None,
    decider: Any | None = None,
    question: str = QUESTION,
) -> Ran:
    events, steps = EventLog(), InMemorySteps()
    result = await run_agent(
        question,
        (),
        repository=RepoSnapshot.from_repository(env.repos.a.repo),
        session_factory=env.factory,
        llm=make_llm(),
        config=config or agent_config(verify=True, seed=False, max_repair_rounds=0),
        embed=fake_embedder(),
        client_factory=model.factory,
        decider=decider or SufficiencyDecider(),
        emit=events,
        steps=steps,
    )
    return Ran(result=result, events=events, steps=steps)


def search(name: str = "verify_password") -> dict[str, Any]:
    return call("search_symbols", {"name": name})


class TestVerdicts:
    @pytest.mark.parametrize(
        ("choice", "expected"),
        [
            ("supports", ClaimVerdict.SUPPORTED),
            ("partially_supports", ClaimVerdict.PARTIALLY_SUPPORTED),
            ("does_not_support", ClaimVerdict.UNSUPPORTED),
            ("contradicts", ClaimVerdict.CONTRADICTED),
        ],
    )
    async def test_each_decider_verdict_produces_its_mark(self, env, choice, expected):
        key = env.symbol_key
        model = ScriptedModel([turn(search()), turn(finish(f"Bcrypt is used [{key}]."))])
        decider = SufficiencyDecider(verdicts=[choice])

        ran = await run(env, model, decider=decider)

        report = ran.result.verification
        assert report is not None
        assert report.claims[0].verdict is expected
        assert ran.result.answer == f"Bcrypt is used [{key}]. [[verify:{expected.value}]]"
        # One batched request answered the one pair.
        assert len(decider.batches) == 1
        assert len(decider.batches[0][1]) == 1

    async def test_a_key_the_run_never_retrieved_is_unresolved_whatever_the_decider_says(self, env):
        model = ScriptedModel(
            [turn(search()), turn(finish("Bcrypt is used [F:not/retrieved.py:1-2]."))]
        )
        decider = SufficiencyDecider(verdicts=["supports"])

        ran = await run(env, model, decider=decider)

        report = ran.result.verification
        assert report is not None
        assert report.claims[0].verdict is ClaimVerdict.UNRESOLVED_KEY
        assert report.claims[0].unresolved == ("F:not/retrieved.py:1-2",)
        # Nothing was asked: there was no evidence to judge.
        assert decider.batches == []
        assert "[[verify:unresolved_key]]" in ran.result.answer
        # The claim itself is still there.
        assert "Bcrypt is used [F:not/retrieved.py:1-2]." in ran.result.answer

    async def test_an_uncited_fact_is_counted_and_marked(self, env):
        answer = (
            "`verify_password` lives in app/auth/security.py. It has 12 lines. It is used often."
        )
        model = ScriptedModel([turn(finish(answer))])

        ran = await run(env, model)

        report = ran.result.verification
        assert report is not None
        assert report.uncited == (
            "`verify_password` lives in app/auth/security.py.",
            "It has 12 lines.",
        )
        assert report.counts["uncited"] == 2
        assert report.failed is False
        for sentence in report.uncited:
            assert sentence in ran.result.answer
        assert ran.result.answer.count("[[verify:uncited]]") == 2

    async def test_a_defaulted_verdict_is_not_supported(self, env):
        key = env.symbol_key
        model = ScriptedModel([turn(search()), turn(finish(f"Bcrypt is used [{key}]."))])
        decider = SufficiencyDecider(verdicts=["supports"], defaulted=True)

        ran = await run(env, model, decider=decider)

        report = ran.result.verification
        assert report is not None and report.defaulted is True
        assert report.claims[0].verdict is ClaimVerdict.UNSUPPORTED
        assert "[[verify:unsupported]]" in ran.result.answer
        assert "[[verify:supported]]" not in ran.result.answer

    async def test_a_decision_outage_marks_claims_unsupported_rather_than_trusting_them(self, env):
        key = env.symbol_key
        model = ScriptedModel([turn(search()), turn(finish(f"Bcrypt is used [{key}]."))])
        decider = SufficiencyDecider(fail_batch=True)

        ran = await run(env, model, decider=decider)

        report = ran.result.verification
        assert report is not None and report.defaulted is True
        assert report.claims[0].verdict is ClaimVerdict.UNSUPPORTED
        assert "[[verify:unsupported]]" in ran.result.answer
        assert ran.result.status == "completed"


class TestRepair:
    async def test_one_repair_round_runs_then_the_mark_stays_and_nothing_is_deleted(self, env):
        key = env.symbol_key
        answer = f"Bcrypt is used [{key}]."
        model = ScriptedModel([turn(search()), turn(finish(answer)), turn(finish(answer))])
        decider = SufficiencyDecider(verdicts=["does_not_support", "does_not_support"])

        ran = await run(
            env,
            model,
            config=agent_config(verify=True, seed=False),
            decider=decider,
        )

        assert len(model.requests) == 3
        feedback = model.requests[2]["input"][-1]
        assert feedback["role"] == "user"
        assert "does not support" in feedback["content"]
        assert key in feedback["content"]
        assert answer in feedback["content"]
        assert ran.result.answer == f"{answer} [[verify:unsupported]]"
        assert "Bcrypt is used" in ran.result.answer
        assert ran.result.repair_rounds == 1

        verify_events = ran.events.named("verify")
        assert [payload["repair"] for payload in verify_events] == [True, False]
        assert len(ran.steps.of_kind("verify")) == 2
        assert ran.steps.of_kind("verify")[-1].payload["counts"]["unsupported"] == 1

    async def test_the_report_counts_match_the_per_claim_table(self, env):
        key = env.symbol_key
        answer = (
            f"A is here [{key}]. "
            f"B is not here [{key}]. "
            "C is elsewhere [F:gone/away.py:1-2]. "
            "There are 3 files."
        )
        model = ScriptedModel([turn(search()), turn(finish(answer))])
        decider = SufficiencyDecider(verdicts=["supports", "does_not_support"])

        ran = await run(env, model, decider=decider)

        report = ran.result.verification
        assert report is not None
        assert len(report.claims) == 3
        assert report.counts == {
            "supported": 1,
            "partially_supported": 0,
            "unsupported": 1,
            "contradicted": 0,
            "unresolved_key": 1,
            "uncited": 1,
        }
        assert report.to_dict()["counts"] == report.counts
        assert [claim.verdict for claim in report.claims] == [
            ClaimVerdict.SUPPORTED,
            ClaimVerdict.UNSUPPORTED,
            ClaimVerdict.UNRESOLVED_KEY,
        ]
        assert ran.result.answer.count("[[verify:") == 4


class TestPlannerAnswer:
    async def test_a_merged_answer_goes_through_the_same_verify_path(self, env):
        auth_key, user_key = env.symbol_key, env.user_key
        merged = f"Passwords are checked in {SECURITY} [{auth_key}]."
        model = RoutedModel(
            planner=plan_reply(
                [
                    {"id": "auth", "question": QUESTION, "focus": "code"},
                    {"id": "users", "question": "Where is `create_user` defined?", "focus": "code"},
                ]
            ),
            workers={
                QUESTION: [
                    turn(call("search_symbols", {"name": "verify_password"})),
                    turn(finish(f"`verify_password` is in {SECURITY} [{auth_key}].")),
                ],
                "Where is `create_user` defined?": [
                    turn(call("search_symbols", {"name": "create_user"})),
                    turn(finish(f"`create_user` is in {USERS} [{user_key}].")),
                ],
            },
            merge=say(merged),
        )
        decider = SufficiencyDecider(1.0, verdicts=["does_not_support"])

        ran = await run(
            env,
            model,
            config=planner_config(verify=True, seed=False, max_repair_rounds=0),
            decider=decider,
        )

        report = ran.result.verification
        assert ran.result.plan is not None
        assert report is not None and report.claims
        assert report.claims[0].verdict is ClaimVerdict.UNSUPPORTED
        assert merged in ran.result.answer
        assert "[[verify:unsupported]]" in ran.result.answer
        assert ran.events.named("verify")
