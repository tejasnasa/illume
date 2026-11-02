"""Rendering retrieved candidates into the context block of a prompt.

Each candidate becomes a fenced ``<source>`` block carrying its citation key, so
the model can cite by writing the key and the answer can be matched back to the
evidence. Repository text is untrusted: a file or commit message can contain
anything, including a literal ``</source>`` followed by instructions. Every
occurrence of the fence in the text is therefore escaped before it is placed
inside a block, so the only fences in the context are the ones rendered here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.retrieval.candidate import Candidate

# The ``type`` attribute for each source type.
SOURCE_LABELS: dict[str, str] = {
    "symbol": "code",
    "file": "file",
    "commit": "commit",
    "pull_request": "pull_request",
    "document": "readme",
}

_FENCE = re.compile(r"<(/?)source", re.IGNORECASE)


@dataclass(frozen=True)
class AssembledContext:
    """The context for one prompt.

    Attributes:
        text: The rendered blocks, separated by blank lines. Empty when there
            are no candidates.
        by_key: Each rendered candidate by its citation key. When two candidates
            share a key, the first (better ranked) one is kept.
    """

    text: str
    by_key: dict[str, Candidate]


def escape_fence(text: str) -> str:
    """Makes ``<source`` and ``</source`` in ``text`` harmless inside a block.

    A backslash is inserted after the ``<``, so ``</source>`` reads ``<\\/source>``.
    The match is case-insensitive, since a tolerant parser would accept
    ``</SOURCE>`` as well.
    """
    return _FENCE.sub(lambda match: f"<\\{match.group(1)}source", text)


def _attribute(value: str) -> str:
    """A value safe inside a double-quoted attribute."""
    return value.replace('"', "&quot;").replace("<", "&lt;")


def render_block(candidate: Candidate) -> str:
    """One candidate as a fenced block."""
    label = SOURCE_LABELS.get(candidate.source_type, candidate.source_type)
    return (
        f'<source key="{_attribute(candidate.key)}" type="{_attribute(label)}" '
        f'provenance="{candidate.provenance}">\n'
        f"{escape_fence(candidate.text)}\n"
        "</source>"
    )


def assemble_context(candidates: Sequence[Candidate]) -> AssembledContext:
    """Renders the candidates in order and maps their keys back to them."""
    by_key: dict[str, Candidate] = {}
    for candidate in candidates:
        by_key.setdefault(candidate.key, candidate)
    return AssembledContext(
        text="\n\n".join(render_block(candidate) for candidate in candidates),
        by_key=by_key,
    )
