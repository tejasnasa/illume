"""The launcher must stay independent of the server package."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src"


def test_the_package_imports_nothing_from_app() -> None:
    files = list(SOURCE.rglob("*.py"))
    assert files

    offenders: list[str] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            else:
                continue
            offenders += [
                f"{path.name}: {module}"
                for module in modules
                if module == "app" or module.startswith("app.")
            ]

    assert offenders == []
