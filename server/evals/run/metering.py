"""Metering every model call a generation makes, without touching product code.

The product's own counts cannot produce cost numbers: a single-shot answer carries no usage at
all, an agent run's counter leaves out query rewrites, HyDE, embeddings and rerankers made inside
tools, and cached tokens are lost. So the harness meters each call itself.

Three mechanisms cover the call paths:

* :func:`metered_client_factory` builds a client whose ``responses.create`` and
  ``embeddings.create`` record usage. It is handed to the product wherever the product accepts a
  ``client_factory`` (the single-shot answerer and the agent).
* :func:`patched_direct_clients` replaces the ``AsyncOpenAI`` name in the modules that build their
  own client (query rewriting, the query embedder, the LLM decider and the LLM reranker) for the
  length of a block. Which meter a call is attributed to is read from a context variable, so two
  generations running concurrently in different tasks never share one another's usage.
* :func:`metered_rerankers` wraps the Cohere and Jev rerankers, whose cost is reported on each
  provider call rather than as tokens. Inside an agent run these run in ``search_code`` and in the
  seed retrieval, where nothing else surfaces their cost.

Cost reported by the retrieval trace and by decision records is converted by
:func:`costs_from_trace` and :func:`costs_from_decision`.
"""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlparse

from openai import AsyncOpenAI

from evals.run.records import Usage

ClientFactory = Callable[..., Any]

_TERMINAL_EVENTS = frozenset({"response.completed", "response.incomplete"})

_KIND_BY_FORMAT = {
    "hypothetical_snippet": "hyde",
    "query_rewrites": "rewrite",
    "standalone_question": "rewrite",
}


class Meter:
    """Collects :class:`Usage` entries from any task or thread.

    A meter made with :meth:`scope` forwards everything it records to its parent, so one
    generation's usage can be read on its own while the run-wide meter still sees all of it.

    Args:
        parent: The meter that also receives every record.
    """

    def __init__(self, parent: Meter | None = None) -> None:
        self._parent = parent
        self._lock = threading.Lock()
        self._usages: list[Usage] = []
        self._unmetered: list[str] = []

    def record(self, usage: Usage) -> None:
        """Adds one usage entry."""
        with self._lock:
            self._usages.append(usage)
        if self._parent is not None:
            self._parent.record(usage)

    def extend(self, usages: Sequence[Usage]) -> None:
        """Adds several usage entries."""
        for usage in usages:
            self.record(usage)

    def note_unmetered(self, path: str) -> None:
        """Records that a call path produced no usage the meter could read."""
        with self._lock:
            self._unmetered.append(path)
        if self._parent is not None:
            self._parent.note_unmetered(path)

    def scope(self) -> Meter:
        """A child meter whose records also reach this one."""
        return Meter(parent=self)

    @property
    def usages(self) -> list[Usage]:
        """A copy of the entries recorded so far."""
        with self._lock:
            return list(self._usages)

    @property
    def unmetered(self) -> list[str]:
        """The distinct unmeterable paths noted so far, sorted."""
        with self._lock:
            return sorted(set(self._unmetered))

    def total_cost(self) -> float:
        """The sum of the costs providers reported; calls that reported none add nothing."""
        return sum(usage.reported_cost_usd or 0.0 for usage in self.usages)


_ACTIVE: ContextVar[Meter | None] = ContextVar("eval_active_meter", default=None)


# --- reading usage out of responses ------------------------------------------


