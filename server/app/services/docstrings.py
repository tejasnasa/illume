"""Docstring and doc-comment extraction for parsed declarations.

The parser walks a tree-sitter tree and produces one ``ParsedSymbol`` per
declaration; this module is the second pass that attaches the prose a
declaration is documented by (a Python docstring for ``def``/``class``, a
preceding JSDoc or ``//`` comment run for JS/TS/Go/etc.).

Why a separate module. The four language-specific traps the Phase C plan
calls out (``decorated_definition`` has no ``body``, Python's one-line
docstring makes ``block`` itself a string, line gaps are not validity
tests, ``export_statement`` is a wrapper) all live on tree-sitter node
introspection and would otherwise bulk up ``parser.py`` past the point
where the rest of the pipeline can be read at a glance.

Public entry point: :func:`extract_docstring`. Everything else is module
private -- callers do not need the marker stripper or the Python-vs-comment
split, only the resolved string (or ``None``).

The embedder consumes the result verbatim in :func:`embedder._build_chunk_text`,
which performs its own de-duplication against ``source_code`` so a Python
docstring that is already inside the captured slice is not embedded twice.
"""

import inspect

# Cap on the rendered docstring text. A header comment for a single function
# is rarely longer than this; anything bigger is almost certainly a copy-paste
# artefact that the embedder would otherwise spend tokens on.
MAX_DOCSTRING_CHARS = 4_000

# License-header markers. A comment run containing any of these (case-
# insensitively) is dropped rather than treated as a docstring -- the run
# documents the file, not the next declaration.
_LICENSE_MARKERS = ("@license", "copyright", "//!")


