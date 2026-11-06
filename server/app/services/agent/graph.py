"""The agent graph: a bounded loop of model turns and tool calls, with a gate.

The nodes and what leaves each one:

* ``route`` then ``seed`` then ``agent``, always.
* ``agent`` goes to ``tools`` when the model asked for tools, to ``gate`` when it
  answered in plain text, back to itself after a nudge, and to ``synthesize``
  when a limit was reached.
* ``tools`` goes back to ``agent``, to ``gate`` when ``finish`` was called, or to
  ``synthesize`` when the run should stop.
* ``gate`` goes back to ``agent`` when the evidence was judged insufficient, and
  to ``synthesize`` otherwise.
* ``synthesize`` goes to ``verify``, which ends the run, or sends it back to
  ``agent`` to repair unsupported claims.

``finish`` is a tool, so the tools node is where a finished answer appears and
where the loop hands over to the gate. Every way out of the loop passes through
``synthesize``, so a run always produces an answer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.nodes import (
    make_agent_node,
    make_gate_node,
    make_route_node,
    make_seed_node,
    make_synthesize_node,
    make_tools_node,
    make_verify_node,
)
from app.services.agent.state import AgentState

NODE_NAMES = ("route", "seed", "agent", "tools", "gate", "synthesize", "verify")

# The graph takes this many steps per model turn at most (agent, tools, and the
# gate that may follow), plus the nodes outside the loop.
STEPS_PER_ITERATION = 4
STEPS_OUTSIDE_LOOP = 16


def recursion_limit(max_iterations: int) -> int:
    """The step limit to run the graph under for an agent with this many turns."""
    return STEPS_PER_ITERATION * max_iterations + STEPS_OUTSIDE_LOOP


def _after_agent(state: AgentState) -> str:
    return {
        "tools": "tools",
        "text": "gate",
        "nudge": "agent",
        "limit": "synthesize",
    }[state["turn_end"] or "limit"]


def _after_tools(state: AgentState) -> str:
    if state["stop_reason"] is not None:
        return "synthesize"
    if state["turn_end"] == "finish":
        return "gate"
    return "agent"


def _after_gate(state: AgentState) -> str:
    return "synthesize" if state["stop_reason"] is not None else "agent"


def _after_verify(state: AgentState) -> str:
    return "agent" if state["answer"] is None else END


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
        "route": make_route_node(deps),
        "seed": make_seed_node(deps),
        "agent": make_agent_node(deps),
        "tools": make_tools_node(deps),
        "gate": make_gate_node(deps),
        "synthesize": make_synthesize_node(deps),
        "verify": make_verify_node(deps),
    }
    graph = StateGraph(AgentState)
    for name in NODE_NAMES:
        graph.add_node(name, cast(Any, _instrumented(deps, name, nodes[name])))

    graph.add_edge(START, "route")
    graph.add_edge("route", "seed")
    graph.add_edge("seed", "agent")
    graph.add_conditional_edges("agent", _after_agent, ["tools", "gate", "agent", "synthesize"])
    graph.add_conditional_edges("tools", _after_tools, ["gate", "agent", "synthesize"])
    graph.add_conditional_edges("gate", _after_gate, ["agent", "synthesize"])
    graph.add_edge("synthesize", "verify")
    graph.add_conditional_edges("verify", _after_verify, ["agent", END])
    return graph.compile()
