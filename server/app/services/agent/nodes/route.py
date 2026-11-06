"""The route node: where the routing decision lands in the timeline.

The decision itself is made before the graph is built, because it selects the
graph. The node only reports it, so a run's events read in the order things
happened.
"""

from __future__ import annotations

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.state import AgentState


def make_route_node(deps: AgentDeps):
    """Builds the route node."""

    async def route(state: AgentState) -> dict:
        decision = state["route"]
        if decision is not None:
            await deps.event(
                Event.ROUTE,
                {
                    "route": decision.route.value,
                    "accepted": decision.accepted,
                    "confidence": decision.confidence,
                    "probabilities": decision.probabilities,
                    "model": decision.model,
                },
            )
        return {}

    return route
