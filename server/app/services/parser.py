import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tree_sitter_language_pack import SupportedLanguage, get_parser

logger = logging.getLogger(__name__)

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
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

DEFAULT_SYMBOL_TYPES = {
    "function_definition": "function",
    "function_declaration": "function",
    "class_definition": "class",
    "class_declaration": "class",
    "import_statement": "import",
}


@dataclass
class ParsedSymbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    source_code: str
    cyclomatic_complexity: int = 0


@dataclass
class ParsedFile:
    path: str
    language: str
    loc: int
    symbols: list[ParsedSymbol] = field(default_factory=list)


def get_language(file_path: Path) -> str | None:
    return EXTENSION_TO_LANGUAGE.get(file_path.suffix)


def _extract_name(node, source_bytes: bytes) -> str:
    if node.type in ("arrow_function", "function") and node.parent:
        parent = node.parent
        if parent.type == "variable_declarator":
            for child in parent.children:
                if child.type == "identifier":
                    return source_bytes[child.start_byte : child.end_byte].decode(
                        "utf-8", errors="replace"
                    )

    if node.type == "lexical_declaration":
        for child in node.children:
            if child.type == "variable_declarator":
                for subchild in child.children:
                    if subchild.type == "identifier":
                        return source_bytes[
                            subchild.start_byte : subchild.end_byte
                        ].decode("utf-8", errors="replace")

    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                node = child
                break

    if node.type in ("import_statement", "import_from_statement"):
        for child in node.children:
            if child.type in ("dotted_name", "aliased_import", "identifier"):
                return source_bytes[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )
            if child.type == "string":
                raw = source_bytes[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                name = raw.strip("\"'`").lstrip("./")
                return name if name else "<anonymous>"

    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

    for child in node.children:
        if child.type in ("identifier", "name"):
            return source_bytes[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            )

    return "<anonymous>"


def _count_complexity(node) -> int:
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
        stack.extend(current.children)
    return count


def parse_file(file_path: Path) -> ParsedFile | None:
    language = get_language(file_path)
    if not language:
        return None

    try:
        source_bytes = file_path.read_bytes()
    except (OSError, PermissionError) as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return None

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
        if node.type == "export_statement":
            for child in node.children:
                if child.type in ("function_declaration", "class_declaration"):
                    actual_node = child
                    break
                elif child.type == "lexical_declaration":
                    for decl in child.children:
                        if decl.type == "variable_declarator":
                            for val in decl.children:
                                if val.type in ("arrow_function", "function"):
                                    actual_node = val
                                    break

        if actual_node.type in symbol_types:
            kind = symbol_types[node.type]
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
                nodes_to_visit.extend(actual_node.children)

    return ParsedFile(
        path=str(file_path),
        language=language,
        loc=loc,
        symbols=symbols,
    )
