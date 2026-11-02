"""Stable citation keys: one grammar for prompts, answers and evaluation gold.

A key names the thing being cited, not the position of a chunk in one prompt,
so it means the same thing across tool calls, parallel workers and runs, and it
maps one to one onto the identifiers an evaluation item is graded against.

| Kind           | Key                         | Example                                |
| -------------- | --------------------------- | -------------------------------------- |
| Code range     | ``F:<path>:<start>-<end>``  | ``F:server/app/core/security.py:48-67`` |
| Whole file     | ``F:<path>``                | ``F:server/app/main.py``               |
| Commit         | ``C:<short hash>``          | ``C:a1b2c3d4``                         |
| Pull request   | ``PR:<number>``             | ``PR:142``                             |
| README section | ``D:<document>#<slug>``     | ``D:README#installation``              |

In prose a key is written in square brackets, ``[F:app/main.py:3-9]``, and one
bracket may hold several keys separated by ``;`` or ``,``. Paths may contain
brackets themselves (Next.js route folders such as ``app/repo/[id]/page.tsx``),
so the scanner matches brackets rather than stopping at the first ``]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

KeyKind = Literal["F", "C", "PR", "D"]

# Eight hex characters: unambiguous across the few hundred commits ingestion
# keeps, and short enough to write inline.
SHORT_HASH_LENGTH = 8

_PREFIXES: tuple[str, ...] = ("PR:", "F:", "C:", "D:")
_RANGE = re.compile(r"^(?P<path>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$")
# A range with nothing before it, which would otherwise read as a file named ":1-2".
_RANGE_ONLY = re.compile(r"^:\d+(?:-\d+)?$")
_HASH = re.compile(r"^[0-9a-fA-F]{4,40}$")
_PR = re.compile(r"^#?(?P<number>\d+)$")
_DOCUMENT = re.compile(r"^(?P<document>[^#\s]+)#(?P<slug>[^\s#]+)$")
_SEPARATOR = re.compile(r"\s*[;,]\s*(?=(?:PR|F|C|D):)")


@dataclass(frozen=True)
class CitationKey:
    """A parsed key.

    Attributes:
        kind: ``F`` for code, ``C`` for a commit, ``PR`` for a pull request,
            ``D`` for a document section.
        path: The repository-relative path, for ``F`` keys.
        start: The first line of a range, for ``F`` keys that have one.
        end: The last line of that range.
        commit: The short lowercase hash, for ``C`` keys.
        pr_number: The number, for ``PR`` keys.
        document: The document name, for ``D`` keys.
        slug: The section slug, for ``D`` keys.
    """

    kind: KeyKind
    path: str | None = None
    start: int | None = None
    end: int | None = None
    commit: str | None = None
    pr_number: int | None = None
    document: str | None = None
    slug: str | None = None

    def render(self) -> str:
        """The canonical text of the key, without brackets."""
        if self.kind == "F":
            if self.start is None:
                return f"F:{self.path}"
            return f"F:{self.path}:{self.start}-{self.end}"
        if self.kind == "C":
            return f"C:{self.commit}"
        if self.kind == "PR":
            return f"PR:{self.pr_number}"
        return f"D:{self.document}#{self.slug}"

    def __str__(self) -> str:
        return self.render()


def normalize_path(path: str) -> str:
    """Puts a path in the form ingestion stores it.

    Backslashes become slashes, leading ``./`` and ``/`` go, and repeated
    slashes collapse. ``..`` is left alone: a key is matched against retrieved
    evidence, never opened, so normalising it away would only hide a bad key.
    """
    cleaned = path.strip().replace("\\", "/")
    cleaned = re.sub(r"/{2,}", "/", cleaned)
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def code_key(path: str, start: int | None = None, end: int | None = None) -> str:
    """The key for a file, or for a line range inside it.

    Raises:
        ValueError: When only one end of the range is given, or it is not a
            valid one-based range.
    """
    normalized = normalize_path(path)
    if start is None and end is None:
        return CitationKey(kind="F", path=normalized).render()
    if start is None or end is None:
        raise ValueError("a line range needs both a start and an end")
    if start < 1 or end < start:
        raise ValueError(f"invalid line range {start}-{end}")
    return CitationKey(kind="F", path=normalized, start=start, end=end).render()


def commit_key(commit_hash: str) -> str:
    """The key for a commit, from its full or short hash.

    Raises:
        ValueError: When the text is not a hexadecimal hash.
    """
    if not _HASH.match(commit_hash):
        raise ValueError(f"not a commit hash: {commit_hash!r}")
    return CitationKey(kind="C", commit=_short_hash(commit_hash)).render()


def pull_request_key(number: int) -> str:
    """The key for a pull request.

    Raises:
        ValueError: When the number is not positive.
    """
    if number < 1:
        raise ValueError(f"not a pull request number: {number}")
    return CitationKey(kind="PR", pr_number=number).render()


def slugify_heading(heading: str) -> str:
    """A heading's anchor slug, the way GitHub renders it.

    Lowercased, punctuation other than hyphens and underscores removed, and
    spaces turned into hyphens. Markdown heading markers are stripped first.
    """
    text = heading.strip().lstrip("#").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def document_key(heading: str, document: str = "README") -> str:
    """The key for one section of a document, from the section's heading."""
    return CitationKey(kind="D", document=document, slug=slugify_heading(heading) or "top").render()


