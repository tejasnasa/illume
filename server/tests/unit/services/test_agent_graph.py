"""The shape of the agent graph, and the tool lists it offers the model."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.agent.budgets import RunBudget
from app.services.agent.deps import AgentDeps
from app.services.agent.graph import NODE_NAMES, build_graph, recursion_limit
from app.services.agent.prompts import RepoBrief
from app.services.agent.steps import InMemorySteps
from app.services.agent.tools import REGISTRY
from tests.fixtures.agent_run import agent_config
from tests.fixtures.retrieval import make_llm

pytestmark = pytest.mark.unit


def make_deps(llm: Any = None, **agent: Any) -> AgentDeps:
    config = agent_config(**agent)
    assert config.agent is not None

    async def emit(event: str, payload: dict[str, Any]) -> None:
        return None

    return AgentDeps(
        config=config,
        agent=config.agent,
        llm=llm or make_llm(),
        client=SimpleNamespace(),
        tool_ctx=SimpleNamespace(),  # type: ignore[arg-type]
        registry=REGISTRY,
        brief=RepoBrief(name="x"),
        budget=RunBudget(config.agent),
        emit=emit,
        steps=InMemorySteps(),
        system_prompt="system",
    )


def edges(deps: AgentDeps) -> set[tuple[str, str]]:
    graph = build_graph(deps).get_graph()
    return {(edge.source, edge.target) for edge in graph.edges}


def test_the_graph_has_the_documented_nodes_and_edges():
    assert set(NODE_NAMES) == {"route", "seed", "agent", "tools", "gate", "synthesize", "verify"}

    assert edges(make_deps()) == {
        ("__start__", "route"),
        ("route", "seed"),
        ("seed", "agent"),
        ("agent", "tools"),
        ("agent", "gate"),
        ("agent", "agent"),
        ("agent", "synthesize"),
        ("tools", "agent"),
        ("tools", "gate"),
        ("tools", "synthesize"),
        ("gate", "agent"),
        ("gate", "synthesize"),
        ("synthesize", "verify"),
        ("verify", "agent"),
        ("verify", "__end__"),
    }


def test_the_only_way_to_the_end_is_through_synthesize_then_verify():
    found = edges(make_deps())

    assert {source for source, target in found if target == "verify"} == {"synthesize"}
    assert {source for source, target in found if target == "__end__"} == {"verify"}


def test_the_recursion_limit_scales_with_the_iteration_limit():
    assert recursion_limit(12) == 4 * 12 + 16
    assert recursion_limit(1) == 20


class TestToolsOffered:
    def test_every_agent_tool_is_offered_by_default(self):
        deps = make_deps()

        assert deps.tool_names == [t.name for t in REGISTRY if t.expose_to_agent]
        assert "finish" in deps.tool_names

    def test_an_allowlist_always_keeps_finish(self):
        deps = make_deps(tools=("search_symbols", "grep_code"))

        assert deps.tool_names == ["search_symbols", "grep_code", "finish"]
        assert deps.allows("grep_code") and not deps.allows("read_file")

    def test_schemas_are_strict_only_for_providers_that_honour_it(self):
        assert all(tool["strict"] is False for tool in make_deps().tools)

        strict = make_deps(llm=make_llm(supports_strict_tools=True))

        assert all(tool["strict"] is True for tool in strict.tools)
        assert all(tool["parameters"]["additionalProperties"] is False for tool in strict.tools)