def _strip_comment_markers(text: str) -> str:
    """Strip leading line-comment markers and trailing block-comment markers.

    Tree-sitter gives ``comment`` nodes verbatim: a JSDoc block carries its
    ``/**``/``*/`` markers, a single-line ``//`` comment keeps its prefix,
    Python ``#`` comments keep theirs. This helper trims them so the rendered
    docstring is the author's prose, not the punctuation around it.

    Empty lines are preserved as paragraph separators -- a JSDoc ``*`` alone
    on a line is the author's signal that the previous paragraph ended. The
    final pass collapses any runs of blank lines that came from the comment
    block's own padding (``/**`` and ``*/`` framing lines that became empty
    after marker removal).
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Block-comment openers / closers, in the order they appear.
        for prefix in ("/**", "/*", "//!", "///", "//", "#"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :]
                break
        if stripped.endswith("*/"):
            stripped = stripped[:-2].rstrip()
        # JSDoc middle lines start with " *".
        if stripped.startswith("*") and not stripped.startswith("**"):
            stripped = stripped[1:].lstrip()
        # Re-strip to drop the leading space the prefix removal may leave
        # behind (``"// foo"`` becomes ``" foo"`` after the prefix is removed).
        stripped = stripped.strip()
        cleaned.append(stripped)
    # Collapse runs of blank lines so the JSDoc framing (``/**`` and ``*/``
    # becoming empty) does not produce visible double-blanks.
    collapsed: list[str] = []
    prev_blank = False
    for line in cleaned:
        blank = line == ""
        if blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = blank
    text = "\n".join(collapsed).strip()
    return text


def _is_license_header(comments: list) -> bool:
    """Return True if any comment in the run names a license or copyright."""
    for node in comments:
        text = node.text.decode("utf-8", errors="replace")
        lowered = text.lower()
        for marker in _LICENSE_MARKERS:
            if marker in lowered:
                return True
    return False


def _python_docstring(node, source_bytes: bytes) -> str | None:
    """Extract a Python docstring from a function or class definition node.

    Handles the two Python shapes the plan calls out:

    * a multi-line docstring sits as the first named child of ``node.body``
      (the ``block``), so we look at ``named_children[0]``;
    * a one-liner ``def f(): "docstring"`` makes the ``block`` itself a
      ``string`` node.
    """
    body = node.child_by_field_name("body")
    if body is None:
        return None
    if body.type == "string":
        return _python_string_text(body, source_bytes)
    if body.named_children:
        first = body.named_children[0]
        if first.type == "string":
            return _python_string_text(first, source_bytes)
    return None


def _python_string_text(string_node, source_bytes: bytes) -> str:
    """Pull a docstring's plain text out of a Python ``string`` node.

    Concatenates every ``string_content`` child and decodes it; the triple-
    quoted wrapper and any prefix characters (``r``, ``b``, ``f``) are
    handled by skipping every non-content sibling. ``inspect.cleandoc``
    is what Python itself uses to render docstrings -- it strips the
    common leading whitespace from continuation lines (which ``dedent``
    alone misses when the first line is already at column zero) and
    collapses runs of blank lines.
    """
    parts: list[str] = []
    for child in string_node.children:
        if child.type == "string_content":
            parts.append(
                source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            )
    text = inspect.cleandoc("".join(parts)).strip()
    return text[:MAX_DOCSTRING_CHARS] if text else ""


def _comment_docstring(node) -> str | None:
    """Extract a docstring from a C-family declaration by walking its siblings.

    A declaration's docstring is the run of ``comment`` nodes immediately
    preceding it, with no blank lines between consecutive siblings (or between
    the last comment and the declaration). A run that includes a license
    marker is dropped. The result is the run's text with comment markers
    stripped.

    The walker steps over ``export_statement`` wrappers (Trap 4 from the
    plan): for ``/** */ export function f() {}``, the comment is the sibling
    of ``export_statement``, not the inner ``function_declaration``, so we
    start from the *outermost* node when it is an export wrapper.
    """
    target = node

    # Walk backwards from the previous named sibling, collecting a contiguous
    # comment run. ``prev_named_sibling`` is None past the first non-comment
    # neighbour, which terminates the walk.
    siblings: list = []
    prev = target.prev_named_sibling
    while prev is not None and prev.type == "comment":
        siblings.append(prev)
        prev = prev.prev_named_sibling

    if not siblings:
        return None
    # We appended from decl-out; reverse so the run reads top-to-bottom.
    siblings.reverse()

    # Adjacency test: a gap of more than one line between two consecutive
    # siblings ends the run, as does a gap of more than one line between the
    # last comment and the declaration. Tree-sitter start/end points are
    # 0-based and ``end_point`` is exclusive, so consecutive lines give a gap
    # of 0; one blank line between them gives a gap of 1.
    for i in range(len(siblings) - 1):
        if siblings[i + 1].start_point[0] - siblings[i].end_point[0] > 1:
            return None
    if target.start_point[0] - siblings[-1].end_point[0] > 1:
        return None

    if _is_license_header(siblings):
        return None
    text = _strip_comment_markers(
        "\n".join(node.text.decode("utf-8", errors="replace") for node in siblings)
    )
    if not text:
        return None
    return text[:MAX_DOCSTRING_CHARS]


def extract_docstring(node, actual_node, source_bytes: bytes, language: str) -> str | None:
    """Find the docstring (or its absence) for a declaration node.

    Trap 4: when the declaration is wrapped in ``export_statement``, the
    preceding ``comment`` is the wrapper's sibling, not the inner node's.
    So the comment walker has to step to the wrapper first. For Python
    there is no export, so we use the original node.

    Trap 1 (Python only): ``decorated_definition`` has no ``body``; descend
    to the inner ``function_definition``/``class_definition`` first.
    """
    # The node the comment walker starts from. For non-Python we want the
    # outermost wrapper when there is one, because that is what the
    # preceding comment is the sibling of. For Python there is no export
    # wrapper, so the original ``node`` is always correct.
    target = node if language != "python" else actual_node
    if language == "python" and target.type == "decorated_definition":
        for child in target.children:
            if child.type in ("function_definition", "class_definition"):
                target = child
                break
    if language == "python":
        return _python_docstring(target, source_bytes)
    return _comment_docstring(target)
