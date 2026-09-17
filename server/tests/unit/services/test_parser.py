"""AST symbol extraction.

Runs the real tree-sitter grammars over real temp files -- there is nothing worth
mocking here, and grammar node names are exactly the kind of thing that drifts between
library versions and silently stops matching. The symbol tables are keyed on those names.
"""

import json

import pytest

from app.services.parser import (
    ParsedFile,
    get_language,
    parse_file,
    parse_notebook,
)

pytestmark = pytest.mark.unit


def write(tmp_path, name: str, content: str):
    """
    Write a fixture file without newline translation.

    `write_text` on Windows rewrites "\\n" to "\\r\\n", so a byte-for-byte comparison of
    extracted source against the original string fails on an invisible character.
    Writing bytes keeps the file exactly what the test declared.
    """
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return path


def names_of(parsed: ParsedFile, kind: str | None = None) -> set[str]:
    return {s.name for s in parsed.symbols if kind is None or s.kind == kind}


def symbol(parsed: ParsedFile, name: str):
    for s in parsed.symbols:
        if s.name == name:
            return s
    raise AssertionError(f"{name!r} not found; got {sorted(names_of(parsed))}")


class TestLanguageDetection:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("a.py", "python"),
            ("a.ipynb", "python"),
            ("a.js", "javascript"),
            ("a.jsx", "jsx"),
            ("a.ts", "typescript"),
            ("a.tsx", "tsx"),
            ("a.go", "go"),
            ("a.rs", "rust"),
            ("a.java", "java"),
            ("a.c", "c"),
            ("a.cpp", "cpp"),
            ("a.rb", "ruby"),
            ("a.cs", "c_sharp"),
        ],
    )
    def test_extension_maps_to_a_grammar(self, tmp_path, filename, expected):
        assert get_language(tmp_path / filename) == expected

    @pytest.mark.parametrize("filename", ["notes.md", "data.json", "archive.zip", "noext"])
    def test_unsupported_extensions_return_none(self, tmp_path, filename):
        assert get_language(tmp_path / filename) is None

    def test_unsupported_file_is_not_parsed(self, tmp_path):
        path = write(tmp_path, "notes.md", "# hello")

        assert parse_file(path) is None


