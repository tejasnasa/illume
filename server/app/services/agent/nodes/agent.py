"""The agent node: one model turn.

The model is called with the whole conversation so far and the tool list. What
it returns is appended to the conversation unchanged, reasoning items included,
because some providers lose the chain of thought between tool calls without
them. The node does not run the tools; it records what was asked for.

Before the call the node checks that the conversation fits the context window,
compacting older tool results when it nears the limit. When even the compacted
conversation does not fit, or the provider refuses the call as too long after
one harder compaction, the turn ends the investigation and the run answers from
the evidence it has.
"""

from __future__ import annotations

import time
from typing import Any

from app.services.agent.budgets import BudgetLimit
from app.services.agent.deps import (
    AGENT_MAX_OUTPUT_TOKENS,
    MAX_CONSECUTIVE_TOOL_ERRORS,
    AgentDeps,
)
from app.services.agent.events import Event
from app.services.agent.nodes._model import (
    message_text,
    output_item,
    stream_response,
    usage_of,
)
from app.services.agent.prompts import NO_TOOL_CALL_NUDGE
from app.services.agent.state import AgentState, ReplaceItems, StopReason
from app.services.agent.window import (
    compact,
    conversation_chars,
    estimate_tokens,
    is_context_overflow,
)

EMPTY_REPLY_NUDGE = "Your reply was empty. Call a tool to look at the repository, or call finish."

# After the provider refuses a call as too long, this many recent turns stay whole.
OVERFLOW_KEEP_RECENT_TURNS = 1


async def limit_reached(deps: AgentDeps, state: AgentState) -> StopReason | None:
    """The stop reason of a limit the run has reached, or ``None``.

    Model turns are counted in the state, the rest by the shared budget. Reaching
    a limit announces it once with a ``degraded`` event.
    """
    if state["iteration"] >= deps.agent.max_iterations:
        await deps.budget.note_reached(
            BudgetLimit.ITERATIONS, state["iteration"], deps.agent.max_iterations
        )
        return StopReason.MAX_ITERATIONS
    reached = await deps.budget.exceeded()
    return StopReason(reached) if reached is not None else None


class _Conversation:
    """The conversation one turn sends, and whether compaction rewrote it."""

    def __init__(self, state: AgentState) -> None:
        self.items = state["items"]
        self.replaced = False
        self.compactions = state["compactions"]
        self.chars = conversation_chars(self.items)
        self._last_tokens = state["last_input_tokens"]
        self._last_chars = state["last_input_chars"]

    @property
    def estimate(self) -> int:
        """The predicted input tokens of sending it now."""
        return estimate_tokens(
            self.chars, last_tokens=self._last_tokens, last_chars=self._last_chars
        )

    async def compact(self, deps: AgentDeps, *, keep_recent_turns: int, trigger: str) -> int:
        """Compacts older tool results and reports it; returns how many were replaced."""
        before = self.estimate
        items, replaced = compact(self.items, keep_recent_turns=keep_recent_turns)
        if not replaced:
            return 0
        self.items, self.replaced = items, True
        self.compactions += 1
        self.chars = conversation_chars(items)
        payload = {
            "trigger": trigger,
            "replaced": replaced,
            "estimated_tokens_before": before,
            "estimated_tokens_after": self.estimate,
            "context_window": deps.agent.context_window,
        }
        await deps.record("compact", "agent", payload)
        await deps.event(Event.COMPACTED, payload)
        return replaced

    def update(self, appended: list[dict[str, Any]]) -> list[dict[str, Any]] | ReplaceItems:
        """The ``items`` update: the new items, or the whole rewritten conversation."""
        return ReplaceItems([*self.items, *appended]) if self.replaced else appended

    def counters(self) -> dict[str, Any]:
        return {"compactions": self.compactions}


