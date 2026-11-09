"""Splitting a question, sharing the budget, and merging what workers found."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.services.agent.budgets import RunBudget
from app.services.agent.deps import AgentDeps
from app.services.agent.graph import build_graph
from app.services.agent.nodes.planner import parse_plan, worker_agent_settings
from app.services.agent.prompts import with_coverage_note
from app.services.agent.state import (
    Evidence,
    StopReason,
    WorkerResult,
    merge_evidence,
)
from app.services.agent.steps import InMemorySteps
from app.services.agent.tools import REGISTRY
from tests.fixtures.agent_run import agent_config, planner_config
from tests.fixtures.retrieval import make_llm

pytestmark = pytest.mark.unit


# --- parsing the plan -----------------------------------------------------------


class TestParsePlan:
    def test_a_well_formed_plan_is_kept(self):
        plan = parse_plan(
            {
                "subquestions": [
                    {"id": "a", "question": "Where is auth?", "focus": "code"},
                    {"id": "b", "question": "How does auth import users?", "focus": "graph"},
                ],
                "synthesis_hint": "Lead with the flow.",
            },
            max_workers=4,
            min_subquestions=2,
        )

        assert plan is not None
        assert [sub.id for sub in plan.subquestions] == ["a", "b"]
        assert [sub.focus for sub in plan.subquestions] == ["code", "graph"]
        assert plan.synthesis_hint == "Lead with the flow."

    def test_a_plan_with_too_few_questions_is_not_worth_running(self):
        value = {"subquestions": [{"id": "a", "question": "Where is auth?"}], "synthesis_hint": ""}

        assert parse_plan(value, max_workers=4, min_subquestions=2) is None

    def test_a_plan_longer_than_the_fan_out_is_cut(self):
        value = {
            "subquestions": [
                {"id": str(index), "question": f"part {index}", "focus": "code"}
                for index in range(9)
            ],
            "synthesis_hint": "",
        }

        plan = parse_plan(value, max_workers=3, min_subquestions=2)

        assert plan is not None
        assert [sub.question for sub in plan.subquestions] == ["part 0", "part 1", "part 2"]

    def test_empty_questions_are_dropped_and_focus_defaults(self):
        value = {
            "subquestions": [
                {"id": "a", "question": "  ", "focus": "code"},
                {"id": "b", "question": "first", "focus": "nonsense"},
                {"question": "second"},
            ],
            "synthesis_hint": 4,
        }

        plan = parse_plan(value, max_workers=4, min_subquestions=2)

        assert plan is not None
        assert [sub.question for sub in plan.subquestions] == ["first", "second"]
        assert all(sub.focus == "code" for sub in plan.subquestions)
        assert plan.subquestions[1].id == "q3"
        assert plan.synthesis_hint == ""

    @pytest.mark.parametrize("value", [None, [], "plan", {"subquestions": "two"}, {}])
    def test_malformed_output_is_refused(self, value):
        assert parse_plan(value, max_workers=4, min_subquestions=2) is None


# --- the graph ------------------------------------------------------------------


def make_deps(config: Any) -> AgentDeps:
    assert config.agent is not None
    return AgentDeps(
        config=config,
        agent=config.agent,
        llm=make_llm(),
        client=SimpleNamespace(),
        tool_ctx=SimpleNamespace(),  # type: ignore[arg-type]
        registry=REGISTRY,
        brief=SimpleNamespace(render=lambda: "brief"),  # type: ignore[arg-type]
        budget=RunBudget(config.agent),
        emit=_discard,
        steps=InMemorySteps(),
        system_prompt="system",
    )


async def _discard(event: str, payload: dict[str, Any]) -> None:
    return None


def edges(config: Any) -> set[tuple[str, str]]:
    graph = build_graph(make_deps(config)).get_graph()
    return {(edge.source, edge.target) for edge in graph.edges}


class TestPlannerGraph:
    def test_the_planner_sits_between_the_seed_and_the_fan_out(self):
        found = edges(planner_config())

        assert ("seed", "planner") in found
        assert ("planner", "agent") in found
        assert ("planner", "worker") in found
        assert ("worker", "merge") in found
        assert ("merge", "synthesize") in found

    def test_the_single_agent_graph_is_unchanged(self):
        found = edges(agent_config())

        assert found == {
            ("__start__", "route"),
            ("route", "seed"),
            ("seed", "agent"),
            ("agent", "tools"),
            ("agent", "agent"),
            ("agent", "synthesize"),
            ("tools", "agent"),
            ("tools", "synthesize"),
            ("synthesize", "__end__"),
        }

    def test_workers_take_their_turns_from_the_planner(self):
        config = planner_config(worker_iterations=3)

        settings = worker_agent_settings(make_deps(config))

        assert settings.max_iterations == 3
        assert settings.context_window == config.agent.context_window  # type: ignore[union-attr]


# --- the shared budget ----------------------------------------------------------


class TestSharedBudget:
    async def test_two_workers_cannot_both_spend_the_last_tool_call(self):
        config = agent_config(max_tool_calls=1)
        assert config.agent is not None

        budget = RunBudget(config.agent)

        granted = await asyncio.gather(budget.reserve_tool_calls(1), budget.reserve_tool_calls(1))

        assert sorted(granted) == [0, 1]

    async def test_tokens_from_every_worker_add_up(self):
        config = agent_config()
        assert config.agent is not None

        budget = RunBudget(config.agent)

        await asyncio.gather(*(budget.add_usage(100, 10) for _ in range(3)))

        assert (await budget.snapshot()).input_tokens == 300


# --- the evidence reducer under concurrent writes -------------------------------


class _EvidenceState(TypedDict):
    seeds: list[str]
    evidence: Annotated[dict[str, Evidence], merge_evidence]


def test_concurrent_branches_merge_evidence_by_key():
    def fan_out(state: _EvidenceState):
        return [Send("branch", {"seed": seed}) for seed in state["seeds"]]

    def branch(state: dict[str, str]) -> dict[str, Any]:
        return {
            "evidence": {
                "F:app/a.py:1-2": Evidence(
                    key="F:app/a.py:1-2",
                    text=state["seed"],
                    first_step=len(state["seed"]),
                    found_by=("seed",),
                )
            }
        }

    graph = StateGraph(_EvidenceState)
    graph.add_node("branch", branch)
    graph.add_conditional_edges(START, fan_out, ["branch"])
    graph.add_edge("branch", END)
    compiled = graph.compile()

    final = asyncio.run(compiled.ainvoke({"seeds": ["one", "longer"], "evidence": {}}))

    merged = final["evidence"]["F:app/a.py:1-2"]
    assert merged.text == "longer"
    assert merged.first_step == 3


# --- naming what no worker covered ----------------------------------------------


def _result(question: str, status: str = "failed") -> WorkerResult:
    return WorkerResult(
        worker_id="w1",
        subquestion_id="q1",
        question=question,
        focus="code",
        status=status,  # type: ignore[arg-type]
        stop_reason=StopReason.ERROR,
        answer="",
    )


class TestCoverageNote:
    def test_a_failed_worker_is_named(self):
        answer = with_coverage_note("The answer.", [_result("Who calls it?")])

        assert "Who calls it?" in answer
        assert answer.startswith("The answer.")

    def test_an_answer_that_already_names_it_is_left_alone(self):
        answer = with_coverage_note(
            "Who calls it? could not be checked.", [_result("Who calls it?")]
        )

        assert answer == "Who calls it? could not be checked."

    def test_nothing_is_added_when_every_worker_finished(self):
        answer = with_coverage_note("The answer.", [_result("done", status="completed")])

        assert answer == "The answer."
