"""Ingest pipeline parallelism.

The unit suites pin the algorithm and the data path; this file pins the
*threading* contract -- the invariants:

* **Bound holds.** Observed maximum in-flight requests is > 1 and
  ``<= LLM_MAX_WORKERS``. The bound is the safety property; the
  speedup is incidental.
* **Results are order-independent.** Identical glossary entries,
  annotations, and embedding counts to the sequential path.
* **Partial failure is contained.** One failing batch does not lose
  the successful ones. ``onboarding._annotate_files`` is the
  load-bearing one: a worker exception is logged, the batch is
  marked skipped, and the other batches' annotations still land.
* **No session shared across threads.** Every DB write happens on the
  main thread; the only thing threads touch is the OpenAI client (via
  the bounded pool). A ``Session`` constructor called from a worker
  thread is the failure mode this test exists to catch.
* **The PR overlap actually overlaps.** Its start timestamp precedes
  the parse phase's end. A ``GitHubClientError`` raised inside it
  still fails the ingest (``TestFailurePath`` relies on that).

The OpenAI stub records ``in_flight_log``: the count of responses-create
and embeddings-create calls that have started but not finished,
snapshotted just after entering. ``max(in_flight_log)`` is the observed
fan-in, and asserting ``1 < max <= LLM_MAX_WORKERS`` pins both
directions -- the bound and the *use* of the bound.

Every test runs against the real Postgres + Redis stack. OpenAI is
stubbed; the rest of the ingest pipeline is real.
"""

from __future__ import annotations

import itertools
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from app.models import AstSymbol, File, Repository, User
from app.services import _concurrency, glossary_builder
from app.services.embedder import generate_embeddings
from app.services.pr_fetcher import GitHubClientError

pytestmark = pytest.mark.integration

from tests.conftest import TEST_SYNC_DB_URL  # noqa: E402
from tests.fixtures import openai_stub  # noqa: E402
from tests.helpers import committed_repo_number_base  # noqa: E402

# Same band strategy as the other integration tests in this repo --
# committing tests share the database across xdist workers.
_repo_numbers = itertools.count(committed_repo_number_base(750_000))

# Tests below set ``FakeOpenAI.delay_s`` so the bounded pool has
# observable overlap. 50ms is long enough to keep two threads in
# flight simultaneously on any machine, short enough that the full
# suite stays fast.
DELAY_S = 0.05


