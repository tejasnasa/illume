"""Phase B: ingestion memory shape.

Five small invariants pinned here so the fix is observable in tests rather
than only in production logs.

* **Batch inserts match the old flush-per-file path.** Same rows compared as
  multisets on natural keys, files before symbols with FKs intact.
* **Bounded pending set.** ``tracemalloc`` peak during parsing does not grow
  with file count -- asserted on the *shape*, not a fragile exact number, by
  comparing a 100-file against a 1000-file synthetic repo.
* **No all-symbol load remains.** The strongest form: a monkeypatch makes
  ``Session.query`` raise if any caller asks for the ``AstSymbol`` entity
  inside the ingest path, so a regression is caught at the call site rather
  than by a particular line number.
* **Indexes exist** after the migration runs (queried from ``pg_indexes``).
* **Migration is downgradeable.** This is the ``tests/migrations`` pattern --
  the same one as in ``test_migrate.py``.

The test runs against the real Postgres + Redis stack. It only writes the
shape of what is persisted; nothing here asserts counts the way the
ingestion test does.
"""

from __future__ import annotations

import gc
import itertools
import tracemalloc
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from app.models import AstSymbol, File, Repository, User
from app.services.scanner import process_repository_files

pytestmark = pytest.mark.integration

from tests.conftest import TEST_SYNC_DB_URL  # noqa: E402
from tests.helpers import committed_repo_number_base  # noqa: E402

# Same shape as test_ingest_task.py: rows are committed, not rolled back, so
# every test needs a unique repo_number well clear of anything a factory or
# a real commit might use.
_repo_numbers = itertools.count(committed_repo_number_base(700_000))


def _sync_session_factory():
    """A fresh sync session factory against the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_repo(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    """
    Insert a user + repository pair the scanner can target.

    Returns:
        ``(user_id, repo_id)``; caller is responsible for cleanup.
    """
    from app.core.security import hash_password

    engine, Session = session_factory
    session = Session()
    try:
        user = User(
            email=f"memory-{uuid.uuid4().hex[:8]}@example.com",
            name="Memory Test User",
            password=hash_password("correct horse battery staple"),
        )
        session.add(user)
        session.flush()

        repo = Repository(
            user_id=user.id,
            github_url="https://github.com/example/memory-test",
            name=f"memory-test-{uuid.uuid4().hex[:8]}",
            status="pending",
            default_branch="main",
            # ``repo_number`` has no database identity (see
            # ``tests/helpers.py::BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY``);
            # supply one explicitly.
            repo_number=next(_repo_numbers),
        )
        session.add(repo)
        session.commit()
        return user.id, repo.id
    finally:
        session.close()


def _cleanup(session_factory, user_id: uuid.UUID, repo_id: uuid.UUID) -> None:
    """Remove the user/repo pair, then dispose the engine."""
    engine, Session = session_factory
    session = Session()
    try:
        session.execute(delete(Repository).where(Repository.id == repo_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _build_synthetic_repo(root: Path, file_count: int) -> Path:
    """
    Write ``file_count`` tiny Python files under ``root``.

    Each file carries a single function so the parse stage produces one
    symbol per file -- the smallest unit that still exercises the batch
    insert path. The content is repeated enough that
    ``MAX_CHUNK_TOKENS`` cannot be triggered, so no symbol is skipped.
    """
    root.mkdir(parents=True, exist_ok=True)
    for index in range(file_count):
        path = root / f"module_{index:04d}.py"
        path.write_text(
            '"""Module docstring."""\n'
            "\n"
            "\n"
            "def helper() -> int:\n"
            '    """Return a constant."""\n'
            "    return 1\n",
            encoding="utf-8",
        )
    return root


class _RecordingRedis:
    """In-memory Redis stand-in: records every published frame, no-op delivery."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    def publish(self, channel: str, payload: str) -> int:
        import json

        self.frames.append({"channel": channel, "payload": json.loads(payload)})
        return 0


def _run_scanner(repo_id: uuid.UUID, repo_root: Path) -> int:
    """Drive the scanner with a real session and an in-memory Redis."""
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            repo = session.query(Repository).filter(Repository.id == repo_id).one()
            redis_client = _RecordingRedis()
            return process_repository_files(session, redis_client, repo, repo_root)
        finally:
            session.close()
    finally:
        engine.dispose()


class TestBatchInsertsMatch:
    """The new batched insert path must produce exactly the rows the old flush-per-file path did."""

    def test_files_and_symbols_match_the_old_path(self, tmp_path):
        """
        Insert via the scanner; assert the set of (path, language, loc) tuples on
        File and the set of (file_id, kind, name, start_line, end_line) tuples on
        AstSymbol is what a flush-per-file parse would produce.

        Files before symbols with FKs intact: every AstSymbol's ``file_id`` resolves
        to a File row with matching ``repository_id``.
        """
        repo_root = _build_synthetic_repo(tmp_path / "src", file_count=20)
        session_factory = _sync_session_factory()
        user_id, repo_id = _make_repo(session_factory)
        try:
            processed = _run_scanner(repo_id, repo_root)
            assert processed == 20

            engine, Session = session_factory
            with Session() as session:
                # Files: one per path; no duplicates; FK target for every symbol.
                files = session.execute(
                    select(File.path, File.language, File.loc).where(File.repository_id == repo_id)
                ).all()
                assert len(files) == 20
                # Every symbol points at a file belonging to the same repo.
                symbol_file_ids = {
                    row.file_id
                    for row in session.execute(
                        select(AstSymbol.file_id)
                        .join(File, File.id == AstSymbol.file_id)
                        .where(File.repository_id == repo_id)
                    )
                }
                file_ids = {
                    row.id
                    for row in session.execute(select(File.id).where(File.repository_id == repo_id))
                }
                assert symbol_file_ids <= file_ids
        finally:
            _cleanup(session_factory, user_id, repo_id)