class TestPython:
    def test_extracts_a_function(self, tmp_path):
        path = write(tmp_path, "m.py", "def greet():\n    return 'hi'\n")

        parsed = parse_file(path)

        assert names_of(parsed, "function") == {"greet"}

    def test_extracts_a_class(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            "class Service:\n"
            "    def start(self):\n"
            "        return 1\n"
            "    def stop(self):\n"
            "        return 2\n",
        )

        parsed = parse_file(path)

        assert names_of(parsed, "class") == {"Service"}

    def test_extracts_methods_from_a_class_body(self, tmp_path):
        """
        Methods must be reached. The class's immediate children hold the body as a single
        `block` node, which is not itself a symbol, so the traversal has to open it --
        otherwise every method in every repository is silently dropped.
        """
        path = write(
            tmp_path,
            "m.py",
            "class Service:\n"
            "    def start(self):\n"
            "        return 1\n"
            "    def stop(self):\n"
            "        return 2\n",
        )

        parsed = parse_file(path)

        assert names_of(parsed, "method") | names_of(parsed, "function") == {
            "start",
            "stop",
        }

    def test_does_not_hoist_nested_definitions_out_of_a_method(self, tmp_path):
        """Only class bodies are opened; a def inside a method stays out of the index."""
        path = write(
            tmp_path,
            "m.py",
            "class A:\n"
            "    def m(self):\n"
            "        def nested():\n"
            "            return 1\n"
            "        return nested\n",
        )

        parsed = parse_file(path)

        assert names_of(parsed) == {"A", "m"}

    def test_extracts_methods_from_a_nested_class(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            "class Outer:\n    class Inner:\n        def deep(self):\n            return 1\n",
        )

        parsed = parse_file(path)

        assert names_of(parsed, "class") == {"Outer", "Inner"}
        assert names_of(parsed, "function") == {"deep"}

    def test_extracts_imports(self, tmp_path):
        path = write(tmp_path, "m.py", "import os\nfrom app.core import config\n")

        parsed = parse_file(path)

        assert names_of(parsed, "import") == {"os", "app.core"}

    def test_handles_async_functions(self, tmp_path):
        path = write(tmp_path, "m.py", "async def fetch():\n    return 1\n")

        parsed = parse_file(path)

        assert "fetch" in names_of(parsed, "function")

    def test_decorator_does_not_create_a_spurious_symbol(self, tmp_path):
        """The decorator wrapper resolves to the function it decorates."""
        path = write(
            tmp_path,
            "m.py",
            "@staticmethod\ndef helper():\n    return 1\n",
        )

        parsed = parse_file(path)

        assert names_of(parsed, "function") == {"helper"}

    def test_line_numbers_are_one_based_and_inclusive(self, tmp_path):
        path = write(tmp_path, "m.py", "x = 1\n\ndef greet():\n    return 'hi'\n")

        parsed = parse_file(path)

        assert symbol(parsed, "greet").start_line == 3
        assert symbol(parsed, "greet").end_line == 4

    def test_loc_counts_lines(self, tmp_path):
        path = write(tmp_path, "m.py", "a = 1\nb = 2\nc = 3\n")

        assert parse_file(path).loc == 4  # three newlines plus a trailing empty line

    def test_source_code_is_captured_verbatim(self, tmp_path):
        source = "def greet():\n    return 'hi'\n"
        path = write(tmp_path, "m.py", source)

        assert symbol(parse_file(path), "greet").source_code == source.rstrip("\n")

    def test_empty_file_parses_to_no_symbols(self, tmp_path):
        path = write(tmp_path, "m.py", "")

        parsed = parse_file(path)

        assert parsed.symbols == []

    def test_unicode_identifiers_and_strings(self, tmp_path):
        path = write(tmp_path, "m.py", 'def saluer():\n    return "héllo wörld ☕"\n')

        parsed = parse_file(path)

        assert "saluer" in names_of(parsed, "function")

    def test_unicode_filename_is_handled(self, tmp_path):
        path = write(tmp_path, "módulo_日本語.py", "def f():\n    return 1\n")

        parsed = parse_file(path)

        assert "f" in names_of(parsed, "function")

    def test_syntax_error_does_not_raise(self, tmp_path):
        """
        Tree-sitter is error-tolerant, so a malformed file yields a partial parse rather
        than an exception. What matters is that ingestion is not aborted by one bad file.
        """
        path = write(tmp_path, "broken.py", "def (:\n  ???\nclass\n")

        parsed = parse_file(path)

        assert parsed is not None


class TestPythonComplexity:
    def test_a_straight_line_function_scores_one(self, tmp_path):
        path = write(tmp_path, "m.py", "def f():\n    return 1\n")

        assert symbol(parse_file(path), "f").cyclomatic_complexity == 1

    def test_each_branch_increases_complexity(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            "def f(a):\n"
            "    if a:\n"
            "        return 1\n"
            "    elif a is None:\n"
            "        return 2\n"
            "    return 3\n",
        )

        # base 1 + if + elif
        assert symbol(parse_file(path), "f").cyclomatic_complexity == 3

    def test_loops_and_boolean_operators_count(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            "def f(items):\n    for i in items:\n        if i and i > 0:\n            yield i\n",
        )

        complexity = symbol(parse_file(path), "f").cyclomatic_complexity

        assert complexity >= 4  # base + for + if + and

    def test_classes_are_not_scored_for_complexity(self, tmp_path):
        path = write(tmp_path, "m.py", "class C:\n    def m(self):\n        return 1\n")

        assert symbol(parse_file(path), "C").cyclomatic_complexity == 0

    def test_try_except_raises_complexity(self, tmp_path):
        path = write(
            tmp_path,
            "m.py",
            "def f():\n    try:\n        return 1\n    except ValueError:\n        return 2\n",
        )

        assert symbol(parse_file(path), "f").cyclomatic_complexity >= 2


