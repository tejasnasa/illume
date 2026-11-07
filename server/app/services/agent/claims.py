"""Splitting an answer into claims, and marking what a verifier found.

A claim is one sentence a reader would treat as a statement about the
repository. The splitter is deliberately small and rule based: it protects
fenced code, inline code, citation keys and markdown links, splits on sentence
punctuation and on list-item boundaries, and leaves abbreviations, decimals and
file paths alone. A sentence that carries a citation key is always a claim; a
sentence without one is a claim only when it names a path, a symbol or a number,
which is the case the verifier reports as an uncited claim.

The mark the verifier leaves in the answer is machine-readable and stable::

    [[verify:<verdict>]]

It follows the claim it describes, after a single space, for example::

    Passwords are hashed with bcrypt [F:app/auth/security.py:4-8]. [[verify:supported]]

The verdicts are ``supported``, ``partially_supported``, ``unsupported``,
``contradicted``, ``unresolved_key`` and, for a factual sentence with no key,
``uncited``. A reader that wants the table rather than the prose reads the
:class:`~app.services.agent.state.VerificationReport`; the marks exist so the
same table can be rendered over the answer itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.agent.state import ClaimVerdict
from app.services.retrieval.citations import find_keys

MARK_TEMPLATE = "[[verify:{verdict}]]"
"""The one mark format. The verdict is a lower-case, underscore-separated name."""

MARK_PATTERN = re.compile(r"\[\[verify:(?P<verdict>[a-z_]+)\]\]")

# Words whose full stop does not end a sentence.
_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "al",
        "approx",
        "cf",
        "co",
        "corp",
        "dept",
        "dr",
        "e.g",
        "est",
        "etc",
        "fig",
        "i.e",
        "inc",
        "jr",
        "ltd",
        "mr",
        "mrs",
        "ms",
        "no",
        "prof",
        "sr",
        "st",
        "u.k",
        "u.s",
        "vs",
    }
)

# A leading list bullet, block quote or heading marker, which is not part of the claim.
_MARKER = re.compile(r"[ \t]*(?:[>#]+[ \t]*|[-*+][ \t]+|\d+[.)][ \t]+)")

# A path, with or without a known source extension.
_PATH = re.compile(
    r"(?<![\w.-])(?:[\w.-]+/)+[\w.-]+"
    r"|(?<![\w.-])[\w-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|go|rs|java|kt|rb|php|cs|cpp|cc|"
    r"c|h|hpp|md|mdx|json|ya?ml|toml|ini|cfg|sql|sh|bash|ps1|html|css|scss|vue|svelte|"
    r"swift|scala|ex|exs|erl|clj|dart|lua|r|jl|tf|proto|graphql|gql|lock|txt)\b"
)

# An identifier a reader would recognise as a name: backticked, snake_case,
# camelCase, PascalCase with an internal capital, or written as a call.
_SYMBOL = re.compile(
    r"`[^`\n]+`"
    r"|\b[a-z][a-z0-9]*_[a-z0-9_]+\b"
    r"|\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b"
    r"|\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b"
    r"|\b[A-Za-z_][A-Za-z0-9_]*\(\)"
)

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?(?![\w.])")


@dataclass(frozen=True)
class ClaimSpan:
    """One claim and where it sits in the answer.

    Attributes:
        index: The claim's position among the answer's claims, from one.
        text: The sentence without its leading list or heading marker.
        start: The offset of ``text`` in the answer.
        end: The offset just past the last character of ``text``; a mark goes here.
        keys: The citation keys the sentence writes, as written, without brackets.
        uncited: Whether the sentence states a fact but carries no key.
    """

    index: int
    text: str
    start: int
    end: int
    keys: tuple[str, ...] = ()
    uncited: bool = False


def mark_for(verdict: ClaimVerdict | None) -> str:
    """The mark for one verdict, or for an uncited claim when ``verdict`` is ``None``."""
    return MARK_TEMPLATE.format(verdict=verdict.value if verdict is not None else "uncited")


def extract_marks(answer: str) -> list[tuple[int, str]]:
    """Every mark in ``answer``, as ``(offset, verdict)`` in order of appearance."""
    return [(match.start(), match.group("verdict")) for match in MARK_PATTERN.finditer(answer)]


def looks_factual(sentence: str) -> bool:
    """Whether a sentence without a key names a path, a symbol or a number.

    That is the rule for treating it as an uncited claim rather than ordinary
    prose. It is intentionally conservative: a sentence made only of plain words
    is not a claim the verifier tries to count.
    """
    return bool(_PATH.search(sentence) or _SYMBOL.search(sentence) or _NUMBER.search(sentence))


def _protected(text: str) -> list[bool]:
    """Which characters must not be treated as sentence punctuation.

    Fenced code, inline code, citation brackets and markdown links are all
    protected, so a full stop inside any of them cannot end a sentence.
    """
    mask = [False] * len(text)

    def protect(start: int, end: int) -> None:
        for position in range(max(start, 0), min(end, len(text))):
            mask[position] = True

    for match in re.finditer(r"```.*?```|~~~.*?~~~", text, re.DOTALL):
        protect(match.start(), match.end())
    for match in re.finditer(r"`[^`\n]*`", text):
        protect(match.start(), match.end())
    for match in re.finditer(r"\[[^\]\n]*\]\([^)\n]*\)", text):
        protect(match.start(), match.end())

    position = 0
    while True:
        opening = text.find("[", position)
        if opening == -1:
            break
        if not text.startswith(("PR:", "F:", "C:", "D:"), opening + 1):
            position = opening + 1
            continue
        depth = 0
        closing = None
        for index in range(opening, len(text)):
            if text[index] == "\n":
                break
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            position = opening + 1
            continue
        protect(opening, closing + 1)
        position = closing + 1
    return mask


def _word_before(text: str, dot: int) -> str:
    """The token before a full stop, lower-cased, for the abbreviation test."""
    position = dot
    while position > 0 and (text[position - 1].isalnum() or text[position - 1] == "."):
        position -= 1
    return text[position:dot].lower()


def _is_sentence_end(text: str, position: int, protected: list[bool]) -> bool:
    """Whether the punctuation at ``position`` closes a sentence."""
    if protected[position]:
        return False
    character = text[position]
    if character == ".":
        previous = text[position - 1] if position else ""
        following = text[position + 1] if position + 1 < len(text) else ""
        if previous.isdigit() and following.isdigit():
            return False
        word = _word_before(text, position)
        if word in _ABBREVIATIONS or len(word) == 1:
            return False
        if text.startswith("..", position):
            return False
    after = position + 1
    if after < len(text) and not text[after].isspace():
        return False
    while after < len(text) and text[after].isspace():
        after += 1
    if after >= len(text):
        return True
    return text[after].isupper() or text[after].isdigit() or text[after] in "`\"'([{"


def _starts_item(text: str, position: int) -> bool:
    """Whether the line beginning at ``position`` is a new list item or heading."""
    while position < len(text) and text[position] in " \t":
        position += 1
    if position >= len(text):
        return True
    if text[position] in "#>|":
        return True
    if text[position] in "-*+" and position + 1 < len(text) and text[position + 1].isspace():
        return True
    return bool(re.match(r"\d+[.)]\s", text[position : position + 8]))


def _newline_ends_sentence(text: str, position: int) -> bool:
    """Whether the newline at ``position`` separates one claim from the next."""
    if text.startswith("\n\n", position):
        return True
    following = position + 1
    if _starts_item(text, following):
        return True
    previous = position
    while previous > 0 and text[previous - 1] in " \t":
        previous -= 1
    return previous > 0 and text[previous - 1] in ".!?:;"


def _trim(text: str, start: int, end: int) -> tuple[str, int, int]:
    """The meaningful text of a segment, without surrounding whitespace or a marker."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    marker = _MARKER.match(text, start)
    if marker is not None and marker.end() <= end:
        start = marker.end()
    return text[start:end], start, end


