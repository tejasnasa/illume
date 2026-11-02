"""Turning the question into the query variants the channels search with.

Variant 0 is always the question the channels start from: as typed, or
rewritten into a standalone question when ``condense`` is on and there is a
conversation to resolve. ``multi_query`` and ``hyde`` append further variants.

Every model call here is an optimisation of recall, never a requirement, so no
failure escapes: a provider error, a timeout, malformed JSON or a provider that
ignores ``json_schema`` falls back to the plain question, logs, and emits one
``degraded`` event naming the transform.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Protocol, cast

from openai import AsyncOpenAI

from app.services.llm_config import LLMConfig
from app.services.retrieval.candidate import QueryVariant
from app.services.retrieval.channels.base import Emit
from app.services.retrieval.config import QueryConfig
from app.services.retrieval.llm_json import ModelFailure, call_json

logger = logging.getLogger(__name__)

# A rewrite longer than this is a model rambling, not a search query.
MAX_VARIANT_CHARS = 2000

_CONDENSE_SYSTEM = (
    "You rewrite the final user message of a conversation about a code repository "
    "into one standalone question. Resolve pronouns and references such as 'it', "
    "'that file' or 'what about its tests' using the earlier messages, keep every "
    "file path, identifier and technical term exactly as written, and add nothing "
    "that was not asked. If the message is already standalone, return it unchanged."
)

_MULTI_QUERY_SYSTEM = (
    "You write alternative search queries for a question about a code repository, "
    "to find code that the original wording would miss. Write exactly {n} queries "
    "that differ in vocabulary: one phrased the way identifiers appear in code "
    "(snake_case or camelCase names, module names, likely function names), one in "
    "plain English, one describing the behaviour or effect rather than the names. "
    "Any further queries should vary the vocabulary again. Do not answer the question."
)

_HYDE_SYSTEM = (
    "You write a short hypothetical code snippet (at most 15 lines) that would "
    "answer the question about a code repository if it existed in the code, using "
    "plausible names for functions, classes and variables. Return only the code "
    "and brief comments; do not explain it."
)

_CONDENSE_SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}

_MULTI_QUERY_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}

_HYDE_SCHEMA = {
    "type": "object",
    "properties": {"snippet": {"type": "string"}},
    "required": ["snippet"],
    "additionalProperties": False,
}


class HistoryMessage(Protocol):
    """A prior chat message; ``role`` is ``user`` or ``assistant``.

    The attributes are read-only so that a class whose ``role`` is a narrower
    type, such as a ``Literal``, still satisfies the protocol.
    """

    @property
    def role(self) -> str: ...

    @property
    def content(self) -> str: ...


def _clean(value: Any) -> str | None:
    """A trimmed, bounded string, or ``None`` when the value is not usable text."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_VARIANT_CHARS:
        return None
    return cleaned


def _string_field(parsed: Any, *names: str) -> str:
    """The first usable string among ``names`` of a parsed object.

    Raises:
        ModelFailure: When the output is not an object or has none of the fields.
    """
    if isinstance(parsed, dict):
        for name in names:
            cleaned = _clean(parsed.get(name))
            if cleaned is not None:
                return cleaned
    raise ModelFailure(f"the model's JSON had no usable {names[0]!r} field")


def _string_list(parsed: Any, name: str) -> list[str]:
    """The usable strings of ``parsed[name]``, or of ``parsed`` itself when it is a list.

    Raises:
        ModelFailure: When there is no list or it holds no usable string.
    """
    items = parsed.get(name) if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        raise ModelFailure(f"the model's JSON had no {name!r} list")
    cleaned = [text for item in items if (text := _clean(item)) is not None]
    if not cleaned:
        raise ModelFailure(f"the model's {name!r} list had no usable entries")
    return cleaned


def _render_history(history: Sequence[HistoryMessage], limit: int) -> str:
    """The last ``limit`` messages as ``role: content`` lines."""
    return "\n".join(f"{message.role}: {message.content}" for message in history[-limit:])


async def _degrade(emit: Emit, transform: str, reason: str) -> None:
    """Logs a fallback and tells the caller which transform was lost and why."""
    logger.warning("query transform %s degraded: %s", transform, reason)
    await emit("degraded", {"stage": "query", "transform": transform, "reason": reason})