def parse_key(text: str) -> CitationKey | None:
    """Parses one key, with or without surrounding brackets.

    Returns ``None`` for anything that is not a well-formed key, so callers
    can treat a malformed key as an unresolved citation rather than an error.
    """
    raw = text.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()

    if raw.startswith("PR:"):
        match = _PR.match(raw[3:].strip())
        if not match or int(match.group("number")) < 1:
            return None
        return CitationKey(kind="PR", pr_number=int(match.group("number")))

    if raw.startswith("C:"):
        value = raw[2:].strip()
        if not _HASH.match(value):
            return None
        return CitationKey(kind="C", commit=_short_hash(value))

    if raw.startswith("D:"):
        match = _DOCUMENT.match(raw[2:].strip())
        if not match:
            return None
        return CitationKey(
            kind="D", document=match.group("document"), slug=match.group("slug").lower()
        )

    if raw.startswith("F:"):
        body = raw[2:].strip()
        if not body or _RANGE_ONLY.match(body):
            return None
        match = _RANGE.match(body)
        if match:
            start = int(match.group("start"))
            end = int(match.group("end") or start)
            path = normalize_path(match.group("path"))
            if not path or start < 1 or end < start:
                return None
            return CitationKey(kind="F", path=path, start=start, end=end)
        path = normalize_path(body)
        return CitationKey(kind="F", path=path) if path else None

    return None


def find_keys(prose: str) -> list[tuple[str, CitationKey | None]]:
    """Every bracketed key in a piece of prose, in order of appearance.

    Returns:
        ``(raw, parsed)`` pairs. ``raw`` is the text exactly as written, so a
        malformed key is still reported, with ``parsed`` set to ``None``.
        Brackets that do not start with a key prefix, such as markdown links
        or ordinary asides, are skipped.
    """
    found: list[tuple[str, CitationKey | None]] = []
    position = 0
    while True:
        opening = prose.find("[", position)
        if opening == -1:
            return found
        inner_start = opening + 1
        if not prose.startswith(_PREFIXES, inner_start):
            position = inner_start
            continue

        closing = _matching_bracket(prose, opening)
        if closing is None:
            return found

        inner = prose[inner_start:closing]
        for part in _SEPARATOR.split(inner):
            part = part.strip()
            if part:
                found.append((part, parse_key(part)))
        position = closing + 1


def _matching_bracket(text: str, opening: int) -> int | None:
    """The index of the ``]`` closing the ``[`` at ``opening``, nesting included.

    A newline ends the search: a key never spans lines, and stopping there
    keeps one stray bracket from swallowing the rest of an answer.
    """
    depth = 0
    for index in range(opening, len(text)):
        character = text[index]
        if character == "\n":
            return None
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def _short_hash(commit_hash: str) -> str:
    return commit_hash.lower()[:SHORT_HASH_LENGTH]
