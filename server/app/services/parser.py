"""AST-based source parsing via tree-sitter.

Parses source files (and Jupyter notebooks) into a flat list of symbols —
functions, classes, methods, and imports — with line ranges, raw source,
and cyclomatic complexity for functions/methods.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tree_sitter_language_pack import SupportedLanguage, get_parser

logger = logging.getLogger(__name__)

# Maps file extensions to tree-sitter language identifiers.
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ipynb": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".cs": "c_sharp",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
}

# Per-language mapping of tree-sitter node types to symbol kinds.
SYMBOL_NODE_TYPES: dict[str, dict[str, str]] = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
        "import_statement": "import",
        "import_from_statement": "import",
        "decorated_definition": "function",
    },
    "javascript": {
        "function_declaration": "function",
        "function_expression": "function",
        "arrow_function": "function",
        "class_declaration": "class",
        "import_statement": "import",
    },
    "typescript": {
        "function_declaration": "function",
        "function_expression": "function",
        "arrow_function": "function",
        "class_declaration": "class",
        "import_statement": "import",
        "interface_declaration": "class",
        "type_alias_declaration": "class",
        "export_statement": "function",
    },
    "tsx": {
        "function_declaration": "function",
        "function_expression": "function",
        "arrow_function": "function",
        "class_declaration": "class",
        "import_statement": "import",
        "export_statement": "function",
        "interface_declaration": "class",
        "type_alias_declaration": "class",
    },
    "jsx": {
        "function_declaration": "function",
        "function_expression": "function",
        "arrow_function": "function",
        "class_declaration": "class",
        "import_statement": "import",
        "export_statement": "function",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "class",
        "import_declaration": "import",
    },
    "rust": {
        "function_item": "function",
        "impl_item": "class",
        "struct_item": "class",
        "use_declaration": "import",
    },
    "java": {
        "method_declaration": "method",
        "class_declaration": "class",
        "import_declaration": "import",
    },
    "c": {
        "function_definition": "function",
        "preproc_include": "import",
    },
    "cpp": {
        "function_definition": "function",
        "class_specifier": "class",
        "preproc_include": "import",
    },
}

# Fallback node-type map for languages without an explicit entry above.
DEFAULT_SYMBOL_TYPES = {
    "function_definition": "function",
    "function_declaration": "function",
    "class_definition": "class",
    "class_declaration": "class",
    "import_statement": "import",
}


@dataclass
class ParsedSymbol:
    """A single extracted symbol (function, class, method, or import)."""

    name: str
    kind: str
    start_line: int
    end_line: int
    source_code: str
    cyclomatic_complexity: int = 0


@dataclass
class ParsedFile:
    """Parse result for one file: its language, LOC, and extracted symbols."""

    path: str
    language: str
    loc: int
    symbols: list[ParsedSymbol] = field(default_factory=list)


def get_language(file_path: Path) -> str | None:
    """Return the tree-sitter language id for a file's extension, or None."""
    return EXTENSION_TO_LANGUAGE.get(file_path.suffix)


def _extract_name(node, source_bytes: bytes) -> str:
    """Best-effort extraction of a symbol's name from its AST node."""
    if node.type in ("arrow_function", "function") and node.parent:
        parent = node.parent
        if parent.type == "variable_declarator":
            # Anonymous functions get their name from the variable they're assigned to.
            for child in parent.children:
                if child.type == "identifier":
                    return source_bytes[child.start_byte : child.end_byte].decode(
                        "utf-8", errors="replace"
                    )

    if node.type == "lexical_declaration":
        # `const handler = () => {}` / `const x = function() {}`: the arrow or
        # function expression itself is anonymous, so take the declared name.
        for child in node.children:
            if child.type == "variable_declarator":
                for subchild in child.children:
                    if subchild.type == "identifier":
                        return source_bytes[
                            subchild.start_byte : subchild.end_byte
                        ].decode("utf-8", errors="replace")

    if node.type == "decorated_definition":
        # The decorator wrapper isn't a symbol itself; descend to the
        # decorated function/class for kind, name, and source.
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                node = child
                break

    if node.type in ("import_statement", "import_from_statement"):
        # Imports are named by their module path; try the `source` field first,
        # then fall back to scanning child string/from-clause nodes since the
        # field name varies across grammars (Python vs JS).
        source_node = node.child_by_field_name("source")
        if source_node:
            raw = source_bytes[source_node.start_byte : source_node.end_byte].decode(
                "utf-8", errors="replace"
            )
            name = raw.strip("\"'`")
            return name if name else "<anonymous>"

        for child in node.children:
            if child.type == "string":
                raw = source_bytes[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                name = raw.strip("\"'`")
                return name if name else "<anonymous>"
            if child.type == "from_clause":
                for subchild in child.children:
                    if subchild.type == "string":
                        raw = source_bytes[
                            subchild.start_byte : subchild.end_byte
                        ].decode("utf-8", errors="replace")
                        name = raw.strip("\"'`")
                        return name if name else "<anonymous>"

        for child in node.children:
            if child.type in ("dotted_name", "aliased_import", "identifier"):
                # Plain `import x.y` has no string source; use the dotted name.
                return source_bytes[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )

    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

    # Last resort: first identifier-ish child (covers grammars where the
    # name isn't in a named field).
    for child in node.children:
        if child.type in ("identifier", "name"):
            return source_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )

    return "<anonymous>"


