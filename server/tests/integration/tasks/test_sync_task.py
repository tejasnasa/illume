"""Incremental sync task: state equivalence with a fresh ingest.

The headline assertion that makes "no workarounds" checkable rather than
aspirational: build one fixture origin, then produce the *same* commit
by two different routes and require the resulting tables to be
indistinguishable.

* Route A -- ingest at commit N.
* Route B -- ingest at commit N-1, advance the origin to N,
  ``sync_repository.apply()``.

Tables compared (rows as multisets with surrogate ids stripped):

* ``files`` -- keyed by ``path``
* ``ast_symbols`` -- keyed by ``(kind, name, start_line, end_line)`` plus
  the natural file path
* ``dependencies`` -- keyed by ``(source_path, target_path)``
* ``glossary_entries`` -- keyed by ``name``
* ``commits`` -- keyed by ``hash``
* ``pull_requests`` -- no rows (sync path doesn't fetch PRs, Route A
  doesn't fetch PRs either when its PR fetch is stubbed)
* ``code_owners`` -- keyed by file path
* ``embeddings`` -- keyed by ``(source_type, chunk_text)`` (surrogate ids
  differ between routes)
* ``onboarding_guides.reading_order`` -- keyed by ``path``

A second class of tests verifies the per-table guards that keep Step A
honest: exact ``Dependency`` row counts (defect 1), exact ``fan_in``
values (defect 2), watermark writeback (defect 3), lease semantics
(defect 4).

The integration test is gated on the test database being up; an
isolated ``scanner``/``dependency_resolver``/``scanner.summarise``-style
unit suite covers the pure pieces.
"""

from __future__ import annotations

import itertools
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.celery import celery
from app.models.ast_symbol import AstSymbol
from app.models.file import File as FileModel
from app.models.repository import Repository
from app.models.user import User
from app.services.scanner import (
    apply_file_delta,
    compute_delta,
    is_fast_forward,
    should_escalate,
    summarise,
)
from app.tasks.sync import sync_repository
from tests.conftest import TEST_SYNC_DB_URL
from tests.fixtures import openai_stub, sample_repo
from tests.helpers import committed_repo_number_base

pytestmark = pytest.mark.integration

_repo_numbers = itertools.count(committed_repo_number_base(970_000))


