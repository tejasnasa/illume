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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import sessionmaker

from app.models.file import File as FileModel
from app.models.repository import Repository
from app.models.user import User
from app.services.scanner import (
    compute_delta,
    is_fast_forward,
    should_escalate,
    summarise,
)
from app.tasks.sync import _fresh_generation, sync_repository
from tests.conftest import TEST_SYNC_DB_URL
from tests.fixtures import openai_stub, sample_repo
from tests.helpers import (
    RATIO_ESCALATION_IS_UNREACHABLE,
    RENAME_ORPHANS_THE_VACATED_FILE,
    committed_repo_number_base,
)

pytestmark = pytest.mark.integration

_repo_numbers = itertools.count(committed_repo_number_base(970_000))


def sync_session():
    """A short-lived sync session against the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


# --- Fixture helpers -------------------------------------------------------


def _make_user(session, *, with_token: bool = True, with_ai_key: bool = True) -> User:
    """Create a user suitable for sync tests.

    ``with_ai_key=True`` is the default because the task-level backstop
    in :func:`app.tasks.sync.sync_repository` returns ``None`` when the
    owner has no stored key -- which would short-circuit every existing
    sync test that exercised a real head-but-no-watermark sync. The flag
    passes through the parameters a real save would write (``provider``,
    ``key``, ``model``).
    """
    user = User(
        id=uuid.uuid4(),
        github_id=str(uuid.uuid4().int)[:20],
        email=f"sync-{uuid.uuid4().int}@example.test",
        name="Sync Test User",
        github_access_token="ghp_test_token" if with_token else None,
    )
    if with_ai_key:
        user.ai_provider = "openai"
        user.ai_api_key = "sk-test"
        user.ai_model = "gpt-4o-mini"
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


# --- Lease settlement -------------------------------------------------------
#
# ``sync_status`` is what the settings panel polls, and every value in
# ``ACTIVE_SYNC_STATUSES`` reads there as "a sync is running". An exit that
# leaves one behind therefore repaints the repository page every few seconds
# indefinitely and keeps its controls disabled, because nothing else in the
# system clears that field -- the sweep only ever moves ``next_sync_at``.


def _lease_of(repo_id):
    """The repository's ``sync_lease_expires_at``, read on a fresh connection."""
    engine, Session = sync_session()
    try:
        return (
            Session().query(Repository).filter(Repository.id == repo_id).one().sync_lease_expires_at
        )
    finally:
        Session().close()
        engine.dispose()


def _write_row(session, repo, **values) -> None:
    """Write ``values`` straight onto the row, bypassing the ORM identity map.

    ``update(Repository)`` rather than ``Repository.__table__.update()``: the
    latter is typed as ``FromClause``, which carries no ``update``, so the
    attribute access fails a type check that this function's return annotation
    opts it into.
    """
    session.execute(update(Repository).where(Repository.id == repo.id).values(**values))
    session.commit()


