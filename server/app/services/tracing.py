"""Opt-in LangSmith tracing for the chat request path.

Tracing is enabled only when ``LANGSMITH_TRACING`` is ``true`` and
``LANGSMITH_API_KEY`` is non-empty. Both are read from ``os.environ`` on every
call rather than from ``Settings``, so an environment without them runs exactly
as it did before and nothing here is ever required. Production sets
``LANGSMITH_HIDE_INPUTS`` and ``LANGSMITH_HIDE_OUTPUTS``, which the LangSmith
client applies to every run it uploads.

Only the chat path imports this module: ingestion, sync and every other model
caller keep their clients unwrapped.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


RunType = Literal["tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"]
_WRAPPED_MARK = "_illume_traced"


def tracing_enabled() -> bool:
    """Whether chat tracing is on: ``LANGSMITH_TRACING=true`` and a non-empty API key."""
    if os.environ.get("LANGSMITH_TRACING", "").strip().lower() != "true":
        return False
    return bool(os.environ.get("LANGSMITH_API_KEY", "").strip())


def wrap_client[C](client: C) -> C:
    """Returns ``client`` traced by LangSmith when tracing is enabled, else unchanged.

    Wrapping patches the client in place, so the object returned is the one
    passed in; a client already wrapped is not wrapped twice.
    """
    if not tracing_enabled() or getattr(client, _WRAPPED_MARK, False):
        return client
    from langsmith.wrappers import wrap_openai

    wrapped = wrap_openai(client)  # type: ignore[type-var]
    try:
        setattr(wrapped, _WRAPPED_MARK, True)
    except AttributeError:
        pass
    return wrapped


def _drop(_payload: dict[str, Any]) -> dict[str, Any]:
    return {}


def traced(name: str, *, run_type: RunType = "chain") -> Callable[[F], F]:
    """Decorates an async function so each call is a LangSmith run when tracing is on.

    The run records no inputs or outputs of its own: the arguments carry the
    user's question, chat history and credentials, so only metadata set through
    :func:`add_trace_metadata` is attached. When tracing is disabled the call is
    forwarded to the function untouched.
    """

    def decorator(fn: F) -> F:
        cached: Callable[..., Awaitable[Any]] | None = None

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal cached
            if not tracing_enabled():
                return await fn(*args, **kwargs)
            if cached is None:
                from langsmith import traceable

                cached = traceable(
                    name=name,
                    run_type=run_type,
                    process_inputs=_drop,
                    process_outputs=_drop,
                )(fn)
            return await cached(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def add_trace_metadata(**metadata: Any) -> None:
    """Attaches metadata to the current run; a no-op when tracing is off or no run is open.

    Callers must pass identifiers, counts and flags only, never user text.
    """
    if not tracing_enabled():
        return
    from langsmith.run_helpers import get_current_run_tree

    run = get_current_run_tree()
    if run is not None:
        run.add_metadata(metadata)
