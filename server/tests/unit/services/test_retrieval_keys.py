"""Every source type gets the key the citation grammar promises."""

from __future__ import annotations

import pytest

from app.services.retrieval.citations import parse_key
from app.services.retrieval.keys import key_for, provenance_for, readme_heading
from app.services.retrieval.resolve import SourceReference

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("reference", "key"),
    [
        (
            SourceReference(
                source_type="symbol",
                chunk_text="x",
                file_path="app/auth.py",
                start_line=3,
                end_line=9,
            ),
            "F:app/auth.py:3-9",
        ),
        (
            SourceReference(source_type="symbol", chunk_text="x", file_path="app/auth.py"),
            "F:app/auth.py",
        ),
        (
            SourceReference(source_type="file", chunk_text="x", file_path="app/main.py"),
            "F:app/main.py",
        ),
        (
            SourceReference(source_type="commit", chunk_text="x", commit_hash="ABCDEF0123456789"),
            "C:abcdef01",
        ),
        (SourceReference(source_type="pull_request", chunk_text="x", pr_number=42), "PR:42"),
        (
            SourceReference(
                source_type="document", chunk_text="# README\n## Getting Started\ntext"
            ),
            "D:README#getting-started",
        ),
        (
            SourceReference(source_type="document", chunk_text="# README\nIntro paragraph."),
            "D:README#top",
        ),
    ],
)
def test_key_for_each_source_type(reference, key):
    assert key_for(reference) == key
    assert parse_key(key) is not None


def test_a_source_missing_its_identifier_still_gets_a_stable_key():
    orphan = SourceReference(source_type="commit", chunk_text="# Commit gone")
    assert key_for(orphan) == key_for(
        SourceReference(source_type="commit", chunk_text="# Commit gone")
    )
    assert key_for(orphan).startswith("X:commit:")


def test_a_code_source_without_a_path_is_an_error():
    with pytest.raises(ValueError):
        key_for(SourceReference(source_type="file", chunk_text="x"))


def test_readme_heading():
    assert readme_heading("# README\n## Install\nsteps") == "Install"
    assert readme_heading("# README\nIntro") == ""


def test_provenance():
    assert provenance_for("commit") == "history"
    assert provenance_for("pull_request") == "history"
    assert provenance_for("symbol") == "repo"
