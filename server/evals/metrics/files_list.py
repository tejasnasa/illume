"""Parsing the ``Files:`` list an answer ends with.

Every arm is asked to finish with the same list, so it is read the same way for every arm. The
parser is deliberately forgiving about presentation (bullets, backticks, links, line ranges,
Windows separators) and strict about structure: the last ``Files:`` heading is the list, and
an answer without one is a format failure, not an empty answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from evals.mining.paths import normalise_path

_HEADING = re.compile(
    r"^\s*(?:>\s*)?(?:#{1,6}\s*)?(?:[*_]{1,3}\s*)?Files\s*(?:[*_]{1,3})?\s*:\s*(?:[*_]{1,3})?"
    r"\s*(?P<rest>.*?)\s*$",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+(?P<body>.*?)\s*$")
_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)]*)\)")
_BACKTICKED = re.compile(r"`(?P<code>[^`]+)`")
_LINE_SUFFIX = re.compile(r":\d+(?:\s*[-–—]\s*\d+)?(?::\d+)?$")
_PATHISH = re.compile(r"[/\\]|\.\w")
_LINES_PHRASE = re.compile(r"^lines?\s+\d", re.IGNORECASE)
_NOT_PATHS = frozenset({"none", "n/a", "na", "-", "—", "nothing"})
_STRIP = "`*_<>\"'"
_OPENERS = {"(": ")", "[": "]", "`": "`"}


@dataclass(frozen=True)
class FilesList:
    """The result of reading an answer's ``Files:`` list.

    Attributes:
        paths: Normalised repo-relative paths, in order of first appearance, without
            duplicates.
        found: Whether the answer has a ``Files:`` heading at all. ``False`` is a format
            failure; ``True`` with no paths is an answer that listed nothing.
    """

    paths: tuple[str, ...]
    found: bool


def _split_items(text: str) -> list[str]:
    """Split on commas and semicolons that sit outside backticks, brackets and parentheses."""
    items: list[str] = []
    current: list[str] = []
    closers: list[str] = []
    for char in text:
        if closers and char == closers[-1]:
            closers.pop()
        elif char in _OPENERS:
            closers.append(_OPENERS[char])
        if not closers and char in ",;":
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


def _clean(token: str) -> str:
    token = token.strip().strip(_STRIP).strip()
    token = token.rstrip(".,;:").strip(_STRIP)
    token = token.split("#", 1)[0]
    token = _LINE_SUFFIX.sub("", token)
    return token.rstrip(".,;:").strip(_STRIP).strip()


def _first_token(text: str) -> str:
    parts = text.split()
    return parts[0] if parts else ""


def parse_item(text: str) -> str | None:
    """Read one list item as a path.

    Handles markdown links (the target, or the link text when the target is a URL), a
    backticked path, a bare path followed by a description, ``:10-20`` and ``#L10-L20``
    suffixes, ``(lines 3-9)`` notes, Windows separators and ``./`` prefixes.

    Args:
        text: One item, with its bullet already removed.

    Returns:
        The normalised path, or ``None`` when the item holds no path (empty, ``none``,
        ``n/a``, a bare ``lines 10-20`` note or a URL).
    """
    body = text.strip().strip("*_").strip()
    if not body or _LINES_PHRASE.match(body):
        return None
    link = _LINK.search(body)
    if link:
        target = _first_token(link.group("target").strip().strip("<>"))
        candidate = link.group("text") if (not target or "://" in target) else target
    else:
        code = _BACKTICKED.search(body)
        candidate = code.group("code") if code else body
    candidate = _clean(_first_token(candidate.strip().strip(_STRIP)))
    if not candidate or candidate.lower() in _NOT_PATHS or "://" in candidate:
        return None
    path = normalise_path(candidate, strip_diff_prefix=False)
    return path or None


def _looks_like_paths(line: str) -> bool:
    """Whether an unbulleted line reads as a path rather than prose."""
    first = _clean(_first_token(line.strip().strip("*_").strip()))
    link = _LINK.search(line)
    if link:
        first = _clean(_first_token(link.group("text")))
    code = _BACKTICKED.search(line)
    if code:
        first = _clean(_first_token(code.group("code")))
    return bool(first) and bool(_PATHISH.search(first))


def parse_files_list(answer: str) -> FilesList:
    """Find the last ``Files:`` heading in an answer and read the paths after it.

    The heading is a line that begins (after optional ``>``, ``#`` marks or bold markers)
    with ``Files`` and a colon, in any case. Items may follow on the heading line,
    comma-separated, and on the lines below as bullets (``-``, ``*``, a bullet dot, ``1.``
    or ``1)``). Directly after the heading or an item, an unbulleted line is read as more
    items when its first word looks like a path. A blank line ends the list unless a bullet
    follows it. Code fence lines are ignored. Only the last heading counts.

    Edge cases: no heading gives ``found=False``; a heading with nothing readable under it
    gives ``found=True`` and no paths; duplicates are dropped keeping first position; paths
    are normalised without stripping a leading ``a/`` or ``b/``, since those are real
    directories in a repo-relative path.

    Args:
        answer: The full answer text.

    Returns:
        The parsed list.
    """
    lines = answer.splitlines()
    heading_at = None
    for index in range(len(lines) - 1, -1, -1):
        if _HEADING.match(lines[index]):
            heading_at = index
            break
    if heading_at is None:
        return FilesList(paths=(), found=False)

    raw_items: list[str] = []
    match = _HEADING.match(lines[heading_at])
    assert match is not None
    rest = match.group("rest")
    if rest:
        bullet = _BULLET.match(rest)
        raw_items.extend(_split_items(bullet.group("body") if bullet else rest))

    blank_seen = False
    for line in lines[heading_at + 1 :]:
        stripped = line.strip()
        if not stripped:
            blank_seen = True
            continue
        if stripped.startswith("```"):
            continue
        bullet = _BULLET.match(line)
        if bullet:
            raw_items.extend(_split_items(bullet.group("body")))
            blank_seen = False
            continue
        if blank_seen or not _looks_like_paths(line):
            break
        raw_items.extend(_split_items(line))

    paths: list[str] = []
    for item in raw_items:
        path = parse_item(item)
        if path is not None and path not in paths:
            paths.append(path)
    return FilesList(paths=tuple(paths), found=True)


__all__ = ["FilesList", "parse_files_list", "parse_item"]
