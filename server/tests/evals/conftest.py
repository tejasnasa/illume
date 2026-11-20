"""Fixtures shared by the corpus ingestion and report tests."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from evals.corpus.corpus import CorpusRepo
from evals.corpus.ingest import IngestResult, ingest_at_base
from evals.mining.github_cache import CachedPR, CachedPRFile, save_pr
from tests.fixtures import openai_stub, sample_repo

POST_BASE_TEXT = "ZEBRA-LANDS-AFTER-THE-BASE-COMMIT"
EARLY_TEXT = "QUOKKA-HAS-AN-EARLY-DATE-BUT-IS-NOT-AN-ANCESTOR"
HISTORY_TEXT = "NARWHAL-IS-ORDINARY-HISTORY"
UNKNOWN_SHA = "f" * 40


def _pr(number: int, sha: str, merged: datetime, body: str, *, files=None) -> CachedPR:
    return CachedPR(
        number=number,
        title=f"Pull request {number}",
        body=body,
        author="ada",
        merged_at=merged,
        merge_commit_sha=sha,
        files=files,
        labels=("fixture",),
        user_type="User",
    )


@pytest.fixture
def history(tmp_path) -> sample_repo.HistoryRepo:
    """The sample repository with branches, a whitespace commit and a moved function."""
    return sample_repo.build_with_history(tmp_path / "history-repo")


@pytest.fixture
def cache_dir(tmp_path, history) -> Path:
    """A GitHub cache with one ordinary, one post-base, one early-dated and one unknown PR."""
    directory = tmp_path / "github"
    slug = corpus_repo_for(history).slug
    files = (CachedPRFile("docs/x.md", "added", None, 3, 0),)
    for pr in (
        _pr(
            sample_repo.PR_A_NUMBER,
            history.pr_a_merge,
            datetime(2026, 2, 15, tzinfo=UTC),
            HISTORY_TEXT,
        ),
        _pr(
            sample_repo.PR_B_NUMBER,
            history.pr_b_merge,
            datetime(2026, 5, 1, tzinfo=UTC),
            POST_BASE_TEXT,
            files=files,
        ),
        _pr(
            sample_repo.PR_EARLY_NUMBER,
            history.pr_early_merge,
            datetime(2026, 1, 15, tzinfo=UTC),
            EARLY_TEXT,
        ),
        _pr(104, UNKNOWN_SHA, datetime(2026, 2, 20, tzinfo=UTC), "object missing"),
    ):
        save_pr(directory, slug, pr)
    return directory


def corpus_repo_for(history: sample_repo.HistoryRepo, base: str | None = None, **kw) -> CorpusRepo:
    """A corpus entry whose URL is the local sample repository."""
    return CorpusRepo(
        name="sample",
        url=str(history.root),
        language="Python",
        licence="MIT",
        base_commit=base or history.base,
        **kw,
    )


@pytest.fixture
def session_factory():
    """A sessionmaker on the test database; the engine is disposed afterwards."""
    from tests.conftest import TEST_SYNC_DB_URL

    engine = create_engine(TEST_SYNC_DB_URL)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    """A committed-writes session; every user this test created is removed afterwards."""
    session = session_factory()
    yield session
    session.rollback()
    session.execute(
        text(
            "DELETE FROM repositories WHERE user_id IN "
            "(SELECT id FROM users WHERE email LIKE 'eval-test-%')"
        )
    )
    session.execute(text("DELETE FROM users WHERE email LIKE 'eval-test-%'"))
    session.commit()
    session.close()


@pytest.fixture
def ingest(db, history, cache_dir, monkeypatch) -> Callable[..., IngestResult]:
    """Run ``ingest_at_base`` against the sample repository with the LLM and embeddings faked."""
    openai_stub.install(monkeypatch)

    def run(base: str | None = None, **kw) -> IngestResult:
        return ingest_at_base(
            db,
            corpus_repo=corpus_repo_for(history, base, **kw),
            user_email=f"eval-test-{uuid.uuid4().hex[:8]}@example.com",
            cache_dir=cache_dir,
            llm_config=None,
        )

    return run
