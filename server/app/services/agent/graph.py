"""The agent graph: a bounded loop of model turns and tool calls.

The nodes and what leaves each one:

* ``seed`` then ``agent``, always.
* ``agent`` goes to ``tools`` when the model asked for tools, to ``synthesize``
  when it answered in plain text or a limit was reached, and back to itself
  after a nudge.
* ``tools`` goes back to ``agent``, or to ``synthesize`` when ``finish`` was
  called or the run should stop.
* ``synthesize`` ends the run.

With parallel execution the question may be split first: ``seed`` leads to
``planner`` instead of ``agent``. When the plan says the question is simple,
``planner`` leads to ``agent`` and the graph is the one above. Otherwise it
fans out to one ``worker`` per sub-question, every worker leads to ``merge``,
and ``merge`` leads to ``synthesize`` as a finished draft. Each worker is the agent
loop compiled as a subgraph of its own.

``finish`` is a tool, so the tools node is where a finished answer appears and
where the loop hands over to ``synthesize``. Every way out of the loop passes through
``synthesize``, so a run always produces an answer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.nodes import (
    make_agent_node,
    make_merge_node,
    make_planner_node,
    make_seed_node,
    make_synthesize_node,
    make_tools_node,
    make_worker_node,
)
from app.services.agent.nodes.planner import worker_id
from app.services.agent.nodes.worker import WorkerInput, worker_items
from app.services.agent.state import AgentState

NODE_NAMES = ("seed", "agent", "tools", "synthesize")

PLANNER_NODE_NAMES = ("planner", "worker", "merge")

# The graph takes this many steps per model turn at most (agent and tools), plus
# the nodes outside the loop.
STEPS_PER_ITERATION = 2
STEPS_OUTSIDE_LOOP = 16


def recursion_limit(max_iterations: int) -> int:
    """The step limit to run the graph under for an agent with this many turns."""
    return STEPS_PER_ITERATION * max_iterations + STEPS_OUTSIDE_LOOP


def _after_agent(state: AgentState) -> str:
    return {
        "tools": "tools",
        "text": "synthesize",
        "nudge": "agent",
        "limit": "synthesize",
    }[state["turn_end"] or "limit"]


def _after_tools(state: AgentState) -> str:
    if state["stop_reason"] is not None or state["turn_end"] == "finish":
        return "synthesize"
    return "agent"


def _after_planner(state: AgentState) -> str | list[Send]:
    """The single agent when planning was skipped, one send per sub-question otherwise."""
    plan = state["plan"]
    if plan is None:
        return "agent"
    question = state["standalone_question"] or state["question"]
    return [
        Send(
            "worker",
            WorkerInput(
                worker_id=worker_id(index),
                subquestion=subquestion,
                items=worker_items(state["items"], subquestion, question),
                evidence=dict(state["evidence"]),
                question=question,
            ),
        )
        for index, subquestion in enumerate(plan.subquestions, start=1)
    ]


def _instrumented(
    deps: AgentDeps, name: str, node: Callable[[AgentState], Awaitable[dict[str, Any]]]
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Wraps a node so its start and end land in the event stream."""

    async def run(state: AgentState) -> dict[str, Any]:
        await deps.event(Event.NODE, {"node": name, "phase": "started"})
        update = await node(state)
        await deps.event(Event.NODE, {"node": name, "phase": "done"})
        return update

    return run


def build_graph(deps: AgentDeps):
    """Builds and compiles the graph for one run.

    No checkpointer is attached: runs are short and not resumable, and the step
    log is the record of what happened.

    Args:
        deps: The run's collaborators, closed over by each node.
    """
    nodes = {
        "seed": make_seed_node(deps),
        "agent": make_agent_node(deps),
        "tools": make_tools_node(deps),
        "synthesize": make_synthesize_node(deps),
    }
    graph = StateGraph(AgentState)
    for name in NODE_NAMES:
        graph.add_node(name, cast(Any, _instrumented(deps, name, nodes[name])))

    graph.add_edge(START, "seed")
    if deps.config.execution == "planner":
        planner = _instrumented(deps, "planner", make_planner_node(deps))
        graph.add_node("planner", cast(Any, planner))
        graph.add_node(
            "worker",
            cast(Any, make_worker_node(deps)),
            input_schema=WorkerInput,
        )
        graph.add_node("merge", cast(Any, _instrumented(deps, "merge", make_merge_node(deps))))
        graph.add_edge("seed", "planner")
        graph.add_conditional_edges("planner", _after_planner, ["agent", "worker"])
        graph.add_edge("worker", "merge")
        graph.add_edge("merge", "synthesize")
    else:
        graph.add_edge("seed", "agent")
    graph.add_conditional_edges("agent", _after_agent, ["tools", "agent", "synthesize"])
    graph.add_conditional_edges("tools", _after_tools, ["agent", "synthesize"])
    graph.add_edge("synthesize", END)
    return graph.compile()
