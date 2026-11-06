"""What the graph's nodes share besides the state.

State is for values that change as the run goes. Everything fixed for the whole
run, and everything that cannot be copied or serialised (the model client, the
budget, the decider, the step log), is carried here and closed over by each node
when the graph is built.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.budgets import RunBudget
from app.services.agent.events import safe_emit
from app.services.agent.prompts import RepoBrief
from app.services.agent.state import AgentState, VerificationReport
from app.services.agent.steps import StepKind, StepRecord, StepRecorder
from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.registry import ToolRegistry, ToolResult
from app.services.decisions import Decider, DecisionRecord
from app.services.llm_config import LLMConfig
from app.services.retrieval.channels.base import Emit
from app.services.retrieval.config import AgentConfig, PipelineConfig

Verifier = Callable[[AgentState], Awaitable[VerificationReport | None]]
"""Checks a finished answer's citations. Returns the claims that failed, or ``None``."""

ResultScreen = Callable[[ToolResult], Awaitable[ToolResult]]
"""Inspects a tool result before the model sees it, and may replace it."""

AGENT_MAX_OUTPUT_TOKENS = 16_000
SYNTHESIS_MAX_OUTPUT_TOKENS = 8_000
SYNTHESIS_EFFORT = "low"

# Turns in a row with nothing but failed tool calls (or empty replies) after
# which the run stops investigating.
MAX_CONSECUTIVE_TOOL_ERRORS = 3

# The tool that ends the loop is always offered, whatever the allowlist says.
FINISH_TOOL = "finish"


@dataclass
class AgentDeps:
    """The collaborators of one run.

    Attributes:
        config: The pipeline configuration; the seed retrieval and the tools use it.
        agent: The limits in force, after the caller's input token limit.
        llm: The generation credential.
        client: The model client; anything with ``responses.create``.
        tool_ctx: The context every tool call is made with.
        registry: The tools.
        brief: Facts about the repository, for the prompts.
        budget: The run's shared limits.
        emit: Where events go.
        steps: Where steps go.
        decider: Makes the gate's decision; ``None`` runs without decisions.
        verifier: Checks citations after the answer; ``None`` skips the check.
        screen: Inspects tool results; ``None`` passes them through.
        system_prompt: The agent's system prompt.
    """

    config: PipelineConfig
    agent: AgentConfig
    llm: LLMConfig
    client: Any
    tool_ctx: ToolContext
    registry: ToolRegistry
    brief: RepoBrief
    budget: RunBudget
    emit: Emit
    steps: StepRecorder
    system_prompt: str
    decider: Decider | None = None
    verifier: Verifier | None = None
    screen: ResultScreen | None = None
    _tools: list[dict[str, Any]] = field(default_factory=list, init=False)
    _allowed: frozenset[str] = field(default_factory=frozenset, init=False)
    _next_step: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        names = list(self.agent.tools) if self.agent.tools is not None else None
        if names is not None and FINISH_TOOL not in names:
            names.append(FINISH_TOOL)
        self._tools = self.registry.function_tools(names, strict=self.llm.supports_strict_tools)
        self._allowed = frozenset(tool["name"] for tool in self._tools)

    @property
    def tools(self) -> list[dict[str, Any]]:
        """The function tool definitions offered to the model."""
        return self._tools

    @property
    def tool_names(self) -> list[str]:
        """The names of the tools offered, in registration order."""
        return [tool["name"] for tool in self._tools]

    def allows(self, tool: str) -> bool:
        """Whether the model may call this tool in this run."""
        return tool in self._allowed

    def next_step(self) -> int:
        """Reserves the next step index."""
        index = self._next_step
        self._next_step += 1
        return index

    async def event(self, name: str, payload: dict[str, Any]) -> None:
        """Emits an event, absorbing a failing listener."""
        await safe_emit(self.emit, name, payload)

    async def record(
        self,
        kind: StepKind,
        node: str,
        payload: dict[str, Any],
        *,
        index: int | None = None,
        started: float | None = None,
    ) -> int:
        """Writes one step and returns its index.

        Args:
            kind: What kind of step it is.
            node: The node it ran in.
            payload: The details.
            index: A previously reserved index; a new one is taken when omitted.
            started: ``time.perf_counter()`` at the start, for the duration.
        """
        step = self.next_step() if index is None else index
        duration = round((time.perf_counter() - started) * 1000, 2) if started is not None else 0.0
        await self.steps.record(
            StepRecord(index=step, kind=kind, node=node, payload=payload, duration_ms=duration)
        )
        return step

    def decision_sink(self, node: str) -> Callable[[DecisionRecord], Awaitable[None]]:
        """A sink that writes decision records into the step log."""

        async def sink(record: DecisionRecord) -> None:
            await self.record("decision", node, record.to_dict())

        return sink
