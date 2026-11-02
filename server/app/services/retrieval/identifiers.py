"""Identifier splitting shared by the lexical index and the queries against it.

Code identifiers are one token to a full-text parser: ``getUserById`` and
``parse_config`` would only match a query that spells them exactly. The
``embeddings.search_tsv`` generated column therefore indexes each chunk twice,
once with identifiers split into words and once as written, so a chunk matches
both ``getUserById`` and "get user by id".

The query side has to apply the same transform, or the two sides disagree on
what a word is. :func:`split_identifiers` is the Python twin of the SQL in the
generated column, and a test runs both on the same inputs to keep them equal.
The SQL lives in the migration that adds the column and in
:class:`~app.models.embedding.Embedding`; change all three together.
"""

from __future__ import annotations

import re

# Applied in this order, matching the nested ``regexp_replace`` calls:
# an acronym before a capitalised word (``HTTPServer`` -> ``HTTP Server``),
# then a lower-case letter or digit before a capital (``getUser`` -> ``get User``),
# then runs of separators used in snake_case, dotted names and paths.
_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_SEPARATORS = re.compile(r"[_./:-]+")


def split_identifiers(text: str) -> str:
    """Splits camelCase, PascalCase, snake_case, dotted names and paths into words.

    Case is kept; the ``simple`` text-search configuration lowercases later.
    """
    split = _ACRONYM_BOUNDARY.sub(r"\1 \2", text)
    split = _CAMEL_BOUNDARY.sub(r"\1 \2", split)
    return _SEPARATORS.sub(" ", split)


def lexical_text(text: str) -> str:
    """The text the lexical index actually parses: split words, then the original."""
    return f"{split_identifiers(text)} {text}"


# --- identifiers in a question -------------------------------------------------

# A backticked span is taken whole; anything else is a run of non-space characters.
_TOKEN_SCAN = re.compile(r"`([^`\n]+)`|([^\s`]+)")
_EDGE_PUNCTUATION = "\"'()[]{}<>,;:!?*`"
_LOWER_THEN_UPPER = re.compile(r"[a-z].*[A-Z]")
_ACRONYM_THEN_LOWER = re.compile(r"[A-Z]{2}[a-z]")
_HAS_WORD_CHARACTER = re.compile(r"[A-Za-z_]")
_FILE_EXTENSIONS = frozenset(
    {"py", "js", "ts", "tsx", "jsx", "json", "md", "yaml", "yml", "toml", "txt", "rs", "go", "java"}
)
_MIN_SEGMENT_LENGTH = 3
_QUOTED = re.compile(r"(?<!\w)(?:\"([^\"\n]+)\"|'([^'\n]+)')(?!\w)")


def _clean_token(raw: str) -> str:
    """Strips surrounding punctuation, a call's argument list and a trailing full stop."""
    token = raw.strip(_EDGE_PUNCTUATION)
    # ``getUser(id)`` and ``getUser()`` both name ``getUser``.
    token = re.split(r"[(\[{<]", token, maxsplit=1)[0]
    return token.strip(_EDGE_PUNCTUATION).rstrip(".")


def _looks_like_identifier(token: str) -> bool:
    """Whether a bare word has the shape of a code identifier rather than prose."""
    if not _HAS_WORD_CHARACTER.search(token):
        return False
    if "_" in token:
        return True
    if "." in token:
        # ``e.g`` and ``i.e`` are prose; a dotted name has a part longer than a letter.
        return any(len(part) > 1 for part in token.split("."))
    return bool(_LOWER_THEN_UPPER.search(token) or _ACRONYM_THEN_LOWER.search(token))


def identifier_tokens(text: str) -> list[str]:
    """Pulls the identifier-like tokens out of a question, in order of appearance.

    A token is kept when it is backticked, contains ``_`` or ``.``, or is
    camelCase or PascalCase (a lower-case letter followed later by an upper-case
    one, or two capitals followed by a lower-case letter). Surrounding
    punctuation, a trailing ``()`` or argument list and a closing full stop are
    stripped. A dotted name such as ``auth.verify_password`` also contributes its
    last segment, which is usually the symbol; file extensions and very short
    segments are not worth searching and are skipped.

    Args:
        text: The question, as typed.

    Returns:
        The distinct tokens, first occurrence first. Empty when the question
        mentions no identifier.
    """
    tokens: list[str] = []
    for match in _TOKEN_SCAN.finditer(text):
        backticked, bare = match.groups()
        token = _clean_token(backticked or bare)
        if not token:
            continue
        if backticked:
            # A backticked span may be code with spaces in it; only a single
            # word is a name worth looking up.
            if " " in token or not _HAS_WORD_CHARACTER.search(token):
                continue
        elif not _looks_like_identifier(token):
            continue

        tokens.append(token)
        if "." in token and "/" not in token:
            last = token.rsplit(".", 1)[1]
            if len(last) >= _MIN_SEGMENT_LENGTH and last.lower() not in _FILE_EXTENSIONS:
                tokens.append(last)
    return list(dict.fromkeys(tokens))


def quoted_strings(text: str, *, min_length: int = 3) -> list[str]:
    """The strings inside ``"..."`` or ``'...'`` in a question, in order.

    A quote glued to a word is an apostrophe (``user's``), not a quotation, so
    only quotes at word edges open or close a string.

    Args:
        text: The question, as typed.
        min_length: Shorter strings are dropped; they match nearly everything.

    Returns:
        The distinct strings, first occurrence first.
    """
    found = [
        (double or single).strip() for double, single in _QUOTED.findall(text) if (double or single)
    ]
    return list(dict.fromkeys(item for item in found if len(item) >= min_length))