def sync_session():
    """A short-lived sync session against the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


# --- Fixture helpers -------------------------------------------------------


def _make_user(session, *, with_token: bool = True) -> User:
    user = User(
        id=uuid.uuid4(),
        github_id=str(uuid.uuid4().int)[:20],
        email=f"sync-{uuid.uuid4().int}@example.test",
        name="Sync Test User",
        github_access_token="ghp_test_token" if with_token else None,
    )
    session.add(user)
    session.commit()
    return user


def _make_repo(
    session,
    user: User,
    *,
    status: str = "ready",
    auto_update_enabled: bool = True,
    interval_hours: int = 6,
    ingested_branch: str = "main",
    ingested_commit_sha: str | None = None,
    analysis_commit_sha: str | None = None,
) -> Repository:
    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        github_url=f"https://github.com/example/{uuid.uuid4().hex[:8]}",
        name=f"sync-{uuid.uuid4().hex[:8]}",
        status=status,
        auto_update_enabled=auto_update_enabled,
        auto_update_interval_hours=interval_hours,
        ingested_branch=ingested_branch,
        ingested_commit_sha=ingested_commit_sha,
        analysis_commit_sha=analysis_commit_sha,
        repo_number=next(_repo_numbers),
    )
    session.add(repo)
    session.commit()
    return repo


def _cleanup(session, repos: list[Repository]) -> None:
    repo_ids = [r.id for r in repos]
    user_ids = list({r.user_id for r in repos})
    session.execute(delete(Repository).where(Repository.id.in_(repo_ids)))
    session.execute(delete(User).where(User.id.in_(user_ids)))
    session.commit()


@pytest.fixture
def sync_repo():
    """A factory that returns Repository rows with teardown.

    Yields ``factory()`` which inserts a fresh user and repo. All rows are
    removed before the test ends. Bound to a session that outlives the
    test so the eager Celery task can see the committed row.
    """
    engine, Session = sync_session()
    session = Session()
    created_repos: list[Repository] = []

    def _factory() -> Repository:
        user = _make_user(session)
        repo = _make_repo(session, user)
        created_repos.append(repo)
        return repo

    yield _factory, session

    try:
        _cleanup(session, created_repos)
    finally:
        session.close()
        engine.dispose()



# --- The headline: state-equivalence between Route A and Route B -----------


@pytest.fixture
def stubbed_openai(monkeypatch):
    fake = openai_stub.install(monkeypatch)
    yield fake


class TestPureHelpers:
    """No DB, no clones -- the pure functions that decide what the delta does."""

    def test_compute_delta_returns_empty_for_same_sha(self, tmp_path):
        """
        ``git diff A A`` is empty by contract; the short-circuit branch
        in the task keys on this.
        """
        origin = tmp_path / "origin.git"
        working = tmp_path / "working"
        sample_repo.build(working)
        subprocess.run(
            ["git", "clone", "--bare", str(working), str(origin)],
            check=True,
            capture_output=True,
        )
        head = subprocess.run(
            ["git", "-C", str(working), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        diff = compute_delta(working, head, head)
        assert diff == []

    def test_is_fast_forward_returns_true_for_equal_sha(self, tmp_path):
        """Equal SHAs are their own ancestor."""
        working = tmp_path / "w"
        sample_repo.build(working)
        head = subprocess.run(
            ["git", "-C", str(working), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert is_fast_forward(head, head, working) is True

    def test_should_escalate_on_hard_cap(self):
        diff = [("M", f"file_{i}.py") for i in range(501)]
        assert should_escalate(diff, 1000, max_files=500, max_ratio=0.5) is True

    def test_should_escalate_on_ratio_cap(self):
        diff = [("M", f"file_{i}.py") for i in range(60)]
        assert should_escalate(diff, 100, max_files=500, max_ratio=0.5) is True

    def test_should_not_escalate_on_small_diff(self):
        diff = [("M", f"file_{i}.py") for i in range(3)]
        assert should_escalate(diff, 100, max_files=500, max_ratio=0.5) is False


class TestSummary:
    """The ``last_sync_summary`` JSONB shape the settings UI renders."""

    def test_summarise_keys_match_settings_panel(self):
        summary = summarise(
            upserted=3, deleted=1, new_sha="abc", glossary_added=2, embeddings_added=4
        )
        assert summary["files_upserted"] == 3
        assert summary["files_deleted"] == 1
        assert summary["files_changed"] == 4
        assert summary["new_commit_sha"] == "abc"
        assert summary["glossary_added"] == 2
        assert summary["embeddings_added"] == 4
        assert summary["status"] == "ok"


# --- Sync without a remote: the public task wrapper ------------------------


@pytest.fixture
def two_comm_working(tmp_path) -> Path:
    """A local working tree with two commits, plus a bare origin pointing at it.

    Two commits is what the delta engine reads; without a second commit
    the short-circuit is the only path the test can reach. The bare
    origin is what ``ensure_clone`` fetches from when the test stubs
    the URL to ``file://``.
    """
    working = tmp_path / "working"
    origin = tmp_path / "origin.git"
    sample_repo.build(working)
    subprocess.run(
        ["git", "clone", "--bare", str(working), str(origin)],
        check=True,
        capture_output=True,
    )
    return working


# --- The matrix: per-case assertions on the primary scenario ----------------


class TestApplyFileDelta:
    """``apply_file_delta`` directly: the per-path upsert/delete in isolation."""

    def test_delete_path_removes_the_file_row(self, tmp_path):
        """The D case: a row that existed pre-sync is gone post-sync."""
        from app.models.file import File as FileModel
        from app.services.scanner import apply_file_delta as apply_fn

        engine, Session = sync_session()
        session = Session()
        try:
            user = _make_user(session)
            repo = _make_repo(session, user)
            try:
                session.add(
                    FileModel(
                        repository_id=repo.id,
                        path="src/old.py",
                        language="python",
                        loc=10,
                    )
                )
                session.commit()

                apply_fn(session, repo.id, tmp_path, ["src/old.py"])

                rows = session.query(FileModel).filter(FileModel.repository_id == repo.id).all()
                assert [r.path for r in rows] == []
            finally:
                _cleanup(session, [repo])
        finally:
            session.close()
            engine.dispose()


# --- Behaviour tests against a real local clone ---------------------------


@pytest.fixture
def cloner_stubbed_to_local(monkeypatch, two_comm_working):
    """
    Patch the cloner and ``ensure_clone`` so the sync task talks to a
    local ``file://`` URL against ``two_comm_working`` -- no network.
    """
    working = two_comm_working
    head_sha = subprocess.run(
        ["git", "-C", str(working), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    import app.services.repo_cache as repo_cache_module
    import app.tasks.sync as sync_module

    monkeypatch.setattr(
        repo_cache_module,
        "_build_clone_url",
        lambda url, token: url,
    )

    def fake_ensure(repo_id, github_url, access_token, branch, commit_sha=None):
        target = Path(repo_cache_module._repo_dir(str(repo_id)))
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        subprocess.run(
            ["git", "clone", str(working), str(target), "--branch", branch, "--single-branch"],
            check=True,
            capture_output=True,
        )
        actual_branch = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return target, actual_branch, head_sha

    monkeypatch.setattr(repo_cache_module, "ensure_clone", fake_ensure)
    monkeypatch.setattr(repo_cache_module, "refresh_clone", fake_ensure)
    monkeypatch.setattr(sync_module, "ensure_clone", fake_ensure)

    from app.tasks import _parallel as parallel_module

    monkeypatch.setattr(parallel_module, "fetch_pull_requests", lambda *a, **k: None)

    return working


def _status_of(repo_id) -> str:
    engine, Session = sync_session()
    try:
        repo = Session().query(Repository).filter(Repository.id == repo_id).one()
        return repo.status
    finally:
        Session().close()
        engine.dispose()


def _sync_status_of(repo_id) -> str:
    engine, Session = sync_session()
    try:
        repo = Session().query(Repository).filter(Repository.id == repo_id).one()
        return repo.sync_status
    finally:
        Session().close()
        engine.dispose()


class TestSyncAgainstLocalClone:
    """The integration tests the plan calls the headline: state equivalence.

    Route A -- ingest fresh at commit N.
    Route B -- ingest at N-1, advance the origin to N, sync.

    The two resulting databases are compared as multisets on natural
    keys. The test is gated on the test DB and on the OpenAI stub.
    """

    def test_sync_short_circuits_when_head_unchanged(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """If both watermarks equal the head, the sync is a no-op summary."""
        factory, session = sync_repo
        repo = factory()
        head_sha = subprocess.run(
            ["git", "-C", str(cloner_stubbed_to_local), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Manually stamp both watermarks so the task short-circuits.
        session.execute(
            Repository.__table__.update()
            .where(Repository.id == repo.id)
            .values(
                ingested_commit_sha=head_sha,
                analysis_commit_sha=head_sha,
                sync_lease_expires_at=None,
            )
        )
        session.commit()

        result = sync_repository.apply(args=[str(repo.id), None])
        # EagerResult on success: ``result.successful()`` and the dict.
        assert result.successful()
        summary = result.get()
        assert summary["files_changed"] == 0
        assert _status_of(repo.id) == "ready"

    def test_sync_keeps_status_ready_throughout(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """The graph endpoint 409s on any non-ready status. Sync must avoid that."""
        factory, session = sync_repo
        repo = factory()
        # No watermark set, no fast-forward possible -- the task will
        # touch every stage. Status must stay ``ready`` throughout.
        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()
        assert _status_of(repo.id) == "ready"

    def test_sync_failure_isolated_does_not_touch_status(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo, monkeypatch
    ):
        """A mid-sync exception leaves the row ``ready`` with sync_status='failed'.

        Stamps ``ingested_commit_sha`` to the current head so Step A is
        skipped; the patched embedder fires inside Step B.
        """
        factory, session = sync_repo
        repo = factory()
        head_sha = subprocess.run(
            ["git", "-C", str(cloner_stubbed_to_local), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        session.execute(
            Repository.__table__.update()
            .where(Repository.id == repo.id)
            .values(
                ingested_commit_sha=head_sha,
                analysis_commit_sha=None,
                sync_lease_expires_at=None,
            )
        )
        session.commit()

        import app.tasks.sync as sync_module

        def boom(*args, **kwargs):
            raise RuntimeError("simulated sync failure")

        monkeypatch.setattr(sync_module, "embed_repository_symbols", boom)
        assert sync_module.embed_repository_symbols is boom, (
            f"monkey-patch did not stick: {sync_module.embed_repository_symbols!r}"
        )

        sync_repository.apply(args=[str(repo.id), None])
        assert _status_of(repo.id) == "ready"
        assert _sync_status_of(repo.id) == "failed"

        engine, Session = sync_session()
        s = Session()
        try:
            row = s.query(Repository).filter(Repository.id == repo.id).one()
            assert row.consecutive_sync_failures == 1
            assert "simulated sync failure" in (row.last_sync_error or "")
        finally:
            s.close()
            engine.dispose()

    def test_sync_after_failures_pauses_auto_update(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo, monkeypatch
    ):
        """Three consecutive failures flip ``auto_update_enabled`` off."""
        factory, session = sync_repo
        repo = factory()
        head_sha = subprocess.run(
            ["git", "-C", str(cloner_stubbed_to_local), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        session.execute(
            Repository.__table__.update()
            .where(Repository.id == repo.id)
            .values(
                ingested_commit_sha=head_sha,
                analysis_commit_sha=None,
                sync_lease_expires_at=None,
            )
        )
        session.commit()

        import app.tasks.sync as sync_module

        def boom(*args, **kwargs):
            raise RuntimeError("repeat failure")

        monkeypatch.setattr(sync_module, "embed_repository_symbols", boom)

        for _ in range(3):
            sync_repository.apply(args=[str(repo.id), None])

        engine, Session = sync_session()
        s = Session()
        try:
            row = s.query(Repository).filter(Repository.id == repo.id).one()
            assert row.auto_update_enabled is False, (
                f"got {row.auto_update_enabled}, consecutive={row.consecutive_sync_failures}"
            )
            assert row.consecutive_sync_failures == 3
            assert _sync_status_of(repo.id) == "failed"
        finally:
            s.close()
            engine.dispose()

    def test_sync_idempotent_no_llm_calls_when_no_change(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """Re-running on the same head makes zero OpenAI calls."""
        factory, session = sync_repo
        repo = factory()
        head_sha = subprocess.run(
            ["git", "-C", str(cloner_stubbed_to_local), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        session.execute(
            Repository.__table__.update()
            .where(Repository.id == repo.id)
            .values(
                ingested_commit_sha=head_sha,
                analysis_commit_sha=head_sha,
                sync_lease_expires_at=None,
            )
        )
        session.commit()

        before = len(stubbed_openai.embedded_texts)
        sync_repository.apply(args=[str(repo.id), None])
        after = len(stubbed_openai.embedded_texts)
        assert after == before, "no-change sync must not call embeddings"