def split_claims(answer: str) -> tuple[ClaimSpan, ...]:
    """Splits ``answer`` into the sentences that make a claim.

    Every sentence carrying a citation key is a claim. A sentence without one is
    a claim only when :func:`looks_factual` recognises a path, a symbol or a
    number in it; those are reported as uncited. Everything else, such as a
    heading or a sentence of ordinary prose, is skipped.

    Args:
        answer: The finished answer, in markdown.

    Returns:
        The claims in the order they appear, each with the offsets a mark can be
        inserted at.
    """
    if not answer.strip():
        return ()
    protected = _protected(answer)
    spans: list[ClaimSpan] = []
    start = 0
    position = 0
    while position < len(answer):
        character = answer[position]
        boundary = False
        if character == "\n" and not protected[position]:
            boundary = _newline_ends_sentence(answer, position)
        elif character in ".!?" and _is_sentence_end(answer, position, protected):
            boundary = True
        if not boundary:
            position += 1
            continue
        claim = _claim(answer, start, position + (0 if character == "\n" else 1), len(spans) + 1)
        if claim is not None:
            spans.append(claim)
        start = position + 1
        position += 1

    tail = _claim(answer, start, len(answer), len(spans) + 1)
    if tail is not None:
        spans.append(tail)
    return tuple(spans)


def _claim(answer: str, start: int, end: int, index: int) -> ClaimSpan | None:
    """One segment as a claim, or ``None`` when it makes no claim."""
    text, start, end = _trim(answer, start, end)
    if not text:
        return None
    keys = tuple(raw for raw, _ in find_keys(text))
    if keys:
        return ClaimSpan(index=index, text=text, start=start, end=end, keys=keys)
    if not looks_factual(text):
        return None
    return ClaimSpan(index=index, text=text, start=start, end=end, uncited=True)


def mark_answer(answer: str, claims: tuple[ClaimSpan, ...], marks: dict[int, str]) -> str:
    """Appends each claim's mark to the answer, leaving every character of it in place.

    Args:
        answer: The answer to mark.
        claims: The claims :func:`split_claims` found, with their offsets.
        marks: The mark text for each claim index that has one.

    Returns:
        The answer with a space and the mark inserted after each marked claim.
    """
    pieces: list[str] = []
    position = 0
    for claim in claims:
        mark = marks.get(claim.index)
        if mark is None:
            continue
        pieces.append(answer[position : claim.end])
        pieces.append(f" {mark}" if not answer[: claim.end].endswith((" ", "\n")) else mark)
        position = claim.end
    pieces.append(answer[position:])
    return "".join(pieces)
