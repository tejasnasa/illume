"""Identifier splitting, as the lexical index and its queries apply it."""

from __future__ import annotations

import pytest

from app.services.retrieval.identifiers import lexical_text, split_identifiers

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("getUserById", "get User By Id"),
        ("HTTPServer", "HTTP Server"),
        ("parseHTTPResponse", "parse HTTP Response"),
        ("parse_config", "parse config"),
        ("__init__", " init "),
        ("app/core/auth.py", "app core auth py"),
        ("os.path.join", "os path join"),
        ("kebab-case-name", "kebab case name"),
        ("v2Api", "v2 Api"),
        ("plain words stay", "plain words stay"),
    ],
)
def test_split_identifiers(text, expected):
    assert split_identifiers(text) == expected


def test_lexical_text_keeps_the_original_after_the_split():
    assert lexical_text("getUserById") == "get User By Id getUserById"


def test_the_model_and_the_migration_declare_the_same_expression():
    """The column is defined twice, once to create it and once so drift checks see it."""
    import importlib.util
    from pathlib import Path

    from app.models.embedding import SEARCH_TSV_EXPRESSION

    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "c9d0e1f2a3b4_add_lexical_trigram_and_cochange.py"
    )
    spec = importlib.util.spec_from_file_location("lexical_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._SEARCH_TSV_EXPRESSION == SEARCH_TSV_EXPRESSION