def _number(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _provider(kwargs: Mapping[str, Any]) -> str:
    base_url = kwargs.get("base_url")
    if not base_url:
        return "openai"
    return urlparse(str(base_url)).hostname or str(base_url)


def usage_from_response(
    response: Any, *, kind: str, provider: str, requested_model: str, latency_ms: float
) -> Usage | None:
    """The usage a Responses or embeddings response reports, or ``None`` when it reports none.

    Reads ``input_tokens``/``output_tokens`` (Responses) or ``prompt_tokens``/``total_tokens``
    (embeddings), and cached tokens from ``input_tokens_details`` or ``prompt_tokens_details``.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = _number(getattr(usage, "input_tokens", None)) or _number(
        getattr(usage, "prompt_tokens", None)
    )
    output_tokens = _number(getattr(usage, "output_tokens", None))
    details = getattr(usage, "input_tokens_details", None) or getattr(
        usage, "prompt_tokens_details", None
    )
    reported_model = getattr(response, "model", None)
    return Usage(
        provider=provider,
        model=reported_model
        if isinstance(reported_model, str) and reported_model
        else requested_model,
        kind=kind,
        input_tokens=input_tokens,
        cached_input_tokens=_number(getattr(details, "cached_tokens", None)),
        output_tokens=output_tokens,
        reported_cost_usd=_cost(getattr(usage, "cost", None)),
        latency_ms=round(latency_ms, 2),
    )


def _is_stream(result: Any) -> bool:
    return hasattr(result, "__aiter__") and not hasattr(result, "usage")


class _MeteredResponses:
    def __init__(self, inner: Any, meter: Meter, kind: str, provider: str) -> None:
        self._inner = inner
        self._meter = meter
        self._kind = kind
        self._provider = provider

    def _kind_for(self, kwargs: Mapping[str, Any]) -> str:
        if self._kind != "rewrite":
            return self._kind
        text = kwargs.get("text")
        name = ((text or {}).get("format") or {}).get("name") if isinstance(text, dict) else None
        return _KIND_BY_FORMAT.get(str(name), self._kind)

    async def create(self, **kwargs: Any) -> Any:
        kind = self._kind_for(kwargs)
        model = str(kwargs.get("model") or "")
        started = time.perf_counter()
        result = await self._inner.create(**kwargs)
        if kwargs.get("stream") or _is_stream(result):
            return self._watch(result, kind, model, started)
        self._record(result, kind, model, started)
        return result

    def _record(self, response: Any, kind: str, model: str, started: float) -> None:
        usage = usage_from_response(
            response,
            kind=kind,
            provider=self._provider,
            requested_model=model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        if usage is None:
            self._meter.note_unmetered(f"response_without_usage:{kind}")
        else:
            self._meter.record(usage)

    async def _watch(self, events: Any, kind: str, model: str, started: float):
        recorded = False
        try:
            async for event in events:
                if getattr(event, "type", None) in _TERMINAL_EVENTS:
                    final = getattr(event, "response", None)
                    if final is not None and not recorded:
                        self._record(final, kind, model, started)
                        recorded = True
                yield event
        finally:
            if not recorded:
                self._meter.note_unmetered(f"stream_without_usage:{kind}")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _MeteredEmbeddings:
    def __init__(self, inner: Any, meter: Meter, provider: str) -> None:
        self._inner = inner
        self._meter = meter
        self._provider = provider

    async def create(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        response = await self._inner.create(**kwargs)
        usage = usage_from_response(
            response,
            kind="embed",
            provider=self._provider,
            requested_model=str(kwargs.get("model") or ""),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        if usage is None:
            self._meter.note_unmetered("response_without_usage:embed")
        else:
            self._meter.record(usage)
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class MeteredClient:
    """A client whose ``responses.create`` and ``embeddings.create`` record their usage.

    Everything else is passed through to the wrapped client.
    """

    def __init__(self, inner: Any, meter: Meter, *, kind: str, provider: str) -> None:
        self._inner = inner
        responses = getattr(inner, "responses", None)
        embeddings = getattr(inner, "embeddings", None)
        self.responses = _MeteredResponses(responses, meter, kind, provider) if responses else None
        self.embeddings = _MeteredEmbeddings(embeddings, meter, provider) if embeddings else None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def metered_client_factory(
    meter: Meter | None,
    base_factory: ClientFactory = AsyncOpenAI,
    *,
    kind: str = "generate",
) -> ClientFactory:
    """A client factory whose clients record every call's usage.

    Args:
        meter: Where usage goes. ``None`` resolves the meter active in the calling context
            (see :func:`patched_direct_clients`) each time a client is built.
        base_factory: Builds the real client from ``AsyncOpenAI``-style keyword arguments.
        kind: What calls through these clients are for. ``rewrite`` splits into ``hyde`` and
            ``rewrite`` by the structured-output name of the call.

    Returns:
        A factory compatible with the product's ``ClientFactory``.
    """

    def factory(*args: Any, **kwargs: Any) -> MeteredClient:
        target = meter if meter is not None else _ACTIVE.get()
        if target is None:
            target = Meter()
        return MeteredClient(
            base_factory(*args, **kwargs), target, kind=kind, provider=_provider(kwargs)
        )

    return factory


# --- patching the paths that build their own client --------------------------

_PATCH_LOCK = threading.Lock()
_PATCH_DEPTH: dict[str, int] = {}
_PATCH_SAVED: dict[str, list[tuple[Any, str, Any]]] = {}

# module path, kind of the calls made through the client built there
_DIRECT_CLIENT_MODULES: tuple[tuple[str, str], ...] = (
    ("app.services.retrieval.query", "rewrite"),
    ("app.services.retrieval.embedding", "embed"),
    ("app.services.decisions.llm", "decision"),
    ("app.services.retrieval.rerank.llm", "rerank"),
)


@contextmanager
def _patched(name: str, install: Callable[[], list[tuple[Any, str, Any]]]) -> Iterator[None]:
    """Installs a set of attribute replacements once, however many blocks are active at once."""
    with _PATCH_LOCK:
        depth = _PATCH_DEPTH.get(name, 0)
        if depth == 0:
            _PATCH_SAVED[name] = install()
        _PATCH_DEPTH[name] = depth + 1
    try:
        yield
    finally:
        with _PATCH_LOCK:
            _PATCH_DEPTH[name] -= 1
            if _PATCH_DEPTH[name] == 0:
                for owner, attribute, original in reversed(_PATCH_SAVED.pop(name)):
                    setattr(owner, attribute, original)


_BASE: ContextVar[ClientFactory | None] = ContextVar("eval_base_factory", default=None)
_RERANK_METER: ContextVar[Meter | None] = ContextVar("eval_rerank_meter", default=None)


@contextmanager
def _activated(var: ContextVar[Any], value: Any) -> Iterator[None]:
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)


def _direct_factory(kind: str) -> ClientFactory:
    """The replacement for ``AsyncOpenAI`` in a module that builds its own client."""

    def factory(*args: Any, **kwargs: Any) -> MeteredClient:
        return metered_client_factory(None, _BASE.get() or AsyncOpenAI, kind=kind)(*args, **kwargs)

    return factory


@contextmanager
def patched_direct_clients(
    meter: Meter, base_factory: ClientFactory = AsyncOpenAI
) -> Iterator[None]:
    """Meters the call paths that construct their own ``AsyncOpenAI``.

    For the length of the block the name is replaced, in the query rewriting, query embedding,
    LLM decider and LLM reranker modules, by a factory that builds clients through
    ``base_factory`` and records their usage on ``meter``. Blocks may overlap in time (one per
    concurrent generation): the replacement is installed once and removed when the last block
    ends, and each call is attributed to the meter and base factory of the block it was made in.

    Args:
        meter: Where usage goes.
        base_factory: Builds the real client; ``AsyncOpenAI`` unless a test supplies a fake.
    """

    def install() -> list[tuple[Any, str, Any]]:
        saved: list[tuple[Any, str, Any]] = []
        for path, kind in _DIRECT_CLIENT_MODULES:
            module: Any = importlib.import_module(path)
            saved.append((module, "AsyncOpenAI", module.AsyncOpenAI))
            module.AsyncOpenAI = _direct_factory(kind)
        return saved

    with _patched("clients", install), _activated(_ACTIVE, meter), _activated(_BASE, base_factory):
        yield


# --- the rerankers --------------------------------------------------------------


def costs_from_calls(calls: Sequence[Mapping[str, Any]], *, latency_ms: float = 0.0) -> list[Usage]:
    """Usage entries for rerank provider calls, as :meth:`RerankCall.to_dict` records them.

    Calls made by the LLM reranker are skipped: they go through a client the meter already
    watches, so counting them here would count them twice.
    """
    usages = []
    for call in calls:
        if call.get("provider") == "llm":
            continue
        usages.append(
            Usage(
                provider=str(call.get("provider") or "unknown"),
                model=str(call.get("model") or ""),
                kind="rerank",
                reported_cost_usd=_cost(call.get("cost")),
                latency_ms=round(latency_ms, 2),
            )
        )
    return usages


def costs_from_trace(trace: Any) -> list[Usage]:
    """Rerank usage from a :class:`~app.services.retrieval.pipeline.RetrievalTrace`."""
    return costs_from_calls(trace.rerank_calls)


def costs_from_decision(record: Mapping[str, Any], *, kind: str = "decision") -> Usage:
    """One usage entry for a decision record, as :meth:`DecisionRecord.to_dict` records it."""
    return Usage(
        provider=str(record.get("provider") or "unknown"),
        model=str(record.get("model") or ""),
        kind=kind,
        input_tokens=_number(record.get("tokens_in")),
        output_tokens=_number(record.get("tokens_out")),
        reported_cost_usd=_cost(record.get("cost")),
        latency_ms=float(record.get("latency_ms") or 0.0),
    )


def costs_from_decisions(records: Sequence[Mapping[str, Any]]) -> list[Usage]:
    """Usage entries for decision records, counting each batched request's cost once.

    Decisions answered by one request share its id and its cost, so only the first record of a
    request id carries the cost; the rest are recorded with none.
    """
    seen: set[str] = set()
    usages = []
    for record in records:
        usage = costs_from_decision(record)
        request_id = record.get("request_id")
        if request_id:
            if request_id in seen:
                usage = usage.model_copy(
                    update={"reported_cost_usd": None, "input_tokens": 0, "output_tokens": 0}
                )
            seen.add(str(request_id))
        usages.append(usage)
    return usages


def _rerank_classes() -> list[Any]:
    from app.services.retrieval.rerank.cohere import CohereReranker
    from app.services.retrieval.rerank.jev import JevReranker

    return [CohereReranker, JevReranker]


@contextmanager
def metered_rerankers(meter: Meter) -> Iterator[None]:
    """Records the provider calls of the Cohere and Jev rerankers on ``meter``.

    Inside an agent run these rerankers run in the seed retrieval and in every ``search_code``
    call, and the run's steps carry no cost for them. The calls are read from the reranker's own
    ``calls`` list once each ``rerank`` finishes, whether it succeeded or failed.

    Overlapping blocks share one installation, as in :func:`patched_direct_clients`.
    """

    def install() -> list[tuple[Any, str, Any]]:
        saved: list[tuple[Any, str, Any]] = []
        for cls in _rerank_classes():
            original = cls.rerank
            saved.append((cls, "rerank", original))
            cls.rerank = _recording(original)
        return saved

    with _patched("rerankers", install), _activated(_RERANK_METER, meter):
        yield


def _recording(original: Callable[..., Any]) -> Callable[..., Any]:
    async def rerank(self: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return await original(self, *args, **kwargs)
        finally:
            target = _RERANK_METER.get()
            calls = [call.to_dict() for call in getattr(self, "calls", ())]
            if target is not None and calls:
                elapsed = (time.perf_counter() - started) * 1000
                target.extend(costs_from_calls(calls, latency_ms=elapsed / len(calls)))

    return rerank


__all__ = [
    "MeteredClient",
    "Meter",
    "costs_from_calls",
    "costs_from_decision",
    "costs_from_decisions",
    "costs_from_trace",
    "metered_client_factory",
    "metered_rerankers",
    "patched_direct_clients",
    "usage_from_response",
]