class TestTypeScript:
    def test_extracts_a_function_declaration(self, tmp_path):
        path = write(tmp_path, "m.ts", "export function greet(): string { return 'hi'; }\n")

        assert "greet" in names_of(parse_file(path), "function")

    def test_extracts_an_arrow_function_from_its_variable(self, tmp_path):
        """The arrow itself is anonymous; the name comes from the declarator."""
        path = write(tmp_path, "m.ts", "export const handler = () => { return 1; };\n")

        assert "handler" in names_of(parse_file(path), "function")

    def test_extracts_a_class(self, tmp_path):
        path = write(tmp_path, "m.ts", "export class Service { run() { return 1; } }\n")

        assert "Service" in names_of(parse_file(path), "class")

    def test_extracts_imports(self, tmp_path):
        path = write(tmp_path, "m.ts", "import { thing } from './thing';\n")

        assert "./thing" in names_of(parse_file(path), "import")

    def test_a_bare_interface_is_treated_as_a_class(self, tmp_path):
        path = write(tmp_path, "m.ts", "interface Options { a: number; }\n")

        assert "Options" in names_of(parse_file(path), "class")

    def test_an_exported_interface_keeps_its_name_and_kind(self, tmp_path):
        """
        An `export` wrapper must be unwrapped before the kind is decided, or the wrapper
        becomes the symbol: kind "function", named `<anonymous>`, because `_extract_name`
        finds no name field on it.
        """
        path = write(tmp_path, "m.ts", "export interface Options { a: number; }\n")

        parsed = parse_file(path)

        assert names_of(parsed, "class") == {"Options"}
        assert names_of(parsed, "function") == set()

    def test_an_exported_type_alias_keeps_its_name(self, tmp_path):
        path = write(tmp_path, "m.ts", "export type Alias = string;\n")

        parsed = parse_file(path)

        assert names_of(parsed, "class") == {"Alias"}

    def test_no_symbol_is_ever_named_anonymous_for_this_shape(self, tmp_path):
        """The placeholder leaking into the graph is the symptom to guard against."""
        path = write(
            tmp_path,
            "m.ts",
            "export interface A { x: number; }\nexport type B = string;\n",
        )

        assert "<anonymous>" not in names_of(parse_file(path))

    def test_bare_reexport_is_treated_as_an_import(self, tmp_path):
        """`export ... from '...'` has no declaration, so it is a re-export, not a symbol."""
        path = write(tmp_path, "m.ts", "export { thing } from './thing';\n")

        assert "./thing" in names_of(parse_file(path), "import")


class TestNotebooks:
    def notebook(self, cells):
        return json.dumps({"cells": cells, "nbformat": 4, "nbformat_minor": 5})

    def test_parses_code_cells(self, tmp_path):
        path = write(
            tmp_path,
            "nb.ipynb",
            self.notebook(
                [
                    {"cell_type": "code", "source": ["def f():\n", "    return 1\n"]},
                ]
            ),
        )

        parsed = parse_file(path)

        assert "f" in names_of(parsed, "function")

    def test_skips_markdown_cells(self, tmp_path):
        path = write(
            tmp_path,
            "nb.ipynb",
            self.notebook(
                [
                    {"cell_type": "markdown", "source": ["def not_code():\n"]},
                    {"cell_type": "code", "source": ["def real():\n", "    return 1\n"]},
                ]
            ),
        )

        parsed = parse_file(path)

        assert names_of(parsed, "function") == {"real"}

    def test_source_as_a_plain_string_is_supported(self, tmp_path):
        """nbformat permits either a list of lines or one string."""
        path = write(
            tmp_path,
            "nb.ipynb",
            self.notebook([{"cell_type": "code", "source": "def f():\n    return 1\n"}]),
        )

        assert "f" in names_of(parse_file(path), "function")

    def test_cells_do_not_merge_onto_one_line(self, tmp_path):
        """A cell not ending in a newline must not concatenate with the next."""
        path = write(
            tmp_path,
            "nb.ipynb",
            self.notebook(
                [
                    {"cell_type": "code", "source": ["def first():\n", "    return 1"]},
                    {"cell_type": "code", "source": ["def second():\n", "    return 2"]},
                ]
            ),
        )

        parsed = parse_file(path)

        assert names_of(parsed, "function") == {"first", "second"}

    def test_malformed_notebook_json_returns_none(self, tmp_path):
        path = write(tmp_path, "nb.ipynb", "{not valid json")

        assert parse_notebook(path) is None

    def test_empty_notebook_parses_to_no_symbols(self, tmp_path):
        path = write(tmp_path, "nb.ipynb", self.notebook([]))

        assert parse_file(path).symbols == []


class TestFileReading:
    def test_missing_file_returns_none(self, tmp_path):
        assert parse_file(tmp_path / "does-not-exist.py") is None

    def test_path_is_reported_as_posix(self, tmp_path):
        path = write(tmp_path, "pkg/m.py", "x = 1\n")

        assert "\\" not in parse_file(path).path

    def test_language_is_recorded(self, tmp_path):
        path = write(tmp_path, "m.ts", "const a = 1;\n")

        assert parse_file(path).language == "typescript"
