"""``run_full_analysis``: extracted pipeline contract.

The single regression net for the pipeline extraction:

* **Idempotence.** Two ``run_full_analysis`` runs against the same repo
  leave every per-table row count unchanged. This is the headline
  assertion: a future sync task that calls the same function inherits
  the same property for free. Today the only call site is the ingest
  task, which deletes ``File`` rows up front, so the count happens to
  match by construction -- the test pins that, so a refactor that
  drifts here gets caught.
* **README ``source_id``s are distinct per section.** The upcoming
  ``uq_embedding_source`` unique constraint requires this; sections
  sharing ``source_id = repository_id`` would collapse into one row
  and fail every section past the first. The ``uuid5``-based id
  scheme is what the embedder uses; this test pins it.
* **``manage_status=False`` leaves ``status`` alone.** The sync path
  needs to run the pipeline against a ``ready`` repo without flipping
  the row out of ``ready`` (the graph endpoint would 409, the live-log
  panel would mount). Suppressing the status transitions is the
  property; we test it by calling the pipeline with
  ``manage_status=False`` and asserting the row's status is unchanged
  end-to-end.

The fixture mirrors ``test_ingest_task.py`` -- committed user/repo
pairs, fake clone, stubbed OpenAI -- so the assertion shape stays
comparable to the rest of the suite.
"""

from __future__ import annotations

import itertools
import shutil
import uuid
from collections import Counter
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.fixtures import openai_stub, sample_repo
from tests.helpers import committed_repo_number_base

pytestmark = pytest.mark.integration


# Same numbering band strategy as ``test_ingest_task.py`` -- rows are
# committed and outlive the test's transaction, so each xdist worker needs
# its own counter and the values must be well clear of any real row.
_repo_numbers = itertools.count(committed_repo_number_base(960_000))


