"""Retrieval channels: independent ways of finding candidates for a question."""

from __future__ import annotations

from app.services.retrieval.channels.base import Channel, ExpansionChannel, RetrievalContext
from app.services.retrieval.channels.cochange import CochangeExpansion
from app.services.retrieval.channels.dense import DenseSearch
from app.services.retrieval.channels.graph import GraphExpansion
from app.services.retrieval.channels.grep import GrepSearch
from app.services.retrieval.channels.history import HistorySearch
from app.services.retrieval.channels.lexical import LexicalSearch
from app.services.retrieval.channels.symbol import SymbolSearch

_CHANNELS: dict[str, Channel] = {
    channel.kind: channel
    for channel in (
        DenseSearch(),
        LexicalSearch(),
        SymbolSearch(),
        GrepSearch(),
        HistorySearch(),
    )
}

# Graph and co-change expand the files other channels found rather than searching
# on their own, so they have their own registry and their own entry point.
_EXPANSIONS: dict[str, ExpansionChannel] = {
    channel.kind: channel for channel in (GraphExpansion(), CochangeExpansion())
}


def get_channel(kind: str) -> Channel:
    """The channel that searches for ``kind``.

    Raises:
        KeyError: When no channel is registered for that kind.
    """
    try:
        return _CHANNELS[kind]
    except KeyError:
        known = ", ".join(sorted(_CHANNELS))
        raise KeyError(f"no channel registered for {kind!r}; registered: {known}") from None


def get_expansion_channel(kind: str) -> ExpansionChannel:
    """The channel that expands seed files for ``kind``.

    Raises:
        KeyError: When no expansion channel is registered for that kind.
    """
    try:
        return _EXPANSIONS[kind]
    except KeyError:
        known = ", ".join(sorted(_EXPANSIONS))
        raise KeyError(
            f"no expansion channel registered for {kind!r}; registered: {known}"
        ) from None


__all__ = [
    "Channel",
    "ExpansionChannel",
    "RetrievalContext",
    "get_channel",
    "get_expansion_channel",
]
