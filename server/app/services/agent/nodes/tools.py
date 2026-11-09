"""The tools node: runs every function call of the last model turn.

Calls run concurrently, each on its own database session (a tool opens one from
the context for the length of the call). Nothing a call does wrong stops the
others or the run: a bad argument, an unknown tool, a timeout and a crash each
come back to the model as a tool result it can read. The node only stops the
run when three turns in a row produce nothing but failures, or when the tool
call allowance is spent. Failures are counted per turn, not per call, so a
turn of several parallel calls sharing one mistake costs one strike, not three.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.services.agent.deps import FINISH_TOOL, MAX_CONSECUTIVE_TOOL_ERRORS, AgentDeps
from app.services.agent.events import Event
from app.services.agent.prompts import SKIPPED_CALL_OUTPUT
from app.services.agent.state import (
    AgentState,
    Evidence,
    StopReason,
    extract_evidence,
    merge_evidence,
)
from app.services.agent.tools.registry import ToolResult

logger = logging.getLogger(__name__)

# How much of a call's arguments an event or step carries.
_ARGUMENT_CHARS = 2_000


def _unknown(name: str, deps: AgentDeps) -> ToolResult:
    """The result for a tool that exists nowhere, or is not offered in this run."""
    offered = ", ".join(deps.tool_names)
    return ToolResult(
        tool=name,
        status="unknown_tool",
        text=f"There is no tool named `{name}`. Available tools: {offered}.",
    )


async def _run_call(deps: AgentDeps, call: dict[str, Any], step: int) -> ToolResult:
    """Runs one call and returns its result, whatever happens inside it."""
    name = str(call.get("name") or "")
    started = time.perf_counter()
    if not deps.allows(name):
        result = _unknown(name, deps)
    else:
        result = await deps.registry.call(name, call.get("arguments"), deps.tool_ctx)
    result.elapsed_ms = result.elapsed_ms or round((time.perf_counter() - started) * 1000, 2)
    return result


# The most of a tool's output a listener is sent, for showing what it returned.
SHOWN_OUTPUT_CHARS = 4_000


def _shown_output(text: str) -> str:
    """A tool's output as the reader may see it, cut to a readable length."""
    text = text.strip()
    if len(text) <= SHOWN_OUTPUT_CHARS:
        return text
    return text[:SHOWN_OUTPUT_CHARS].rstrip() + "\n…"


def make_tools_node(deps: AgentDeps):
    """Builds the tools node."""

    async def tools(state: AgentState) -> dict[str, Any]:
        calls = state["pending_calls"]
        counted = [call for call in calls if call.get("name") != FINISH_TOOL]
        granted = await deps.budget.reserve_tool_calls(len(counted))
        allowed_ids = {call.get("call_id") for call in counted[:granted]}

        steps = [deps.next_step() for _ in calls]
        runnable: list[tuple[dict[str, Any], int]] = []
        for call, step in zip(calls, steps, strict=True):
            is_finish = call.get("name") == FINISH_TOOL
            if is_finish or call.get("call_id") in allowed_ids:
                runnable.append((call, step))
                await deps.event(
                    Event.TOOL_CALL,
                    {
                        "call_id": call.get("call_id"),
                        "tool": call.get("name"),
                        "arguments": str(call.get("arguments") or "")[:_ARGUMENT_CHARS],
                        "step": step,
                    },
                )

        results = list(
            await asyncio.gather(*(_run_call(deps, call, step) for call, step in runnable))
        )
        by_id = {
            call.get("call_id"): result for (call, _), result in zip(runnable, results, strict=True)
        }

        outputs: list[dict[str, Any]] = []
        gathered: dict[str, Evidence] = {}
        any_ok = False
        any_failed = False
        draft: str | None = None
        note: str | None = None

        for call, step in zip(calls, steps, strict=True):
            call_id = call.get("call_id")
            name = str(call.get("name") or "")
            result = by_id.get(call_id)
            arguments = str(call.get("arguments") or "")[:_ARGUMENT_CHARS]

            if result is None:
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": SKIPPED_CALL_OUTPUT,
                    }
                )
                await deps.record(
                    "tool_call",
                    "tools",
                    {"call_id": call_id, "tool": name, "arguments": arguments, "status": "skipped"},
                    index=step,
                )
                continue

            outputs.append(
                {"type": "function_call_output", "call_id": call_id, "output": result.text}
            )
            ok = result.status == "ok"
            any_ok = any_ok or ok
            any_failed = any_failed or not ok
            found: dict[str, Evidence] = {}
            if ok:
                found = extract_evidence(result.text, tool=name, step=step)
                gathered = merge_evidence(gathered, found)
            if ok and name == FINISH_TOOL and draft is None and result.data:
                draft = str(result.data.get("answer") or "") or None
                note = result.data.get("confidence_note")

            await deps.record(
                "tool_call",
                "tools",
                {
                    "call_id": call_id,
                    "tool": name,
                    "arguments": arguments,
                    "status": result.status,
                    "elapsed_ms": result.elapsed_ms,
                    "truncated": result.truncated,
                    "error_type": result.error_type,
                    "text_chars": len(result.text),
                    "text": None if ok else result.text,
                    "data": result.data,
                    "evidence_keys": list(found),
                    "nodes": result.nodes.model_dump(mode="json") if result.nodes else None,
                },
                index=step,
                started=None,
            )
            await deps.event(
                Event.TOOL_RESULT,
                {
                    "call_id": call_id,
                    "tool": name,
                    "status": result.status,
                    "elapsed_ms": result.elapsed_ms,
                    "truncated": result.truncated,
                    "error_type": result.error_type,
                    "step": step,
                    "result_count": len(found) if ok else 0,
                    "summary": (
                        f"{len(found)} citable item(s)"
                        if ok
                        else (result.text.strip().splitlines() or [""])[0][:160]
                    ),
                    "output": None if name == FINISH_TOOL else _shown_output(result.text),
                },
            )
            if result.nodes is not None:
                await deps.event(
                    Event.NODES,
                    {
                        "call_id": call_id,
                        "tool": name,
                        "paths": list(result.nodes.paths),
                        "action": result.nodes.action,
                    },
                )

        errors = state["consecutive_errors"]
        if any_ok:
            errors = 0
        elif any_failed:
            errors += 1

        new_keys = [key for key in gathered if key not in state["evidence"]]
        if new_keys:
            await deps.event(Event.EVIDENCE, {"keys": new_keys})

        update: dict[str, Any] = {
            "items": outputs,
            "evidence": gathered,
            "consecutive_errors": errors,
            "pending_calls": [],
        }
        if draft is not None:
            return {**update, "draft": draft, "confidence_note": note, "turn_end": "finish"}
        if errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
            return {**update, "stop_reason": StopReason.TOOL_ERRORS, "turn_end": "limit"}
        return {**update, "turn_end": "tools"}

    return tools