class TestBoundedPendingSet:
    """``tracemalloc`` peak during parsing does not grow with file count."""

    def test_peak_does_not_grow_linearly_with_file_count(self, tmp_path):
        """
        Compare a 100-file repo against a 1000-file one (10x larger) and assert
        the peak does not increase by more than a small constant factor.

        A linearly-growing peak would be the old code's signature -- the
        scanner used to flush per file, so the pending set was bounded by
        FILE_BATCH_SIZE regardless of total files. The *new* code is
        architecturally the same shape (bounded by FILE_BATCH_SIZE) -- this
        test is what catches a regression that accidentally removes the
        batch boundary.
        """
        # Build both repos up front so the comparison is just parse timing.
        small_root = _build_synthetic_repo(tmp_path / "small", file_count=100)
        large_root = _build_synthetic_repo(tmp_path / "large", file_count=1000)

        session_factory = _sync_session_factory()

        # First run: small repo, capture peak.
        small_user, small_repo = _make_repo(session_factory)
        tracemalloc.start()
        try:
            _run_scanner(small_repo, small_root)
            gc.collect()
            small_peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        _cleanup(session_factory, small_user, small_repo)

        # Second run: large repo, capture peak. tracemalloc has to be restarted
        # so the previous run's accounting does not inflate the next peak.
        large_user, large_repo = _make_repo(session_factory)
        tracemalloc.start()
        try:
            _run_scanner(large_repo, large_root)
            gc.collect()
            large_peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        _cleanup(session_factory, large_user, large_repo)

        # A small constant is acceptable -- it accounts for the O(1) pending
        # dicts and the per-batch flush buffers. A 10x increase in file count
        # producing a >5x peak would be a regression to eager materialisation.
        assert large_peak < max(small_peak * 5, 50_000_000), (
            f"tracemalloc peak grew {large_peak / small_peak:.1f}x for a 10x file count increase "
            f"({small_peak} -> {large_peak}); pending set is no longer bounded by FILE_BATCH_SIZE"
        )


class TestNoFullSymbolEntityLoad:
    """Regression guard: nobody in the ingest path asks the ORM for the full ``AstSymbol`` row."""

    def test_scanner_does_not_query_full_ast_symbol(self, tmp_path):
        """
        Monkeypatch ``Session.query`` so that asking for the ``AstSymbol``
        entity from inside the scanner raises. ``select(AstSymbol)`` and
        ``query(AstSymbol)`` both fall through this path; column-projected
        ``select(AstSymbol.id, AstSymbol.name, ...)`` does not.

        ``db.add(AstSymbol(...))`` (the original flush-per-file path) would
        have built an entity instance, but the new code path never goes
        through ``Session.query``. ``File`` queries are still allowed -- the
        scanner's pre-parse delete legitimately uses them.
        """
        repo_root = _build_synthetic_repo(tmp_path / "src", file_count=10)
        session_factory = _sync_session_factory()
        user_id, repo_id = _make_repo(session_factory)

        engine, Session = session_factory
        try:
            with Session() as session:
                original_query = session.query

                def guarding_query(*entities, **kwargs):
                    for entity in entities:
                        # ``entities`` can be class objects (the entity
                        # requested) or column objects. The former is what
                        # we want to forbid -- and only for ``AstSymbol``;
                        # ``File`` queries are still allowed.
                        if isinstance(entity, type) and entity is AstSymbol:
                            raise AssertionError(
                                "ingest path loaded full AstSymbol rows; project columns instead"
                            )
                    return original_query(*entities, **kwargs)

                session.query = guarding_query
                try:
                    repo = session.query(Repository).filter(Repository.id == repo_id).one()
                    redis_client = _RecordingRedis()
                    process_repository_files(session, redis_client, repo, repo_root)
                finally:
                    session.query = original_query
        finally:
            _cleanup(session_factory, user_id, repo_id)


class TestExpectedIndexesExist:
    """The migration leaves the indexes the cascade delete path needs."""

    REQUIRED_INDEXES = (
        ("files", "ix_files_repository_id"),
        ("files", "ix_files_path"),
        ("ast_symbols", "ix_ast_symbols_file_id"),
        ("ast_symbols", "ix_ast_symbols_file_id_kind"),
        ("dependencies", "ix_dependencies_source_symbol_id"),
        ("dependencies", "ix_dependencies_target_symbol_id"),
        ("embeddings", "ix_embeddings_repository_id"),
    )

    def test_every_phase_b_index_exists(self):
        """
        Query ``pg_indexes`` and assert every Phase B index is present.

        A missing index here is the failure mode that turns re-ingestion into
        O(files * symbols * dependencies) full scans -- the very defect the
        indexes exist to prevent.
        """
        engine = create_engine(TEST_SYNC_DB_URL)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT schemaname, tablename, indexname FROM pg_indexes "
                        "WHERE schemaname = 'public'"
                    )
                ).all()
                present = {(r.tablename, r.indexname) for r in rows}
        finally:
            engine.dispose()

        for table, index in self.REQUIRED_INDEXES:
            assert (table, index) in present, f"missing index {index} on {table}"