async def build_variants(
    question: str,
    history: Sequence[HistoryMessage],
    config: QueryConfig,
    *,
    llm: LLMConfig | None,
    emit: Emit,
) -> tuple[str, list[QueryVariant]]:
    """Builds the standalone question and every variant the channels search with.

    Variant 0 is the question as typed (kind ``original``), or its standalone
    rewrite (kind ``condensed``) when ``config.condense`` is set and the last
    ``config.history_messages`` messages are not empty. ``multi_query`` appends up
    to ``config.n_variants`` rewrites as kind ``multi_query`` with indices from 1,
    skipping any that repeat the standalone question or each other. ``hyde``
    appends one hypothetical snippet as kind ``hyde`` with index 1. Rewrites are
    built from the standalone question.

    A model failure of any kind leaves that transform out and emits one
    ``degraded`` event; it never raises. ``llm=None`` resolves to the server's
    free-tier credential, and when that is missing too no model is called.

    Args:
        question: The user's question as typed.
        history: Prior messages, oldest first.
        config: Which transforms run and how many rewrites they ask for.
        llm: The caller's generation credential.
        emit: Receives ``degraded`` events.

    Returns:
        The standalone question and the variants, with the first variant at index 0.
    """
    resolved = llm if llm is not None else LLMConfig.server_default()
    wants_condense = config.condense and config.history_messages > 0 and bool(history)
    wants_rewrites = config.transform != "identity"

    standalone = question
    kind: str = "original"
    client: AsyncOpenAI | None = None

    if (wants_condense or wants_rewrites) and resolved is None:
        reasons = []
        if wants_condense:
            reasons.append("condense")
        if wants_rewrites:
            reasons.append(config.transform)
        for transform in reasons:
            await _degrade(emit, transform, "no model credential is available")
        wants_condense = wants_rewrites = False

    if resolved is not None and (wants_condense or wants_rewrites):
        client = AsyncOpenAI(**resolved.client_kwargs())

    if wants_condense and client is not None and resolved is not None:
        try:
            parsed = await call_json(
                client,
                resolved,
                system=_CONDENSE_SYSTEM,
                user=(
                    f"Conversation:\n{_render_history(history, config.history_messages)}\n\n"
                    f"Final user message:\n{question}"
                ),
                format_name="standalone_question",
                schema=_CONDENSE_SCHEMA,
            )
            standalone = _string_field(parsed, "question", "standalone_question")
            kind = "condensed"
        except Exception as error:
            await _degrade(emit, "condense", _reason(error))

    variants = [QueryVariant(text=standalone, kind=cast(Any, kind), index=0)]

    if wants_rewrites and client is not None and resolved is not None:
        try:
            if config.transform == "multi_query":
                variants += await _multi_query(client, resolved, standalone, config)
            else:
                variants.append(await _hyde(client, resolved, standalone))
        except Exception as error:
            await _degrade(emit, config.transform, _reason(error))

    return standalone, variants


def _reason(error: Exception) -> str:
    """A short, loggable description of why a model call failed."""
    if isinstance(error, ModelFailure):
        return str(error)
    return f"{type(error).__name__}: {error}"[:300]


async def _multi_query(
    client: AsyncOpenAI, llm: LLMConfig, question: str, config: QueryConfig
) -> list[QueryVariant]:
    """The ``multi_query`` rewrites, indexed from 1."""
    parsed = await call_json(
        client,
        llm,
        system=_MULTI_QUERY_SYSTEM.format(n=config.n_variants),
        user=question,
        format_name="query_rewrites",
        schema=_MULTI_QUERY_SCHEMA,
    )
    seen = {question.casefold()}
    variants: list[QueryVariant] = []
    for text in _string_list(parsed, "queries"):
        if text.casefold() in seen:
            continue
        seen.add(text.casefold())
        variants.append(QueryVariant(text=text, kind="multi_query", index=len(variants) + 1))
        if len(variants) == config.n_variants:
            break
    if not variants:
        raise ModelFailure("every rewrite repeated the question")
    return variants


async def _hyde(client: AsyncOpenAI, llm: LLMConfig, question: str) -> QueryVariant:
    """The hypothetical snippet, as variant 1."""
    parsed = await call_json(
        client,
        llm,
        system=_HYDE_SYSTEM,
        user=question,
        format_name="hypothetical_snippet",
        schema=_HYDE_SCHEMA,
    )
    return QueryVariant(text=_string_field(parsed, "snippet", "code"), kind="hyde", index=1)