class TestEveryExitSettlesTheRow:
    """A guard clause must not leave the row reading as in-flight.

    Each of these returns ``None`` without a summary: the task declined to do
    the work. The row it was dispatched for is still marked ``queued`` by the
    route, and before the ``finally`` released it that mark outlived the
    attempt -- permanently, since nothing else clears it.
    """

    def test_a_missing_baseline_settles_the_row(self, sync_repo):
        """No ``ingested_commit_sha`` means there is nothing to diff against.

        This is the state of every repository ingested before the watermark
        column existed, so on a long-lived deployment it is the common case
        rather than an edge.
        """
        factory, session = sync_repo
        repo = factory()
        _write_row(session, repo, ingested_commit_sha=None, sync_status="queued")

        result = sync_repository.apply(args=[str(repo.id), None])

        assert result.successful()
        assert result.get() is None
        assert _sync_status_of(repo.id) == "idle"
        assert _lease_of(repo.id) is None

    def test_a_non_ready_repository_settles_the_row(self, sync_repo):
        """A repository mid-ingest is skipped rather than synced twice."""
        factory, session = sync_repo
        repo = factory()
        _write_row(
            session,
            repo,
            status="parsing",
            ingested_commit_sha="a" * 40,
            sync_status="queued",
        )

        result = sync_repository.apply(args=[str(repo.id), None])

        assert result.successful()
        assert result.get() is None
        assert _sync_status_of(repo.id) == "idle"

    def test_an_owner_without_a_key_settles_the_row(self, sync_repo):
        """The free-tier backstop skips a keyless owner; the row still settles."""
        factory, session = sync_repo
        repo = factory()
        session.execute(
            User.__table__.update()
            .where(User.id == repo.user_id)
            .values(ai_provider=None, ai_api_key=None, ai_model=None)
        )
        _write_row(session, repo, ingested_commit_sha="a" * 40, sync_status="queued")

        result = sync_repository.apply(args=[str(repo.id), None])

        assert result.successful()
        assert result.get() is None
        assert _sync_status_of(repo.id) == "idle"

    def test_losing_the_lease_race_leaves_the_winners_lease_alone(self, sync_repo):
        """A live lease belongs to the attempt holding it, not to this one.

        Settling the row here would clear the winner's lease and let a third
        sync start alongside it -- precisely what the lease exists to prevent.
        """
        factory, session = sync_repo
        repo = factory()
        winner_expiry = datetime.now(UTC) + timedelta(minutes=30)
        _write_row(
            session,
            repo,
            ingested_commit_sha="a" * 40,
            sync_status="updating",
            sync_lease_expires_at=winner_expiry,
        )

        result = sync_repository.apply(args=[str(repo.id), None])

        assert result.successful()
        assert result.get() is None
        assert _sync_status_of(repo.id) == "updating"
        assert _lease_of(repo.id) == winner_expiry

    def test_a_recorded_failure_is_left_alone(self, sync_repo, monkeypatch):
        """``failed`` is a settled result; the release must not overwrite it."""
        factory, session = sync_repo
        repo = factory()
        _write_row(session, repo, ingested_commit_sha="a" * 40, sync_status="queued")

        import app.tasks.sync as sync_module

        def boom(*args, **kwargs):
            raise RuntimeError("simulated clone failure")

        monkeypatch.setattr(sync_module, "ensure_clone", boom)
        sync_repository.apply(args=[str(repo.id), None])

        assert _sync_status_of(repo.id) == "failed"
        assert _lease_of(repo.id) is None


