"""Tests for the corpus report."""

import pytest
from sqlalchemy import func, select

from app.models import AstSymbol, Commit, File
from evals.corpus.report import COLUMNS, corpus_counts, format_table


@pytest.mark.integration
def test_counts_match_the_rows_ingestion_stored(ingest, db):
    result = ingest()
    counts = corpus_counts(db, result.repo_id)

    assert counts["files"] == db.scalar(
        select(func.count()).select_from(File).where(File.repository_id == result.repo_id)
    )
    assert counts["commits"] == db.scalar(
        select(func.count()).select_from(Commit).where(Commit.repository_id == result.repo_id)
    )
    assert counts["symbols"] == db.scalar(
        select(func.count())
        .select_from(AstSymbol)
        .join(File, File.id == AstSymbol.file_id)
        .where(File.repository_id == result.repo_id)
    )
    assert counts["files"] > 0 and counts["symbols"] > 0 and counts["commits"] >= 4
    assert counts["edges"] > 0
    assert counts["prs"] == 1
    assert counts["embeddings"]["pull_request"] == 1
    assert counts["embeddings"]["symbol"] > 0
    assert result.counts == counts


@pytest.mark.integration
def test_an_empty_repository_counts_zero(db):
    import uuid

    counts = corpus_counts(db, uuid.uuid4())
    assert all(counts[column] == 0 for column in COLUMNS)
    assert counts["embeddings"] == {}


@pytest.mark.unit
def test_the_table_lists_every_repository_with_aligned_columns():
    rows = {
        "alpha": {
            "files": 10,
            "symbols": 200,
            "edges": 30,
            "commits": 5,
            "prs": 4,
            "cochange_pairs": 7,
            "embeddings": {"symbol": 100, "commit": 5},
        },
        "beta-long-name": {
            "files": 1234,
            "symbols": 2,
            "edges": 0,
            "commits": 0,
            "prs": 0,
            "cochange_pairs": 0,
            "embeddings": {},
        },
    }
    lines = format_table(rows).splitlines()
    assert len(lines) == 4
    assert lines[0].split() == ["repo", *COLUMNS, "embeddings"]
    assert lines[2].split() == ["alpha", "10", "200", "30", "5", "4", "7", "105"]
    assert lines[3].split()[:2] == ["beta-long-name", "1234"]
    assert len({len(line) for line in lines}) == 1
