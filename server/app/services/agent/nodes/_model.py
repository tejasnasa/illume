"""One streamed Responses API call, shared by the agent and synthesize nodes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.agent.errors import ProviderStreamError

TextSink = Callable[[str], Awaitable[None]]

_TERMINAL = frozenset({"response.completed", "response.incomplete"})

# Providers stream reasoning under one of these, depending on whether they
# expose the raw chain of thought or a summary of it.
_REASONING_DELTAS = frozenset(
    {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"}
)


def output_item(item: Any) -> dict[str, Any]:
    """One output item as a plain dict, ready to be sent back as input.

    The item is kept as the provider returned it, reasoning items included, so
    the next round's input carries them unchanged.
    """
    if isinstance(item, dict):
        return dict(item)
    return item.model_dump(mode="json", exclude_none=True)


def message_text(items: list[dict[str, Any]]) -> str:
    """The text of the assistant messages among output items."""
    parts: list[str] = []
    for item in items:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                parts.append(content.get("text") or "")
    return "".join(parts)


async def stream_response(
    client: Any,
    on_text: TextSink | None = None,
    *,
    on_reasoning: TextSink | None = None,
    **request: Any,
) -> Any:
    """Calls ``client.responses.create`` with streaming and returns the final response.

    Text deltas are passed to ``on_text`` as they arrive, and reasoning deltas,
    from providers that stream them, to ``on_reasoning``, so a listener can show
    the model thinking. The response returned is the provider's own final
    object, whose ``output`` and ``usage`` are the source of truth.

    Raises:
        ProviderStreamError: When the provider reports a failure in the stream
            or the stream ends without a final response.
    """
    stream = await client.responses.create(**request, stream=True)
    final: Any = None
    async for event in stream:
        kind = getattr(event, "type", None)
        if kind == "response.output_text.delta":
            delta = getattr(event, "delta", "") or ""
            if delta and on_text is not None:
                await on_text(delta)
        elif kind in _REASONING_DELTAS:
            delta = getattr(event, "delta", "") or ""
            if delta and on_reasoning is not None:
                await on_reasoning(delta)
        elif kind in _TERMINAL:
            final = event.response
        elif kind == "response.failed":
            error = getattr(event.response, "error", None)
            raise ProviderStreamError(getattr(error, "message", None) or "the response failed")
        elif kind == "error":
            raise ProviderStreamError(getattr(event, "message", None) or "the stream failed")
    if final is None:
        raise ProviderStreamError("the stream ended without a final response")
    return final


def usage_of(response: Any) -> tuple[int, int]:
    """The input and output tokens a response reports, zero when it reports none."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