def _count_complexity(node) -> int:
    """Compute cyclomatic complexity by counting decision-point nodes in a subtree."""
    DECISION_TYPES = {
        "if_statement",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "catch_clause",
        "ternary_expression",
        "switch_case",
        "case_clause",
        "logical_and",
        "logical_or",
        "optional_chain",
        "elif_clause",
        "except_clause",
        "boolean_operator",
        "try_statement",
        "for_each_statement",
        "enhanced_for_statement",
    }
    count = 1
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in DECISION_TYPES:
            count += 1
        # Iterative traversal avoids recursion limits on deeply nested code.
        stack.extend(current.children)
    return count


def _parse_source(
    source_bytes: bytes, file_path: Path, language: str
) -> ParsedFile | None:
    """Parse raw source bytes with tree-sitter and extract symbols.

    Args:
        source_bytes: Raw file contents encoded as UTF-8.
        file_path: Path of the file being parsed (used for logging and the
            returned record).
        language: Tree-sitter language identifier.

    Returns:
        A ``ParsedFile`` with all top-level symbols, or None if tree-sitter
        cannot parse the source. Class bodies are descended into so nested
        methods are captured.
    """
    try:
        parser = get_parser(cast(SupportedLanguage, language))
        tree = parser.parse(source_bytes)
    except Exception as e:
        logger.warning("Tree-sitter failed on %s: %s", file_path, e)
        return None

    loc = source_bytes.count(b"\n") + 1
    symbol_types = SYMBOL_NODE_TYPES.get(language, DEFAULT_SYMBOL_TYPES)
    symbols: list[ParsedSymbol] = []

    root = tree.root_node
    nodes_to_visit = list(root.children)

    while nodes_to_visit:
        node = nodes_to_visit.pop()

        actual_node = node
        override_kind = None
        override_name = None
        if node.type == "export_statement":
            # `export function f()` / `export const x = () => ...` wrap the real
            # declaration; bare `export ... from ...` is a re-export (an import).
            found_decl = False
            for child in node.children:
                if child.type in ("function_declaration", "class_declaration"):
                    actual_node = child
                    found_decl = True
                    break
                elif child.type == "lexical_declaration":
                    for decl in child.children:
                        if decl.type == "variable_declarator":
                            for val in decl.children:
                                if val.type in ("arrow_function", "function"):
                                    actual_node = val
                                    found_decl = True
                                    break
            if not found_decl:
                for child in node.children:
                    if child.type == "string":
                        # No declaration inside => bare re-export
                        # (`export ... from "..."`), treated as an import.
                        raw = source_bytes[child.start_byte : child.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        override_kind = "import"
                        override_name = raw.strip("\"'`")
                        break

        if override_kind:
            symbols.append(
                ParsedSymbol(
                    name=override_name or "<anonymous>",
                    kind=override_kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_code=source_bytes[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="replace"
                    ),
                    cyclomatic_complexity=0,
                )
            )
        elif actual_node.type in symbol_types:
            kind = symbol_types[actual_node.type]
            name = _extract_name(actual_node, source_bytes)
            source_code = source_bytes[
                actual_node.start_byte : actual_node.end_byte
            ].decode("utf-8", errors="replace")
            complexity = (
                _count_complexity(actual_node) if kind in ("function", "method") else 0
            )

            symbols.append(
                ParsedSymbol(
                    name=name,
                    kind=kind,
                    start_line=actual_node.start_point[0] + 1,
                    end_line=actual_node.end_point[0] + 1,
                    source_code=source_code,
                    cyclomatic_complexity=complexity,
                )
            )

            if kind == "class":
                # Descend into class bodies so methods are captured too;
                # function bodies are not descended to avoid double-counting
                # nested defs as top-level symbols.
                nodes_to_visit.extend(actual_node.children)

    return ParsedFile(
        path=file_path.as_posix(),
        language=language,
        loc=loc,
        symbols=symbols,
    )


def parse_notebook(file_path: Path) -> ParsedFile | None:
    """Parse a Jupyter notebook by concatenating its code cells into one
    Python source and running the standard parser over it.

    Args:
        file_path: Path to the ``.ipynb`` file.

    Returns:
        A ``ParsedFile`` for the combined code cells, or None if the
        notebook JSON is malformed.
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        nb_data = json.loads(content)
    except Exception as e:
        logger.warning("Failed to parse notebook JSON %s: %s", file_path, e)
        return None

    cells = nb_data.get("cells", [])
    code_pieces = []
    for cell in cells:
        # Markdown cells are skipped; only code cells contain parseable Python.
        if cell.get("cell_type") == "code":
            source = cell.get("source", "")
            # nbformat allows source as either a list of lines or a single string.
            if isinstance(source, list):
                code_text = "".join(source)
            else:
                code_text = str(source)
            if code_text:
                # Ensure cell boundaries are newline-separated so symbols from
                # adjacent cells don't merge onto one line.
                if not code_text.endswith("\n"):
                    code_text += "\n"
                code_pieces.append(code_text)

    python_source = "".join(code_pieces)
    source_bytes = python_source.encode("utf-8")
    return _parse_source(source_bytes, file_path, "python")


def parse_file(file_path: Path) -> ParsedFile | None:
    """Parse any supported source file into a ``ParsedFile``.

    Routes notebooks to :func:`parse_notebook`; other files are parsed with
    the tree-sitter grammar matching their extension.

    Args:
        file_path: Path to the source file.

    Returns:
        A ``ParsedFile`` on success, or None if the extension is unsupported,
        the file can't be read, or parsing fails.
    """
    if file_path.suffix == ".ipynb":
        return parse_notebook(file_path)

    language = get_language(file_path)
    if not language:
        return None

    try:
        source_bytes = file_path.read_bytes()
    except (OSError, PermissionError) as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return None

    return _parse_source(source_bytes, file_path, language)