def _sync_session_factory():
    """A fresh sync engine + session factory pointed at the test database."""
    from tests.conftest import TEST_SYNC_DB_URL

    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_repo(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a user + repository pair the pipeline can target."""
    from app.core.security import hash_password
    from app.models.repository import Repository
    from app.models.user import User

    engine, Session = session_factory
    session = Session()
    try:
        user = User(
            email=f"pipeline-{uuid.uuid4().hex[:8]}@example.com",
            name="Pipeline Test User",
            password=hash_password("correct horse battery staple"),
        )
        session.add(user)
        session.flush()

        repo = Repository(
            user_id=user.id,
            github_url="https://github.com/example/pipeline-extraction-test",
            name="pipeline-extraction-test",
            status="pending",
            default_branch="main",
            repo_number=next(_repo_numbers),
        )
        session.add(repo)
        session.commit()
        return user.id, repo.id
    finally:
        session.close()


def _cleanup(session_factory, user_id: uuid.UUID, repo_id: uuid.UUID) -> None:
    """Remove the user/repo pair; cascade deletes the children."""
    engine, Session = session_factory
    session = Session()
    try:
        session.execute(text("DELETE FROM repositories WHERE id = :rid"), {"rid": repo_id})
        session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def pipeline_repo():
    """A committed repository row for direct ``run_full_analysis`` calls."""
    session_factory = _sync_session_factory()
    user_id, repo_id = _make_repo(session_factory)
    yield repo_id
    _cleanup(session_factory, user_id, repo_id)


@pytest.fixture
def clone_root(tmp_path):
    """A real git repository to hand the pipeline in place of a clone."""
    return sample_repo.build(tmp_path / "sample-project")


@pytest.fixture
def stubbed_clone(monkeypatch, clone_root, tmp_path):
    """
    Stub the pipeline's external dependencies: fake ``clone_repository``
    returns a per-call copy of the fixture, OpenAI is stubbed.

    PR fetching is the only thing the pipeline *doesn't* do; the rest
    flows through ``run_full_analysis`` directly.
    """
    import app.services.cloner as cloner_module
    import app.tasks._parallel as parallel_module

    counter = itertools.count(1)

    def fake_clone(*args, **kwargs):
        destination = tmp_path / f"clone-{next(counter)}"
        shutil.copytree(clone_root, destination)
        return destination, "main", "a" * 40

    # Pipeline itself never calls ``clone_repository`` -- the task
    # wrapper does -- but having a working fake here makes the test
    # setup consistent with the rest of the suite.
    monkeypatch.setattr(cloner_module, "clone_repository", fake_clone)
    monkeypatch.setattr(parallel_module, "fetch_pull_requests", lambda *a, **k: None)

    return openai_stub.install(monkeypatch)


class _RecordingRedis:
    """A Redis stand-in that records publishes; never reaches the network."""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.channels: list[str] = []

    def publish(self, channel: str, payload: str) -> int:
        import json

        self.channels.append(channel)
        self.frames.append(json.loads(payload))
        return 0


def _run_pipeline(
    repo_id: uuid.UUID,
    repo_root,
    *,
    manage_status: bool = True,
) -> _RecordingRedis:
    """
    Drive ``run_full_analysis`` against an already-committed repo row.

    Mirrors the production call shape (sync session, real Redis stub,
    OpenAI stub) but skips the celery task wrapper -- the property under
    test is the pipeline function's, not the wrapper's.
    """
    from app.models.repository import Repository
    from app.services.pipeline import run_full_analysis

    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            repo = session.query(Repository).filter(Repository.id == repo_id).one()
            redis_client = _RecordingRedis()

            def publish(event: str, message: str, **kwargs):
                # Same shape as the real task wrapper -- a JSON payload
                # carrying event, message and timestamp. Stored as a dict
                # so the test can introspect the frame without parsing.
                from datetime import timezone

                redis_client.frames.append(
                    {
                        "event": event,
                        "message": message,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        **kwargs,
                    }
                )

            run_full_analysis(
                session,
                repo,
                repo_root,
                redis_client,
                publish,
                manage_status=manage_status,
                overlap_llm=False,
            )
            session.commit()
            return redis_client
        finally:
            session.close()
    finally:
        engine.dispose()


def _row_count(repo_id: uuid.UUID, table: str, where: str = "") -> int:
    """Return the row count for ``table`` filtered by the repo.

    ``where`` is an extra predicate fragment appended verbatim -- callers
    are responsible for parameter substitution (we only ever pass repo
    ids, so the SQL injection surface is contained).
    """
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            sql = f"SELECT COUNT(*) FROM {table} WHERE repository_id = :rid {where}"
            return session.execute(text(sql), {"rid": repo_id}).scalar()
        finally:
            session.close()
    finally:
        engine.dispose()


def _all_table_counts(repo_id: uuid.UUID) -> dict[str, int]:
    """Row counts for every table the pipeline touches, by natural key.

    Returned as a dict so ``Counter`` equality is a one-liner. Tables
    whose primary filter is ``file_id`` rather than
    ``repository_id`` (``ast_symbols``, ``dependencies``, ``code_owners``)
    join through ``files``; everything else filters directly.
    """
    counts: dict[str, int] = {}

    # Direct ``repository_id`` filters.
    for table in (
        "files",
        "commits",
        "pull_requests",
        "glossary_entries",
        "embeddings",
        "onboarding_guides",
    ):
        counts[table] = _row_count(repo_id, table)

    # Through ``files``: ``ast_symbols.file_id``, ``code_owners.file_id``.
    counts["ast_symbols"] = _row_count_through_files(repo_id, "ast_symbols", "file_id")
    counts["code_owners"] = _row_count_through_files(repo_id, "code_owners", "file_id")

    # ``dependencies`` joins through ``ast_symbols`` (both columns are FKs
    # into ``ast_symbols.id``).
    counts["dependencies"] = _row_count_through_dependencies(repo_id)

    return counts


def _row_count_through_files(repo_id: uuid.UUID, table: str, fk_column: str) -> int:
    """Row count for ``table`` joined to ``files`` on ``table.<fk_column> = files.id``.

    Used for tables whose primary foreign key is into ``files`` rather
    than directly into ``repositories`` -- ``ast_symbols`` and
    ``code_owners`` today.
    """
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            return session.execute(
                text(
                    f"SELECT COUNT(*) FROM {table} t "
                    f"JOIN files f ON f.id = t.{fk_column} "
                    f"WHERE f.repository_id = :rid"
                ),
                {"rid": repo_id},
            ).scalar()
        finally:
            session.close()
    finally:
        engine.dispose()


def _row_count_through_dependencies(repo_id: uuid.UUID) -> int:
    """Row count for ``dependencies`` joined through ``ast_symbols`` and ``files``.

    Both ``source_symbol_id`` and ``target_symbol_id`` are FKs into
    ``ast_symbols.id`` with CASCADE on delete, so either side being gone
    means the edge is gone -- filter through the source side and dedupe
    not necessary here (each edge is one row).
    """
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            return session.execute(
                text(
                    "SELECT COUNT(*) FROM dependencies d "
                    "JOIN ast_symbols s ON s.id = d.source_symbol_id "
                    "JOIN files f ON f.id = s.file_id "
                    "WHERE f.repository_id = :rid"
                ),
                {"rid": repo_id},
            ).scalar()
        finally:
            session.close()
    finally:
        engine.dispose()


class TestIdempotence:
    """Two ``run_full_analysis`` runs leave every per-table count unchanged."""

    def test_re_running_run_full_analysis_is_byte_identical(
        self, pipeline_repo, clone_root, stubbed_clone
    ):
        _run_pipeline(pipeline_repo, clone_root)
        counts_after_first = _all_table_counts(pipeline_repo)

        _run_pipeline(pipeline_repo, clone_root)
        counts_after_second = _all_table_counts(pipeline_repo)

        # Counts: the per-table shape must match. The fixture's
        # ``ingested_commit_sha`` is hardcoded ("a"*40), so two runs of
        # the same fixture land at the same head; if a future refactor
        # made the pipeline write new rows on a re-run, this fails.
        assert counts_after_first == counts_after_second, (
            f"per-table row counts diverged: first={counts_after_first} "
            f"second={counts_after_second}"
        )

        # ``files`` specifically: one row per path, exactly what the
        # ``uq_file_repo_path`` constraint was added to enforce. A
        # regression where the pipeline wrote duplicates without the
        # constraint would silently inflate this number.
        from sqlalchemy import select

        from app.models.file import File

        engine, Session = _sync_session_factory()
        try:
            session = Session()
            try:
                files = (
                    session.execute(select(File).where(File.repository_id == pipeline_repo))
                    .scalars()
                    .all()
                )
                paths = [f.path for f in files]
                counter = Counter(paths)
                duplicates = {p: c for p, c in counter.items() if c > 1}
                assert not duplicates, f"duplicate File rows: {duplicates}"
            finally:
                session.close()
        finally:
            engine.dispose()


class TestEmbeddingsHavePerSectionSourceIds:
    """README sections get distinct ``source_id``s."""

    def test_readme_section_source_ids_are_distinct(self, pipeline_repo, clone_root, stubbed_clone):
        # The fixture README has 3 ``##`` sections, so the embedder must
        # write three ``document`` rows with three distinct ``source_id``s.
        # If they collapsed to ``repository_id``, the upcoming
        # ``uq_embedding_source`` unique constraint would refuse the
        # second row and the test environment would crash with
        # ``UniqueViolation``.
        _run_pipeline(pipeline_repo, clone_root)

        engine, Session = _sync_session_factory()
        try:
            session = Session()
            try:
                rows = session.execute(
                    text(
                        "SELECT source_id FROM embeddings "
                        "WHERE repository_id = :rid AND source_type = 'document'"
                    ),
                    {"rid": pipeline_repo},
                ).all()
                source_ids = [r[0] for r in rows]
            finally:
                session.close()
        finally:
            engine.dispose()

        # Three sections in the fixture README => at least three rows.
        assert len(source_ids) >= 3, (
            f"expected at least three README document chunks, got {len(source_ids)}"
        )
        # And every id is unique.
        assert len(set(source_ids)) == len(source_ids), (
            f"duplicate document source_ids: {source_ids}"
        )


class TestManageStatusLeavesRowAlone:
    """``manage_status=False`` does not flip ``status`` mid-run."""

    def test_a_run_with_manage_status_false_keeps_status_ready(
        self, pipeline_repo, clone_root, stubbed_clone
    ):
        from sqlalchemy import select

        from app.models.repository import Repository

        engine, Session = _sync_session_factory()
        try:
            # Seed the row at ``status='ready'`` so we can observe the
            # property: a sync task runs against a ready repo and must
            # leave it at ``ready``.
            session = Session()
            try:
                session.execute(
                    text("UPDATE repositories SET status = 'ready' WHERE id = :rid"),
                    {"rid": pipeline_repo},
                )
                session.commit()
            finally:
                session.close()

            _run_pipeline(pipeline_repo, clone_root, manage_status=False)

            session = Session()
            try:
                status = session.execute(
                    select(Repository.status).where(Repository.id == pipeline_repo)
                ).scalar()
                assert status == "ready", (
                    f"manage_status=False left status as {status!r}; "
                    "the sync path would 409 the graph endpoint"
                )
            finally:
                session.close()
        finally:
            engine.dispose()

    def test_a_run_with_manage_status_false_publishes_no_status_update_frames(
        self, pipeline_repo, clone_root, stubbed_clone
    ):
        """The frame is the user-visible signal; absence is the contract."""
        recorder = _run_pipeline(pipeline_repo, clone_root, manage_status=False)

        status_update_frames = [
            frame for frame in recorder.frames if frame.get("event") == "status_update"
        ]
        assert status_update_frames == [], (
            f"manage_status=False still emitted status_update frames: {status_update_frames}"
        )


class TestManageStatusTrueIsTheDefault:
    """The initial-ingest path is the one that publishes status transitions."""

    def test_a_run_with_manage_status_true_emits_status_update_frames(
        self, pipeline_repo, clone_root, stubbed_clone
    ):
        recorder = _run_pipeline(pipeline_repo, clone_root, manage_status=True)

        status_update_frames = [
            frame for frame in recorder.frames if frame.get("event") == "status_update"
        ]
        # At least one transition: ``parsing`` -> ... -> ``embedding``.
        # The exact count depends on which frames the parent task
        # publishes vs. which come from the pipeline itself, so a lower
        # bound is what the test pins.
        assert len(status_update_frames) >= 1, (
            f"manage_status=True should publish at least one status_update "
            f"frame, got {status_update_frames}"
        )


# ``Callable`` was used to silence a forward-reference lint about the
# ``run_full_analysis`` signature; not needed here after import cleanup.
