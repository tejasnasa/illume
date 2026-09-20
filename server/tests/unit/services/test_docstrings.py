"""Docstring extraction.

Tests the four traps the Phase C plan calls out and the language-specific
shapes (``/** JSDoc */``, ``//`` runs, Go doc comments, the Python one-liner
``def f(): "doc"``). The goal is to pin the behaviour the embedder depends
on: the docstring is the prose immediately around the declaration, and
nothing else. The fixtures in ``sample_repo.py`` are the integration side of
the same coverage; these unit tests pin the algorithm itself.
"""

import pytest

from app.services.parser import parse_file

pytestmark = pytest.mark.unit


def write(tmp_path, name: str, content: str):
    """Write a fixture file as bytes to avoid Windows newline translation."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return path


def docstring_of(parsed, name: str):
    for sym in parsed.symbols:
        if sym.name == name:
            return sym.docstring
    raise AssertionError(f"{name!r} not found; got {[s.name for s in parsed.symbols]}")


class TestPython:
    """Trap 1: ``decorated_definition`` has no ``body`` -- descend first.

    Trap 2: Python's docstring is the body's first child when it's a string,
    and the body *is* the string for the one-liner ``def f(): "doc"``.
    """

    def test_a_function_docstring_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            'def greet():\n    """Say hello."""\n    return 1\n',
        )

        assert docstring_of(parse_file(path), "greet") == "Say hello."

    def test_a_class_docstring_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            'class C:\n    """A class."""\n    pass\n',
        )

        assert docstring_of(parse_file(path), "C") == "A class."

    def test_a_method_docstring_is_captured(self, tmp_path):
        """
        Trap 1 + the class-body path: the method is a ``function_definition``
        inside the class's ``block``; the docstring is the body's first child.
        """
        path = write(
            tmp_path,
            "m.py",
            'class C:\n    def m(self):\n        """Do the thing."""\n        return 1\n',
        )

        assert docstring_of(parse_file(path), "m") == "Do the thing."

    def test_a_decorated_function_docstring_is_captured(self, tmp_path):
        """
        Trap 1: ``decorated_definition.child_by_field_name("body")`` returns
        None. The inner ``function_definition`` must be reached first.
        """
        path = write(
            tmp_path,
            "m.py",
            (
                '"""Module doc."""\n'
                "\n"
                "\n"
                "@staticmethod\n"
                'def helper():\n    """Static helper."""\n    return 1\n'
            ),
        )

        assert docstring_of(parse_file(path), "helper") == "Static helper."

    def test_a_decorated_class_docstring_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            ('@dataclass\nclass Thing:\n    """A decorated class."""\n    x: int = 0\n'),
        )

        assert docstring_of(parse_file(path), "Thing") == "A decorated class."

    def test_a_one_line_python_docstring_is_captured(self, tmp_path):
        """
        Trap 2 variant: ``def f(): "doc"`` makes the ``block`` itself a
        ``string`` node, so the docstring is the body, not body's first child.
        """
        path = write(tmp_path, "m.py", 'def f(): "Inline doc."\n')

        assert docstring_of(parse_file(path), "f") == "Inline doc."

    def test_a_multi_line_docstring_is_collapsed_to_a_single_string(self, tmp_path):
        """
        The triple-quoted docstring's ``string_content`` spans multiple lines;
        the rendered docstring is the joined prose, not the raw quoted block.
        """
        path = write(
            tmp_path,
            "m.py",
            'def f():\n    """Line one.\n    Line two.\n    Line three."""\n    return 1\n',
        )

        assert docstring_of(parse_file(path), "f") == "Line one.\nLine two.\nLine three."

    def test_no_docstring_yields_none(self, tmp_path):
        path = write(tmp_path, "m.py", "def f():\n    return 1\n")

        assert docstring_of(parse_file(path), "f") is None

    def test_an_import_has_no_docstring(self, tmp_path):
        """Imports are not declarations; the column is None for them."""
        path = write(tmp_path, "m.py", "import os\n")

        for sym in parse_file(path).symbols:
            assert sym.docstring is None


class TestJavaScript:
    def test_a_jsdoc_above_a_function_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.js",
            "/** Greet the user. */\nfunction greet() { return 1; }\n",
        )

        assert docstring_of(parse_file(path), "greet") == "Greet the user."

    def test_a_multi_line_jsdoc_is_collapsed_to_one_string(self, tmp_path):
        path = write(
            tmp_path,
            "m.js",
            (
                "/**\n * Greet the user.\n *\n * Returns a greeting.\n */\n"
                "function greet() { return 1; }\n"
            ),
        )

        assert docstring_of(parse_file(path), "greet") == "Greet the user.\n\nReturns a greeting."

    def test_a_double_slash_comment_above_a_function_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.js",
            "// Say hello.\nfunction greet() { return 1; }\n",
        )

        assert docstring_of(parse_file(path), "greet") == "Say hello."

    def test_a_run_of_double_slash_comments_is_one_doc_block(self, tmp_path):
        """
        A multi-line ``//`` run is several sibling ``comment`` nodes on
        consecutive lines; they accumulate into one docstring.
        """
        path = write(
            tmp_path,
            "m.js",
            "// First line.\n// Second line.\nfunction greet() { return 1; }\n",
        )

        assert docstring_of(parse_file(path), "greet") == "First line.\nSecond line."

    def test_a_blank_line_breaks_the_docstring_run(self, tmp_path):
        """
        Trap 3: a blank line in the middle of a comment run ends it. The
        earlier comment is too far away to count as this function's docstring.
        """
        path = write(
            tmp_path,
            "m.js",
            "// Far-away note.\n\nfunction greet() { return 1; }\n",
        )

        assert docstring_of(parse_file(path), "greet") is None


class TestTypeScript:
    def test_a_jsdoc_above_an_export_function_is_captured(self, tmp_path):
        """
        Trap 4: the ``comment`` is the sibling of ``export_statement``, not
        the inner ``function_declaration``. The walker has to step to the
        parent before walking siblings.
        """
        path = write(
            tmp_path,
            "m.ts",
            "/** Greet the user. */\nexport function greet(): string { return 'hi'; }\n",
        )

        assert docstring_of(parse_file(path), "greet") == "Greet the user."

    def test_a_two_line_double_slash_run_above_an_export_arrow(self, tmp_path):
        path = write(
            tmp_path,
            "m.ts",
            "// Handle a request.\n// Validate the path first.\nexport const handler = () => 1;\n",
        )

        assert (
            docstring_of(parse_file(path), "handler")
            == "Handle a request.\nValidate the path first."
        )

    def test_a_jsdoc_above_an_exported_class_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.ts",
            "/** The client. */\nexport class ReportClient {\n  constructor() {}\n}\n",
        )

        assert docstring_of(parse_file(path), "ReportClient") == "The client."

    def test_no_comment_above_an_export_yields_none(self, tmp_path):
        path = write(
            tmp_path,
            "m.ts",
            "export function f(): void {}\n",
        )

        assert docstring_of(parse_file(path), "f") is None


class TestGo:
    def test_a_doc_comment_above_a_function_is_captured(self, tmp_path):
        path = write(
            tmp_path,
            "m.go",
            '// Greet says hello.\nfunc Greet() string { return "hi" }\n',
        )

        assert docstring_of(parse_file(path), "Greet") == "Greet says hello."

    def test_a_multi_line_doc_comment_is_one_doc_block(self, tmp_path):
        path = write(
            tmp_path,
            "m.go",
            (
                "// Greet produces a greeting.\n"
                "//\n"
                "// It is exported for callers in other packages.\n"
                'func Greet() string { return "hi" }\n'
            ),
        )

        assert (
            docstring_of(parse_file(path), "Greet")
            == "Greet produces a greeting.\n\nIt is exported for callers in other packages."
        )


class TestLicenceHeaders:
    """
    A comment run that documents the file (a licence, a copyright, a
    ``//!`` inner-doc marker) is *not* the next declaration's docstring.
    """

    def test_a_licence_header_at_the_top_is_not_attached_to_the_next_function(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            (
                "# @license MIT\n"
                "# Copyright 2024 Example\n"
                "\n"
                "\n"
                'def f():\n    """A real docstring."""\n    return 1\n'
            ),
        )

        assert docstring_of(parse_file(path), "f") == "A real docstring."

    def test_an_inner_doc_marker_run_is_not_a_docstring(self, tmp_path):
        """A ``//!`` Rust inner-doc run is a header, not a docstring."""
        path = write(
            tmp_path,
            "m.rs",
            "//! Crate-level doc.\n//! Not the next function's docstring.\n\nfn f() -> i32 { 1 }\n",
        )

        assert docstring_of(parse_file(path), "f") is None


class TestNegativeCases:
    """Cases where no docstring should be inferred."""

    def test_a_comment_two_blank_lines_above_a_function_is_not_a_docstring(self, tmp_path):
        """
        Two blank lines separate the ``// TODO`` from the declaration -- past
        the gap threshold, so it does not count.
        """
        path = write(
            tmp_path,
            "m.py",
            "# TODO: rewrite later.\n\n\n\ndef f():\n    return 1\n",
        )

        assert docstring_of(parse_file(path), "f") is None

    def test_a_non_comment_between_comment_and_function_breaks_the_run(self, tmp_path):
        path = write(
            tmp_path,
            "m.js",
            "// A note.\nconst x = 1;\nfunction f() {}\n",
        )

        assert docstring_of(parse_file(path), "f") is None

    def test_an_empty_comment_run_does_not_become_an_empty_string(self, tmp_path):
        """
        A JSDoc with only ``*``-prefixed lines, after marker stripping, is
        empty prose -- that is not a docstring, that is a stray decoration.
        """
        path = write(
            tmp_path,
            "m.js",
            "/**\n *\n */\nfunction f() {}\n",
        )

        assert docstring_of(parse_file(path), "f") is None