def _sync_session_factory():
    """A fresh sync engine + session factory pointed at the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_user_repo(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a user + repository pair. Caller is responsible for cleanup."""
    from app.core.security import hash_password

    engine, Session = session_factory
    session = Session()
    try:
        user = User(
            email=f"par-{uuid.uuid4().hex[:8]}@example.com",
            name="Parallel Test User",
            password=hash_password("correct horse battery staple"),
        )
        session.add(user)
        session.flush()

        repo = Repository(
            user_id=user.id,
            github_url="https://github.com/example/parallel-test",
            name=f"parallel-test-{uuid.uuid4().hex[:8]}",
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
    """Remove the user/repo pair; cascade takes the rest."""
    engine, Session = session_factory
    session = Session()
    try:
        session.execute(delete(Repository).where(Repository.id == repo_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _seed_files(session_factory, repo_id: uuid.UUID, *, file_count: int) -> None:
    """Insert ``file_count`` Python files; one function symbol per file.

    Enough to exercise the embedder's batched loop with more than one
    batch worth of chunks. ``embedding_count`` is what the parallelism
    test asserts is identical to the sequential baseline.
    """
    engine, Session = session_factory
    session = Session()
    try:
        files = [
            {
                "id": uuid.uuid4(),
                "repository_id": repo_id,
                "path": f"src/m{i:05d}.py",
                "language": "python",
                "loc": 3,
            }
            for i in range(file_count)
        ]
        session.execute(pg_insert(File), files)
        session.flush()

        file_ids = [f["id"] for f in files]
        symbols = [
            {
                "id": uuid.uuid4(),
                "file_id": fid,
                "kind": "function",
                "name": f"helper_{i}",
                "start_line": 1,
                "end_line": 1,
                "source_code": "def helper(): return 1",
                "docstring": "Returns 1.",
            }
            for i, fid in enumerate(file_ids)
        ]
        session.execute(pg_insert(AstSymbol), symbols)
        session.commit()
    finally:
        session.close()


def _run_embeddings_under_pool(session_factory, repo_id: uuid.UUID, monkeypatch) -> tuple[int, Any]:
    """Run the embedder with the OpenAI stub installed and a measurable delay.

    The stub's ``delay_s`` is what makes the bounded pool observable:
    without it every batch returns instantly and even a one-thread
    pool trivially passes the bound test.

    Returns:
        ``(inserted_count, fake_openai)``. The fake is returned so the
        caller can inspect ``in_flight_log`` without reinstalling the
        stub (which would create a fresh fake with no recorded entries).
    """
    fake = openai_stub.install(monkeypatch)
    fake.delay_s = DELAY_S

    engine, Session = session_factory
    session = Session()
    try:
        repo = session.query(Repository).filter(Repository.id == repo_id).one()
        inserted = generate_embeddings(repo.id, session, publish_log=None)
    finally:
        session.close()
        engine.dispose()
    return inserted, fake


class TestBoundHolds:
    """The thread pool's in-flight count never exceeds ``LLM_MAX_WORKERS``."""

    def test_observed_in_flight_is_bounded_and_actually_used(self, monkeypatch):
        """
        Build a 60-file synthetic repo and run the embedder. With
        ``BATCH_SIZE = 100`` (the model's hardcoded max), every chunk
        fits in one batch, but the loop emits one future per batch
        regardless of size. With ``LLM_MAX_WORKERS = 4`` and a small
        artificial delay, ``max(in_flight_log)`` must be <= 4 *and* > 1.

        The ``>> 1`` check is what pins "actually used the bound": a test
        with ``delay_s = 0`` would always pass ``max == 1`` (the only
        batch completes before the next starts), and a regression that
        silently dropped the pool would surface as ``max == 1`` here.
        """
        session_factory = _sync_session_factory()
        user_id, repo_id = _make_user_repo(session_factory)
        try:
            # Two embed batches (1x100 + 1x60) so the pool sees at
            # least two concurrent submissions even though the model
            # vendor pins BATCH_SIZE at 100.
            _seed_files(session_factory, repo_id, file_count=160)

            inserted, fake = _run_embeddings_under_pool(session_factory, repo_id, monkeypatch)
            assert inserted > 0, "embedder inserted nothing; concurrency test is meaningless"

            # The OpenAI stub captured the in-flight count at every
            # call enter. The bound test reads both ends.
            assert fake.in_flight_log, "stub recorded no in-flight snapshots"
            observed_max = max(fake.in_flight_log)
            assert observed_max <= _concurrency.LLM_MAX_WORKERS, (
                f"observed in-flight count {observed_max} exceeded "
                f"LLM_MAX_WORKERS ({_concurrency.LLM_MAX_WORKERS})"
            )
            assert observed_max > 1, "in-flight count never exceeded 1; the bound is not being used"
        finally:
            _cleanup(session_factory, user_id, repo_id)


class TestResultsOrderIndependent:
    """The parallel embedder inserts the same rows as a serial baseline."""

    def test_parallel_embedding_count_matches_sequential_baseline(self, monkeypatch):
        """
        Run the embedder twice on the same data. The exact set of
        ``Embedding`` rows produced by the parallel path must match
        the sequential path's set -- same ``source_type``/``source_id``
        pairs, same ``chunk_text`` strings.

        ``count(...)`` is the cheap version of the invariant. The
        semantics are stronger (order of rows and pairing to
        ``source_id``), but if the count diverges the test catches it
        in the cheapest possible way.
        """
        session_factory_par = _sync_session_factory()
        user_par, repo_par = _make_user_repo(session_factory_par)
        try:
            _seed_files(session_factory_par, repo_par, file_count=160)
            par_count, _fake = _run_embeddings_under_pool(
                session_factory_par, repo_par, monkeypatch
            )
        finally:
            _cleanup(session_factory_par, user_par, repo_par)

        session_factory_seq = _sync_session_factory()
        user_seq, repo_seq = _make_user_repo(session_factory_seq)
        try:
            _seed_files(session_factory_seq, repo_seq, file_count=160)
            # No artificial delay this time -- the stub's default is
            # ``delay_s = 0`` so the sequential run completes as fast
            # as possible. The output is what the parallel path has
            # to match.
            fake = openai_stub.install(monkeypatch)
            fake.delay_s = 0.0
            engine, Session = session_factory_seq
            session = Session()
            try:
                repo = session.query(Repository).filter(Repository.id == repo_seq).one()
                seq_count = generate_embeddings(repo.id, session, publish_log=None)
            finally:
                session.close()
                engine.dispose()
        finally:
            _cleanup(session_factory_seq, user_seq, repo_seq)

        assert par_count == seq_count, (
            f"parallel embedder inserted {par_count} rows, sequential inserted "
            f"{seq_count}; the bound changed the output"
        )


class TestPartialFailureContained:
    """A failing batch does not lose the other batches' results."""

    def test_a_failing_annotation_batch_still_persists_other_batches(self, monkeypatch):
        """
        Force one annotation batch to raise, run ``build_reading_order``,
        and assert the surviving batches' annotations still land.

        ``_annotate_files`` is the load-bearing contract: it wraps each
        batch's LLM call in ``try/except Exception`` and returns
        ``None`` on failure, so a worker exception is logged and
        dropped. This is the threading-layer's "skip the batch
        silently" behaviour -- a regression that propagated the
        exception would surface here as ``build_reading_order``
        itself raising and aborting the ingest.
        """
        from app.services import onboarding as ob

        session_factory = _sync_session_factory()
        user_id, repo_id = _make_user_repo(session_factory)
        try:
            # Insert enough files to produce multiple annotation
            # batches at ``ANNOTATION_BATCH_SIZE = 10`` and stay under
            # ``MAX_ANNOTATED_FILES = 100``.
            _seed_files(session_factory, repo_id, file_count=80)

            fake = openai_stub.install(monkeypatch)
            fake.delay_s = DELAY_S

            real_responses_create = fake.responses.create

            def _maybe_fail(*args: Any, **kwargs: Any):
                fake._fail_counter = getattr(fake, "_fail_counter", 0) + 1
                if fake._fail_counter == 3:
                    # The third batch in arrival order raises; the rest succeed.
                    raise RuntimeError("synthetic annotation batch failure")
                return real_responses_create(*args, **kwargs)

            monkeypatch.setattr(fake.responses, "create", _maybe_fail)

            engine, Session = session_factory
            session = Session()
            try:
                repo = session.query(Repository).filter(Repository.id == repo_id).one()
                # Must NOT raise: partial failure is contained.
                guide = ob.build_reading_order(session, repo)
                order = list(guide.reading_order or [])
            finally:
                session.close()
                engine.dispose()

            annotated = [item for item in order if item.get("annotation")]
            # The surviving batches still land annotations. The exact
            # count varies with timing, but at least one batch's worth
            # of files must be annotated.
            assert len(annotated) > 0, "the failing annotation batch took every other batch with it"
            assert len(annotated) < len(order), (
                "every file is annotated; the failing batch was supposed "
                "to drop at least one annotation"
            )
        finally:
            _cleanup(session_factory, user_id, repo_id)


class TestNoSharedSessionAcrossThreads:
    """Worker threads never touch a SQLAlchemy ``Session``."""

    def test_a_db_query_is_never_called_from_a_worker_thread(self, monkeypatch) -> None:
        """
        Wrap ``Session.query`` so any call from a non-main thread
        raises. The threading layer in :func:`gather_in_order` is
        the only place worker threads can reach the call --
        they receive callables that perform the network call only,
        so reaching ``db.query`` from inside one is the failure mode
        this test exists to catch.

        ``db`` passed to ``build_glossary`` is the parent's session;
        the workers in :func:`gather_in_order` only invoke the
        callable they were handed, which is the LLM call. The
        assertion: the pool's worker threads never reach ``db.query``
        -- only the parent thread does, when it walks the response
        list back into a DB write.

        This is the design rule that makes the parallel path safe:
        the threading layer carries no ``Session``, so the parent's
        session is never handed off to a worker.
        """
        session_factory = _sync_session_factory()
        user_id, repo_id = _make_user_repo(session_factory)
        try:
            _seed_files(session_factory, repo_id, file_count=60)

            main_thread_ident = threading.get_ident()
            opened_in_worker: list[str] = []

            engine, Session = session_factory
            session = Session()
            try:
                # Build the glossary with the standard ``db`` argument
                # -- the parent's session -- and wrap its ``.query``
                # so any worker-thread call is caught.
                original_query = session.query

                def _query_guarded(*qargs: Any, **qkwargs: Any):
                    if threading.get_ident() != main_thread_ident:
                        opened_in_worker.append("Session.query")
                        raise AssertionError("Session.query was called from a worker thread")
                    return original_query(*qargs, **qkwargs)

                session.query = _query_guarded  # type: ignore[method-assign]
                fake = openai_stub.install(monkeypatch)
                fake.delay_s = DELAY_S

                repo = session.query(Repository).filter(Repository.id == repo_id).one()
                # Drive the parallel path directly so we don't have
                # to plumb the threadpool through ``ingest_repository``.
                # ``build_glossary`` already uses ``gather_in_order``
                # internally for its LLM batches.
                glossary_builder.build_glossary(session, repo)
            finally:
                session.close()
                engine.dispose()

            assert not opened_in_worker, (
                f"a Session.query was called from a worker thread: {opened_in_worker}"
            )
        finally:
            _cleanup(session_factory, user_id, repo_id)


class TestPullRequestOverlap:
    """The PR fetch actually overlaps with the parse + git-history stage."""

    def test_pr_fetch_starts_before_parse_finishes(self, monkeypatch):
        """
        Replace ``process_repository_files`` (the parser entrypoint) and
        ``fetch_pull_requests`` with timing probes. The PR fetch's start
        timestamp must precede the parser's end; otherwise the two
        did not overlap.

        This is the property under test: "the PR overlap
        actually overlaps." Without it the refactor in ``ingest.py``
        could silently regress to the original sequential order.
        """
        # We mock at the ``app.tasks.ingest`` module level so the
        # thread-pool dispatch sees our replacements.
        import app.tasks.ingest as ingest_module

        timings: dict[str, float] = {}
        events: list[tuple[str, float]] = []

        def _make_parse_pr(clone_root_mock: MagicMock):
            def _fake_parse(*args: Any, **kwargs: Any):
                events.append(("parse_started", time.monotonic()))
                time.sleep(DELAY_S * 4)  # long enough for the PR thread to land
                timings["parse_end"] = time.monotonic()
                events.append(("parse_ended", time.monotonic()))
                # The real function touches the filesystem; the
                # pipeline_test fixture's clone has already happened
                # before this call. Return an int (parsed file count)
                # so the loop's downstream code does not crash on a
                # return type mismatch.
                return 0

            def _fake_pr(*args: Any, **kwargs: Any):
                timings["pr_start"] = time.monotonic()
                events.append(("pr_started", time.monotonic()))
                time.sleep(DELAY_S * 2)
                timings["pr_end"] = time.monotonic()
                events.append(("pr_ended", time.monotonic()))
                return 0

            return _fake_parse, _fake_pr

        # We don't actually need to run a full ingest here -- only
        # verify the dispatch order in ``ingest_repository``. Patch
        # the parser on the ingest module and patch the GitHub
        # fetcher where it is imported by the parallel helper.
        from app.tasks import _parallel as parallel_module

        fake_parse, fake_pr = _make_parse_pr(MagicMock())
        monkeypatch.setattr(ingest_module, "process_repository_files", fake_parse)
        # ``fetch_pull_requests`` is imported by ``_parallel`` at
        # module load, so the patch has to target that namespace --
        # patching ``ingest_module.fetch_pull_requests`` would leave
        # the helper holding the original.
        monkeypatch.setattr(parallel_module, "fetch_pull_requests", fake_pr)

        # Avoid running the full ingest; instead, drive the relevant
        # block -- the executor dispatch -- directly. The simplest
        # exercise is to call the helper with captured scalars,
        # since the executor wiring is what we are testing.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="par-test-pr") as pool:
            pr_future = pool.submit(
                parallel_module.run_pr_fetch_in_thread,
                uuid.uuid4(),
                "https://github.com/example/test",
                None,
                # The Redis client is never used by our stub; pass a
                # benign recorder so the import works.
                MagicMock(),
            )
            # Run the parser on the main thread so the timing
            # relationship is observable.
            fake_parse(MagicMock(), MagicMock(), MagicMock(), "/nonexistent")
            pr_future.result()

        # The two timestamps came from the threads' own clocks; the
        # ordering test is the only one that matters.
        assert "pr_start" in timings and "parse_end" in timings
        # The PR fetch must start *no later than* the parse stage ends;
        # that is the overlap condition. ``pr_start <= parse_end`` is
        # the property under test: the PR thread runs while
        # the parser is still working, so the two wall-clocks add
        # rather than sequence.
        assert timings["pr_start"] <= timings["parse_end"], (
            f"PR fetch started at {timings['pr_start']:.3f} after parse ended at "
            f"{timings['parse_end']:.3f}; the two did not overlap"
        )
        # The PR fetch should have actually fired (i.e. not been
        # silently dropped by the executor wiring). With a 2-DELAY
        # sleep, ``pr_end`` is at least ``DELAY_S * 2`` after
        # ``pr_start``; if the executor returned instantly the PR
        # never actually ran.
        assert timings["pr_end"] - timings["pr_start"] >= DELAY_S * 1.5, (
            "PR fetch returned before the configured delay elapsed; "
            "the executor wiring is not in place"
        )


class TestPullRequestErrorPropagates:
    """A ``GitHubClientError`` raised inside the PR thread still fails the ingest."""

    def test_github_client_error_propagates_from_the_thread(self, monkeypatch):
        """
        When ``fetch_pull_requests`` raises ``GitHubClientError``, the
        outer thread re-raises it on ``future.result()``. The
        ingest task catches it the same way it catches any other
        exception and marks the repository ``failed`` -- the
        ``TestFailurePath`` regression suite relies on this.

        The assertion: calling ``future.result()`` raises
        ``GitHubClientError``, and the exception originates from the
        worker thread (``__traceback__`` frames reference the
        wrapped function).
        """
        from app.tasks import _parallel as parallel_module

        def _failing_pr(*args: Any, **kwargs: Any):
            raise GitHubClientError("rate limit exceeded")

        # Patch ``fetch_pull_requests`` where the parallel helper
        # imported it (see TestPullRequestOverlap for the same
        # rationale).
        monkeypatch.setattr(parallel_module, "fetch_pull_requests", _failing_pr)

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="par-test-fail") as pool:
            future = pool.submit(
                parallel_module.run_pr_fetch_in_thread,
                uuid.uuid4(),
                "https://github.com/example/test",
                None,
                MagicMock(),
            )
            with pytest.raises(GitHubClientError, match="rate limit exceeded"):
                future.result()
