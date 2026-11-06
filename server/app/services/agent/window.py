"""Keeping each model call inside the context window.

Every call resends the whole conversation, so it grows by every tool result the
agent reads. Before a call, :func:`estimate_tokens` predicts its size from the
size of the conversation, calibrated by what the provider reported for the last
call. When the prediction nears the window, :func:`compact` replaces the outputs
of older tool calls with short stubs naming what they contained.

Nothing is lost by compacting. Every citable block a tool returned is already in
the run's evidence, which the synthesis and the citation checks read; the stub
tells the model which keys it holds, and the model can call the tool again to
see the text. Each tool call keeps its output item, only shortened, because the
Responses API rejects a call without one.

Providers report usage only after a call, so the estimate is all there is to go
on beforehand. When it is wrong and the provider refuses the call as too long,
:func:`is_context_overflow` recognises the refusal so the caller can compact
harder and retry.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import APIStatusError

from app.services.agent.errors import ProviderStreamError
from app.services.agent.prompts import COMPACTED_MARKER, compacted_output

# Characters per token for text with no calibration yet. Code and JSON run a
# little denser than prose, so this errs towards overestimating.
CHARS_PER_TOKEN = 3.5

# Tool outputs shorter than this are left alone: the stub would save nothing.
MIN_COMPACTED_CHARS = 600

_KEY = re.compile(r'<source key="([^"]*)"')

_OVERFLOW = re.compile(
    r"context[ _-]?(length|window)|maximum context|too many (input )?tokens|"
    r"prompt is too long|input is too long|exceeds? the (model'?s? )?(maximum|limit)",
    re.IGNORECASE,
)


def conversation_chars(items: list[dict[str, Any]]) -> int:
    """The size of the conversation as it is serialised for the request."""
    return sum(len(json.dumps(item, ensure_ascii=False, default=str)) for item in items)


def estimate_tokens(chars: int, *, last_tokens: int, last_chars: int) -> int:
    """The predicted input tokens of a call carrying ``chars`` characters.

    The last call's reported tokens per character calibrate the guess once a
    call has been made. The ratio also absorbs what the request carries besides
    the conversation, such as the tool definitions.

    Args:
        chars: The size of the conversation about to be sent.
        last_tokens: Input tokens the provider reported for the last call.
        last_chars: The size of the conversation that call carried.
    """
    if last_tokens > 0 and last_chars > 0:
        return round(chars * last_tokens / last_chars)
    return round(chars / CHARS_PER_TOKEN)


def _turn_starts(items: list[dict[str, Any]]) -> list[int]:
    """The index of the first output item of each run of tool outputs, oldest first."""
    starts: list[int] = []
    previous_was_output = False
    for index, item in enumerate(items):
        is_output = item.get("type") == "function_call_output"
        if is_output and not previous_was_output:
            starts.append(index)
        previous_was_output = is_output
    return starts


def compact(
    items: list[dict[str, Any]], *, keep_recent_turns: int
) -> tuple[list[dict[str, Any]], int]:
    """The conversation with older tool outputs replaced by stubs.

    The outputs of the last ``keep_recent_turns`` tool-calling turns, every
    message and every model output item are kept as they are. A stub names the
    call and lists the citation keys its output held. Outputs that are already
    stubs, or too short to be worth it, are left alone.

    Args:
        items: The conversation.
        keep_recent_turns: Tool-calling turns at the end to leave whole.

    Returns:
        The new conversation, and how many outputs were replaced.
    """
    starts = _turn_starts(items)
    older = len(starts) - max(keep_recent_turns, 0)
    if older <= 0:
        return list(items), 0
    boundary = starts[older] if older < len(starts) else len(items)

    calls = {item.get("call_id"): item for item in items if item.get("type") == "function_call"}
    compacted: list[dict[str, Any]] = []
    replaced = 0
    for index, item in enumerate(items):
        output = item.get("output")
        if (
            index >= boundary
            or item.get("type") != "function_call_output"
            or not isinstance(output, str)
            or len(output) < MIN_COMPACTED_CHARS
            or output.startswith(COMPACTED_MARKER)
        ):
            compacted.append(item)
            continue
        call = calls.get(item.get("call_id"), {})
        keys = list(dict.fromkeys(_KEY.findall(output)))
        stub = compacted_output(
            str(call.get("name") or "tool"), str(call.get("arguments") or ""), keys
        )
        compacted.append({**item, "output": stub})
        replaced += 1
    return compacted, replaced


def is_context_overflow(error: BaseException) -> bool:
    """Whether a provider refused a call because its input was too long."""
    if isinstance(error, APIStatusError):
        if error.status_code == 413:
            return True
        code = getattr(error, "code", None)
        if code == "context_length_exceeded":
            return True
        return error.status_code == 400 and bool(_OVERFLOW.search(str(error)))
    if isinstance(error, ProviderStreamError):
        return bool(_OVERFLOW.search(str(error)))
    return False