async def _context_full(deps: AgentDeps, conversation: _Conversation) -> dict[str, Any]:
    """The update that ends the investigation because the context window is full."""
    await deps.event(
        Event.DEGRADED,
        {
            "stage": "context",
            "limit": "context_window",
            "used": conversation.estimate,
            "allowed": deps.agent.context_window,
        },
    )
    return {
        "items": conversation.update([]),
        **conversation.counters(),
        "stop_reason": StopReason.CONTEXT_WINDOW,
        "turn_end": "limit",
    }


def make_agent_node(deps: AgentDeps):
    """Builds the agent node."""
    window = deps.agent.context_window

    async def call_model(state: AgentState, items: list[dict[str, Any]]) -> Any:
        async def thinking(text: str) -> None:
            await deps.event(Event.THINKING, {"iteration": state["iteration"], "text": text})

        return await stream_response(
            deps.client,
            thinking,
            model=deps.llm.model,
            input=items,
            tools=deps.tools,
            tool_choice="auto",
            parallel_tool_calls=True,
            max_output_tokens=AGENT_MAX_OUTPUT_TOKENS,
            **deps.llm.response_kwargs(deps.agent.effort),
        )

    async def agent(state: AgentState) -> dict[str, Any]:
        stopped = await limit_reached(deps, state)
        if stopped is not None:
            return {"stop_reason": stopped, "turn_end": "limit"}

        conversation = _Conversation(state)
        if conversation.estimate >= window * deps.agent.compact_at:
            await conversation.compact(
                deps, keep_recent_turns=deps.agent.keep_recent_turns, trigger="threshold"
            )
        if conversation.estimate > window:
            return await _context_full(deps, conversation)

        step = deps.next_step()
        started = time.perf_counter()
        try:
            response = await call_model(state, conversation.items)
        except Exception as error:
            if not is_context_overflow(error):
                raise
            # The estimate was wrong, or the window is larger than the model's
            # own. Compact harder once; if that frees nothing, answer from the
            # evidence instead of failing the run.
            replaced = await conversation.compact(
                deps, keep_recent_turns=OVERFLOW_KEEP_RECENT_TURNS, trigger="provider_refused"
            )
            if not replaced:
                return await _context_full(deps, conversation)
            try:
                response = await call_model(state, conversation.items)
            except Exception as retry_error:
                if is_context_overflow(retry_error):
                    return await _context_full(deps, conversation)
                raise

        input_tokens, output_tokens = usage_of(response)
        await deps.budget.add_usage(input_tokens, output_tokens)

        output = [output_item(item) for item in response.output]
        calls = [item for item in output if item.get("type") == "function_call"]
        text = message_text(output)
        await deps.record(
            "model_call",
            "agent",
            {
                "iteration": state["iteration"],
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_input_tokens": conversation.estimate,
                "tool_calls": [call.get("name") for call in calls],
                "text": text,
                "status": getattr(response, "status", None),
            },
            index=step,
            started=started,
        )
        await deps.event(
            Event.MODEL_CALL,
            {
                "iteration": state["iteration"],
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "context_window": window,
                "tool_calls": [call.get("name") for call in calls],
            },
        )

        update: dict[str, Any] = {
            "items": conversation.update(output),
            **conversation.counters(),
            "iteration": state["iteration"] + 1,
            "pending_calls": calls,
            "gate_feedback": None,
            "last_input_tokens": input_tokens,
            "last_input_chars": conversation.chars if input_tokens else 0,
        }
        if calls:
            return {**update, "turn_end": "tools"}

        if state["evidence"] and text.strip():
            return {**update, "turn_end": "text"}

        # Nothing to answer from, or nothing said: ask again, and count it as a
        # failure so a model that keeps doing this cannot loop for ever.
        errors = state["consecutive_errors"] + 1
        nudge = NO_TOOL_CALL_NUDGE if text.strip() else EMPTY_REPLY_NUDGE
        update["items"] = conversation.update([*output, {"role": "user", "content": nudge}])
        update["consecutive_errors"] = errors
        if errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
            return {**update, "stop_reason": StopReason.TOOL_ERRORS, "turn_end": "limit"}
        return {**update, "turn_end": "nudge"}

    return agent