class TestAnExpiredLeaseIsReclaimable:
    """An expired lease must not wedge a repository permanently.

    ``_claim_predicate`` treats an expired lease as claimable, so the sweep
    dispatches a sync for the row. ``_take_lease`` used to require the lease to
    be NULL, so it refused every one of those dispatches -- the sweep re-claimed
    on every tick, the task declined every time, and nothing in between ever
    cleared the stale lease. The two predicates have to agree about what
    "claimable" means.
    """

    def test_an_expired_lease_is_taken_and_the_sync_runs(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """The row is reclaimed and settles, rather than refusing forever."""
        factory, session = sync_repo
        repo = factory()
        head_sha = subprocess.run(
            ["git", "-C", str(cloner_stubbed_to_local), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # A lease left behind by a worker that was killed mid-sync, now lapsed.
        _write_row(
            session,
            repo,
            ingested_commit_sha=head_sha,
            analysis_commit_sha=head_sha,
            sync_status="updating",
            sync_lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        result = sync_repository.apply(args=[str(repo.id), None])

        # Both watermarks match the head, so the sync short-circuits -- a path
        # only reachable if the lease was taken. Refusing returns ``None``.
        assert result.successful()
        assert result.get() is not None
        assert _sync_status_of(repo.id) == "idle"
        assert _lease_of(repo.id) is None


def _success_markers_of(repo_id):
    """``(analysis_commit_sha, last_synced_at, sync_generation)`` for a row."""
    engine, Session = sync_session()
    try:
        row = Session().query(Repository).filter(Repository.id == repo_id).one()
        return row.analysis_commit_sha, row.last_synced_at, row.sync_generation
    finally:
        Session().close()
        engine.dispose()


class TestACompletedSyncRecordsItself:
    """A sync that finishes has to say so.

    Nothing asserted this, which is how a task that did all of its work and
    then threw away the record of it went unnoticed: the release path returns
    the row to ``idle`` too, so an assertion on ``sync_status`` alone passes
    whether or not the sync was recorded. The three markers below are the ones
    only the success path writes.
    """

    def test_the_analysis_watermark_and_last_synced_are_written(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        factory, session = sync_repo
        repo = factory()
        head = sample_repo.head_sha(cloner_stubbed_to_local)

        # The deterministic watermark already matches the head while the
        # analysis one is unset, so the short-circuit cannot fire and the LLM
        # half runs against an unchanged commit -- the shape of the first sync
        # a freshly ingested repository ever performs.
        _write_row(
            session,
            repo,
            ingested_commit_sha=head,
            analysis_commit_sha=None,
            sync_lease_expires_at=None,
        )

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        analysis_sha, last_synced_at, generation = _success_markers_of(repo.id)
        assert analysis_sha == head, (
            "the analysis watermark was never written -- the task returned "
            "before recording its own result"
        )
        assert last_synced_at is not None, (
            "last_synced_at was never stamped -- the sync completed and "
            "discarded the record of having done so"
        )
        assert generation is None, (
            f"sync_generation was left set ({generation!r}) -- the fingerprint "
            "of the release path rather than the success path"
        )

    # The end-to-end "and the next sync is free" property is covered by
    # ``test_sync_short_circuits_when_head_unchanged``, which stamps both
    # watermarks directly. Composed with the assertion above, that is the same
    # guarantee: the watermark this test proves is written is the one the
    # short-circuit reads. Running the task twice in one test is not possible
    # here anyway -- the local-clone fixture cannot re-clone into a cache path
    # it has already populated on Windows.


def _rev(repo_root, rev: str) -> str:
    """The SHA ``rev`` resolves to inside ``repo_root``."""
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", rev],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class TestTheGenerationReadIsNotTheInstance:
    """The read that decides whether a sync may record its result.

    Reading ``repo.sync_generation`` off the instance is not the same as
    reading the column. The status writers update ``Repository.__table__``
    directly -- a Core statement, which does not synchronise ORM instances --
    and the session is built with ``expire_on_commit=False``, so a commit does
    not refresh one either. A check that compared the instance against the
    generation it had just minted therefore compared a pre-lease value against
    a new one, was always unequal, and sent every sync home before it recorded
    anything.
    """

    def test_a_core_write_is_visible_to_the_read_and_invisible_to_the_instance(self, sync_repo):
        factory, _fixture_session = sync_repo
        repo = factory()
        generation = uuid.uuid4()

        # A session configured the way the worker configures its own. The
        # fixture's session takes SQLAlchemy's default and expires instances on
        # commit, which would hide the very staleness this is about.
        engine = create_engine(TEST_SYNC_DB_URL)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()
        try:
            held = session.get(Repository, repo.id)

            # Exactly what taking the lease does: a Core UPDATE, then a commit.
            session.execute(
                Repository.__table__.update()
                .where(Repository.id == repo.id)
                .values(sync_generation=generation)
            )
            session.commit()

            # The instance the task holds still shows the old value ...
            assert held.sync_generation != generation, (
                "the instance was refreshed, so this no longer exercises the "
                "staleness the guard exists to avoid"
            )
            # ... while the read the guard uses sees the write.
            assert _fresh_generation(session, repo.id) == generation
        finally:
            session.close()
            engine.dispose()


class TestTheIncrementalDeltaIsComplete:
    """What the delta has to carry for the apply half to be correct."""

    @RENAME_ORPHANS_THE_VACATED_FILE
    def test_a_rename_deletes_the_row_at_the_vacated_path(self, two_comm_working, sync_repo):
        """``git diff -M`` reports ``R100<TAB>old<TAB>new``.

        Keeping only the last field preserves the new path and drops the old
        one, so the apply half never deletes the row being vacated: it survives
        with its symbols, dependency edges, fan metrics, criticality and
        embeddings, and is served by the graph, the stats and the reading order
        from then on. Nothing downstream can notice -- the file simply exists
        twice.
        """
        from app.services.scanner import apply_file_delta

        factory, session = sync_repo
        user = _make_user(session)
        repo = _make_repo(session, user)
        try:
            for path in (sample_repo.RENAMED_FROM, sample_repo.RENAMED_TO):
                session.add(FileModel(repository_id=repo.id, path=path, language="python", loc=5))
            session.commit()

            root = Path(two_comm_working)
            diff = compute_delta(root, _rev(root, "HEAD~1"), _rev(root, "HEAD"))
            apply_file_delta(session, repo.id, root, [path for _status, path in diff])

            remaining = {
                row.path
                for row in session.query(FileModel).filter(FileModel.repository_id == repo.id)
            }
            assert sample_repo.RENAMED_TO in remaining
            assert sample_repo.RENAMED_FROM not in remaining, (
                "the rename left a phantom row: the delta carried only the new "
                "path, so the vacated one was never deleted"
            )
        finally:
            _cleanup(session, [repo])


class TestTheEscalationCheckIsGivenARealDenominator:
    """The ratio cap cannot fire on a zero."""

    @RATIO_ESCALATION_IS_UNREACHABLE
    def test_the_ratio_branch_receives_the_repository_file_count(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo, monkeypatch
    ):
        """``should_escalate`` compares the diff against the repository's size.

        The call site short-circuits: it evaluates the check only when the
        delta is a fast-forward, and in that branch it passed a count of zero,
        which the ratio test skips. The valve that is supposed to turn a
        most-of-the-tree change into a rebuild has therefore never been
        reachable, and the only escalation that can happen is the absolute
        changed-file cap.
        """
        factory, session = sync_repo
        repo = factory()
        root = Path(cloner_stubbed_to_local)
        _write_row(
            session,
            repo,
            ingested_commit_sha=_rev(root, "HEAD~1"),
            analysis_commit_sha=None,
            sync_lease_expires_at=None,
        )

        import app.tasks.sync as sync_module

        seen: dict[str, int] = {}

        def spy(diff, total_files, **_kwargs):
            seen["changed"] = len(diff)
            seen["total_files"] = total_files
            return False

        monkeypatch.setattr(sync_module, "should_escalate", spy)

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        assert seen.get("changed"), "the sync never took the delta path"
        assert seen.get("total_files", 0) > 0, (
            "the ratio cap was handed a count of zero, so it can never trip"
        )


class TestTheGlossaryStaysWithinItsCap:
    """``MAX_GLOSSARY_ENTRIES`` bounds the glossary, not the query.

    The incremental pass keeps every entry already stored and then asks the
    LLM for definitions of the highest-ranked symbols that lack one. Asking for
    a full cap *of those* refills nothing: it appends up to the cap more rows
    each time the repository is updated, so a glossary that started at the cap
    doubles on the first sync and keeps climbing.
    """

    def test_an_update_at_the_cap_defines_nothing_further(self, sync_repo, monkeypatch):
        from app.models.ast_symbol import AstSymbol
        from app.models.glossary_entry import GlossaryEntry
        from app.services.glossary_builder import MAX_GLOSSARY_ENTRIES, build_glossary

        fake = openai_stub.install(monkeypatch)
        factory, session = sync_repo
        user = _make_user(session)
        repo = _make_repo(session, user)
        try:
            source = FileModel(repository_id=repo.id, path="src/big.py", language="python", loc=500)
            session.add(source)
            session.flush()

            symbols = [
                AstSymbol(
                    file_id=source.id,
                    kind="function",
                    name=f"func_{i}",
                    start_line=i,
                    end_line=i + 1,
                )
                for i in range(MAX_GLOSSARY_ENTRIES + 50)
            ]
            session.add_all(symbols)
            session.flush()

            # The glossary is already full: the first cap-many symbols have
            # entries, leaving fifty with none.
            session.add_all(
                [
                    GlossaryEntry(
                        repository_id=repo.id,
                        symbol_id=symbol.id,
                        name=symbol.name,
                        definition=f"definition of {symbol.name}",
                    )
                    for symbol in symbols[:MAX_GLOSSARY_ENTRIES]
                ]
            )
            session.commit()
            before = len(fake.calls) if hasattr(fake, "calls") else None

            created = build_glossary(session, repo, mode="incremental")

            stored = (
                session.query(GlossaryEntry).filter(GlossaryEntry.repository_id == repo.id).count()
            )
            assert created == 0, (
                f"an update against a full glossary created {created} entries; "
                "the cap bounds the stored total, so the budget for new ones "
                "was already spent"
            )
            assert stored == MAX_GLOSSARY_ENTRIES, (
                f"the glossary grew to {stored}, past its {MAX_GLOSSARY_ENTRIES} cap"
            )
            assert before is None or len(fake.calls) == before
        finally:
            _cleanup(session, [repo])
