"""The full ingestion pipeline, run eagerly.

This is the test that catches failures in code paths that only execute during a real
ingestion -- a `TypeError` in the statement immediately before `status = "ready"`, or a
`NameError` in the first real work of the parse stage. Neither is visible to a
route-level test, because the route only dispatches the task.

Everything external is stubbed and everything internal is real:

* **git** is real -- a temporary repository built by `tests/fixtures/sample_repo.py`.
* **OpenAI** is stubbed (`tests/fixtures/openai_stub.py`).
* **GitHub** is stubbed: `fetch_pull_requests` does not run.
* **Postgres and Redis** are the real test stack.

Because the task uses the *sync* session (psycopg2) and commits, its rows outlive the
test's transaction. The `pipeline_repo` fixture inserts and removes them with an explicit
sync session, and teardown is asserted rather than assumed.
"""

import itertools
import uuid
from datetime import UTC, datetime

import pytest

from tests.fixtures import openai_stub, sample_repo
from tests.helpers import committed_repo_number_base

pytestmark = pytest.mark.integration

# Well clear of both the factory counter and any real row, since these rows are committed
# rather than rolled back. Offset per xdist worker: this module is imported separately in
# every worker, so a bare constant has all of them allocating the same numbers.
_repo_numbers = itertools.count(committed_repo_number_base(950_000))


def sync_session():
    """A short-lived sync session against the test database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import TEST_SYNC_DB_URL

    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


@pytest.fixture
def pipeline_repo():
    """
    A committed repository row the eager task can pick up.

    Committed on purpose: the task opens its own session, so a row left in the test's
    transaction would be invisible to it. `repo_number` is supplied explicitly because
    the column has no database-side generator. Teardown deletes the row and lets the
    cascade take the children.
    """
    engine, Session = sync_session()
    session = Session()

    from app.core.security import hash_password
    from app.models.repository import Repository
    from app.models.user import User

    user = User(
        email=f"pipeline-{uuid.uuid4().hex[:8]}@example.com",
        name="Pipeline User",
        password=hash_password("correct horse battery staple"),
    )
    session.add(user)
    session.flush()

    repo = Repository(
        user_id=user.id,
        github_url="https://github.com/example/sample-project",
        name="sample-project",
        status="pending",
        default_branch="main",
        repo_number=next(_repo_numbers),
    )
    session.add(repo)
    session.commit()
    repo_id = repo.id
    user_id = user.id
    session.close()

    yield repo_id

    session = Session()
    try:
        session.query(Repository).filter(Repository.id == repo_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def clone_root(tmp_path):
    """A real git repository standing in for a completed clone."""
    return sample_repo.build(tmp_path / "sample-project")


@pytest.fixture
def stubbed(monkeypatch, clone_root, tmp_path):
    """
    Replace the task's external dependencies, in the task's own namespace.

    `ingest.py` does `from app.services.cloner import clone_repository`, so it holds a
    direct reference to the function. Patching `app.services.cloner` would leave the
    task calling the original.
    """
    import shutil

    import app.tasks.ingest as ingest_module

    counter = itertools.count(1)

    def fake_clone(db, redis_client, repo, access_token, branch=None, commit_sha=None):
        """
        Hand back a fresh copy of the fixture repository.

        A copy per call, because the task deletes the clone in a `finally` -- pointing
        every call at the fixture itself meant the second run of a test found no
        repository at all. Copying also mirrors the real return type:
        `cloner.clone_repository` returns `Path(tmp_dir)`, and handing back a string here
        made `detect_stack` fail on `.rglob`, which looked like a product bug and was not
        one.
        """
        destination = tmp_path / f"clone-{next(counter)}"
        shutil.copytree(clone_root, destination)
        return destination, "main", "a" * 40

    monkeypatch.setattr(ingest_module, "clone_repository", fake_clone)
    # ``fetch_pull_requests`` is imported by the parallel helper, not by
    # ``ingest`` itself; patching the helper's namespace is what makes
    # the ingest thread run a no-op instead of hitting the network.
    from app.tasks import _parallel as parallel_module

    monkeypatch.setattr(parallel_module, "fetch_pull_requests", lambda *a, **k: None)

    fake_openai = openai_stub.install(monkeypatch)
    return fake_openai


def run_task(repo_id):
    """Execute `ingest_repository` synchronously, in-process."""
    from app.tasks.ingest import ingest_repository

    return ingest_repository.apply(args=[str(repo_id), None])


class TestHappyPath:
    def test_a_repository_reaches_ready(self, pipeline_repo, stubbed):
        """
        The headline assertion: ingestion ends with the repository in `ready`, which is
        the gate the graph, chat, and export routes all check.
        """
        run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "ready"

    def test_files_are_indexed(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)

        assert file_count(pipeline_repo) >= len(sample_repo.FILES) - 1

    def test_both_languages_are_present(self, pipeline_repo, stubbed):
        """The fixture is polyglot; a single-language result means a grammar is not wired."""
        run_task(pipeline_repo)

        assert languages_of(pipeline_repo) >= {"python", "typescript"}

    def test_class_methods_are_extracted(self, pipeline_repo, stubbed):
        """
        End-to-end confirmation that methods are indexed at all. Before the class body
        was opened by the traversal, no method anywhere in any repository was ever
        indexed, and this is the shortest path that proves otherwise.
        """
        run_task(pipeline_repo)

        names = symbol_names(pipeline_repo)

        assert {"describe", "is_large"} <= names  # on Report
        assert {"scan", "largest"} <= names  # on Scanner

    def test_the_entry_point_is_detected(self, pipeline_repo, stubbed):
        """
        `stack_detector` looks for `if __name__ == "__main__"` and similar. `main.py` has
        one, so the brief has something to anchor a data-flow trace to.
        """
        run_task(pipeline_repo)

        assert "entry_points" in (brief_of(pipeline_repo) or {})

    def test_a_glossary_is_generated(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)

        assert glossary_count(pipeline_repo) > 0

    def test_a_reading_order_is_generated(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)

        order = reading_order_of(pipeline_repo)
        assert order
        assert [item["position"] for item in order] == sorted(item["position"] for item in order)

    def test_the_guide_holds_the_architecture_brief(self, pipeline_repo, stubbed):
        """
        The first failure was a `TypeError` here -- `generate_brief` passed keyword
        arguments that `_upsert_guide` did not accept. The follow-on was subtler: even
        with the call fixed, the brief was discarded rather than persisted.
        """
        run_task(pipeline_repo)

        brief = brief_of(pipeline_repo)
        assert brief, "the architecture brief was never persisted"
        assert brief.get("entry_points") is not None

    def test_the_reading_order_survives_the_brief_pass(self, pipeline_repo, stubbed):
        """
        The two passes write the same row: `build_reading_order` first, then
        `generate_brief`. Whichever runs second must not blank the other's columns.
        """
        run_task(pipeline_repo)

        assert reading_order_of(pipeline_repo), "the brief pass overwrote the reading order"
        assert brief_of(pipeline_repo), "the reading-order pass overwrote the brief"

    def test_embeddings_are_written(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)

        assert embedding_count(pipeline_repo) > 0

    def test_embedded_chunk_text_is_rendered_output_not_raw_source(self, pipeline_repo, stubbed):
        """
        `embedder` stores a labelled, pre-rendered chunk rather than the source file. If
        raw source were stored instead, retrieval would have no file names or callers to
        match against.
        """
        run_task(pipeline_repo)

        chunks = chunk_texts(pipeline_repo)
        assert any(chunk.startswith("File:") or "File:" in chunk for chunk in chunks)

    def test_an_oversized_symbol_chunk_is_dropped_not_truncated(self, pipeline_repo, stubbed):
        """
        The `MAX_CHUNK_TOKENS` path, which had no coverage at any level: before this the
        constant appeared nine times in `embedder.py` and not once in `tests/`.

        `src/oversized.py` renders to ~2,700 estimated tokens against a 2,048 limit, so its
        symbol chunk is dropped rather than cut short -- a truncated chunk would embed
        misleading partial code. The assertion is on a line from deep in the body, because
        the *name* still appears in the file-level chunk below.

        Note what this test does not claim. The file is **not** invisible to search: an
        annotated file gets a second, short chunk built from its path, its reading-order
        note, and its symbol names, and that one is well under the limit. So the oversized
        source is simply absent while the file stays findable, which is the design working.

        The remaining uncovered case is narrower and needs a synthetic repository: a file
        that is oversized *and* has no reading-order annotation (because it is past
        `onboarding.MAX_ANNOTATED_FILES`, or the guide omitted it) has neither route.
        """
        run_task(pipeline_repo)

        chunks = chunk_texts(pipeline_repo)

        # Dropped, not truncated: no line of the body survives anywhere in the index.
        assert not any("value_549 = 549" in chunk for chunk in chunks)
        # Control: a normal file's symbol chunk *does* carry its source, so the absence
        # above is the size rule rather than symbol chunks never containing source.
        assert any("def slugify" in chunk for chunk in chunks)
        # And the file is still reachable, through its annotated-file chunk.
        assert "src/oversized.py" in embedded_file_paths(pipeline_repo)

    def test_docstrings_are_extracted_end_to_end(self, pipeline_repo, stubbed):
        """
        End-to-end confirmation that ``ParsedSymbol.docstring`` survives the
        scanner's batched insert and lands in the database. The fixture has
        five positive declarations (decorated function, one-liner,
        method-in-class, class, ``/** JSDoc */ export function``, JSDoc
        class, multi-line ``//``-arrow) and two negatives (license header,
        far-apart ``# TODO``) which the run must surface with ``None``.

        The second half of the test pins the dead read: ``glossary_builder``
        consumes ``symbol.docstring`` to build its prompt, so a missing
        column would render the prompt without the ``Docstring:`` line.
        That is a silent regression the suite would otherwise not catch.
        """
        run_task(pipeline_repo)

        docs = docstrings_by_name(pipeline_repo)

        # Positives: every named declaration in the fixture's two docstring
        # files carries a docstring.
        assert docs.get("static_helper") == (
            "A decorated helper. Tests that the decorator wrapper is "
            "unwrapped before the body is read."
        )
        assert docs.get("one_liner") == "A one-line docstring."
        assert docs.get("Greeter") == (
            "A class that says hello. Tests that the class body's first string is captured."
        )
        assert (
            docs.get("greet") == "Build a greeting. Tests that a method inside a class is captured."
        )
        assert docs.get("titleCaseDoc") == "Render a title in title case."
        assert (
            docs.get("buildEndpoint") == "Build a URL from the endpoint.\nValidates the path first."
        )
        assert docs.get("DocumentedClient") == "The documented client."

        # Negatives: license header and far-apart TODO are not attached.
        # The fixture's positive cases in the same files (``real_one`` has
        # its own real docstring below the license) must still come through.
        assert docs.get("real_one") == ("This is the function's actual docstring, not the license.")
        assert docs.get("without_docstring") is None

        # And the dead read: glossary_builder consumes symbol.docstring, so
        # the prompt it builds must contain the rendered docstring text.
        from app.models.ast_symbol import AstSymbol
        from app.models.file import File
        from app.services.glossary_builder import _build_prompt

        engine, Session = sync_session()
        session = Session()
        try:
            row = (
                session.query(AstSymbol, File)
                .join(File, File.id == AstSymbol.file_id)
                .filter(File.repository_id == pipeline_repo)
                .filter(AstSymbol.name == "static_helper")
                .one()
            )
            prompt = _build_prompt([row])
        finally:
            session.close()
            engine.dispose()

        assert "A decorated helper." in prompt
        assert "Docstring:" in prompt

    def test_the_commit_history_is_stored(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)

        assert commit_count(pipeline_repo) == 2  # the fixture makes exactly two

    def test_a_commit_message_containing_a_pipe_is_not_truncated(self, pipeline_repo, stubbed):
        """
        End-to-end confirmation that a commit message survives the parse. `git log` is
        read with a control-character field separator, and the fixture's second commit
        message contains a `|` specifically to catch a regression back to splitting on it.
        """
        run_task(pipeline_repo)

        messages = commit_messages(pipeline_repo)
        assert "feat: move helper into a package | also add late.py" in messages

    def test_a_commit_date_is_the_authored_date_not_the_analysis_time(self, pipeline_repo, stubbed):
        """
        The other half of the same defect: when the date failed to parse it degraded to
        `now()`, so a wrong timestamp silently propagated into `git_last_modified` and the
        criticality score. The fixture's commits are authored in the past, so a timestamp
        within the last minute would mean the fallback fired.
        """
        run_task(pipeline_repo)

        now = datetime.now(UTC)
        for authored_at in commit_dates(pipeline_repo):
            assert (now - authored_at).total_seconds() > 60

    def test_a_file_moved_into_a_subdirectory_is_tracked(self, pipeline_repo, stubbed):
        """
        End-to-end confirmation that a one-sided rename is normalised. Git renders the
        move as `src/{ => pkg}/nested.py`; unnormalised, the braces survived into the path,
        no `File.path` matched, and the file was silently skipped by ownership, churn, and
        last-modified updates.
        """
        run_task(pipeline_repo)

        assert "src/pkg/nested.py" in file_paths(pipeline_repo)

    def test_ownership_is_recorded_for_the_moved_file(self, pipeline_repo, stubbed):
        """The consequence of an unmatched path: no `CodeOwner` row at all."""
        run_task(pipeline_repo)

        owners = ownership_paths(pipeline_repo)
        assert "src/pkg/nested.py" in owners

    def test_a_non_ascii_file_name_is_indexed(self, pipeline_repo, stubbed):
        """
        The fixture carries `src/café.py`. Nothing else in the suite produces a path that
        is not encodable as ASCII, so this is what pins that the walk, the
        `relative_to(root).as_posix()` every `File.path` is built from, and the ownership
        matching keyed on the same string all survive one.
        """
        run_task(pipeline_repo)

        assert "src/café.py" in file_paths(pipeline_repo)

    def test_an_unparseable_file_is_skipped_rather_than_fatal(self, pipeline_repo, stubbed):
        """
        `src/broken.ipynb` is malformed JSON, so `parse_notebook` returns None and
        `process_repository_files` takes its "unparseable or unsupported file; skip rather
        than abort the run" branch.

        That branch had no coverage at any level before this. `parse_file` returns None
        only for an unsupported extension, an unreadable file, or a rejected notebook -- a
        file full of *syntax errors* still parses, because tree-sitter is error-tolerant.
        So the run reaching `ready` with the file absent is what proves one bad file is
        skipped rather than fatal.
        """
        result = run_task(pipeline_repo)

        assert result.successful()
        assert status_of(pipeline_repo) == "ready"
        assert "src/broken.ipynb" not in file_paths(pipeline_repo)

    def test_both_halves_of_a_dependency_cycle_are_ordered(self, pipeline_repo, stubbed):
        """
        `src/cycle_a.py` and `src/cycle_b.py` import each other. `_topological_sort`
        documents that "files inside dependency cycles are appended as a final tier"; the
        rest of the fixture is a DAG, so without these two that branch was only ever read.

        The assertion that carries the weight is that both land in the *same* tier. If only
        one direction of the import had been resolved there would be no cycle to detect,
        and the two files would be ordered into separate tiers instead.

        Note the key: the stored entry uses `path`, not `file_path`. The endpoint renames
        it on the way out, so the same value answers to two different names depending on
        which side of the API you are on.
        """
        run_task(pipeline_repo)

        assert {"src/cycle_a.py", "src/cycle_b.py"} <= file_paths(pipeline_repo)

        order = reading_order_of(pipeline_repo)
        assert order

        entries = {
            entry["path"]: entry
            for entry in order
            if entry["path"] in {"src/cycle_a.py", "src/cycle_b.py"}
        }
        assert set(entries) == {"src/cycle_a.py", "src/cycle_b.py"}, (
            "a cycle file never reached the order"
        )

        # Non-vacuity. Two files with *no* resolved imports would also share a tier, since
        # neither would be waiting on the other. A fan-in of at least one on both files is
        # the evidence that the imports became edges in each direction -- which is what
        # makes it a cycle rather than two unrelated files. (fan_out is no longer in the
        # stored payload after Phase D; read it from the File table directly.)
        for path in ("src/cycle_a.py", "src/cycle_b.py"):
            assert entries[path]["fan_in"] >= 1, f"{path} has no incoming edge"
            assert fan_out_of(pipeline_repo, path) >= 1, f"{path} has no outgoing edge"

        assert entries["src/cycle_a.py"]["tier"] == entries["src/cycle_b.py"]["tier"]

    def test_the_fixture_notebook_is_really_unparseable(self, tmp_path):
        """
        Control for the test above, and the reason it is not vacuous.

        `parse_file` returning None is what triggers the skip branch. If the malformed
        notebook were silently *readable* -- or if it were never written at all -- the
        integration test would still pass on an absent file, but for the wrong reason.
        This asserts both halves directly: the file exists in the built fixture, and
        `parse_file` rejects it.
        """
        from app.services.parser import parse_file

        root = sample_repo.build(tmp_path / "notebook-check")
        notebook = root / "src/broken.ipynb"

        assert notebook.exists()
        assert parse_file(notebook) is None

    def test_status_transitions_are_published(self, pipeline_repo, stubbed, monkeypatch):
        """
        Progress events are what the WebSocket relays, so the client's live log depends
        on these being emitted with the documented channel and shape.
        """
        published = published_frames(pipeline_repo, monkeypatch)

        assert any('"status": "ready"' in frame for frame in published)

    def test_the_terminal_marker_is_a_json_frame(self, pipeline_repo, stubbed, monkeypatch):
        """
        The completion marker is published through the same JSON-encoding helper as every
        other event, so it arrives as an object carrying `message: "DONE"` -- not as the
        bare string. The socket and the client both compare against the bare string, so
        neither recognises it.

        Pinned here, at the publisher, because this is the half of the disagreement that
        is unambiguous: whatever the consumers decide to match on, this is what goes over
        the wire.
        """
        import json

        published = published_frames(pipeline_repo, monkeypatch)

        markers = [
            json.loads(frame)["message"]
            for frame in published
            if frame not in ("DONE", "ERROR") and json.loads(frame)["message"] in ("DONE", "ERROR")
        ]
        assert markers == ["DONE"]
        assert "DONE" not in published  # never the bare string

    def test_every_frame_is_json_with_a_timestamp(self, pipeline_repo, stubbed, monkeypatch):
        """
        The client parses each frame. `DONE` and `ERROR` are the only bare strings the
        task emits; everything else must be a JSON object carrying a timestamp.
        """
        import json

        published = published_frames(pipeline_repo, monkeypatch)

        for frame in published:
            if frame in ("DONE", "ERROR"):
                continue
            parsed = json.loads(frame)
            assert "timestamp" in parsed
            assert "message" in parsed

    def test_frames_go_to_the_repository_channel(self, pipeline_repo, stubbed, monkeypatch):
        import app.tasks.ingest as ingest_module

        recorder = RecordingRedis()
        monkeypatch.setattr(ingest_module, "get_sync_redis", lambda: recorder)
        run_task(pipeline_repo)

        assert set(recorder.channels) == {f"task:{pipeline_repo}:logs"}

    def test_the_celery_task_succeeds(self, pipeline_repo, stubbed):
        result = run_task(pipeline_repo)

        assert result.successful()


def _explode(message: str):
    """A replacement for a task dependency that raises."""

    def _raiser(*args, **kwargs):
        raise RuntimeError(message)

    return _raiser


class TestFailurePath:
    """
    Eager retries do not surface as a raised exception.

    `self.retry` re-runs the task in-process up to `max_retries`, so `apply()` returns an
    `EagerResult` whose `failed()` is True rather than propagating. Assertions are on that
    result and on the repository's status, which is what a user would actually see.
    """

    def test_a_clone_failure_marks_the_repository_failed(self, pipeline_repo, monkeypatch, stubbed):
        import app.tasks.ingest as ingest_module

        monkeypatch.setattr(
            ingest_module, "clone_repository", _explode("clone failed: repository not found")
        )

        run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "failed"

    def test_a_clone_failure_fails_the_task(self, pipeline_repo, monkeypatch, stubbed):
        import app.tasks.ingest as ingest_module

        monkeypatch.setattr(ingest_module, "clone_repository", _explode("clone failed"))

        assert run_task(pipeline_repo).failed()

    def test_a_clone_failure_publishes_an_error_marker(self, pipeline_repo, monkeypatch, stubbed):
        """
        The failure marker is JSON-encoded too, so it is found by its `message` field
        rather than as a bare string -- the same shape mismatch the socket and the client
        have with the bare terminal string.
        """
        import json

        import app.tasks.ingest as ingest_module

        monkeypatch.setattr(ingest_module, "clone_repository", _explode("clone failed"))

        published = published_frames(pipeline_repo, monkeypatch)

        messages = [json.loads(frame)["message"] for frame in published if frame.startswith("{")]
        assert "ERROR" in messages
        assert any("clone failed" in message for message in messages)

    def test_the_error_message_reaches_the_client(self, pipeline_repo, monkeypatch, stubbed):
        """The published error is what the user sees in the terminal panel."""
        import app.tasks.ingest as ingest_module

        monkeypatch.setattr(ingest_module, "clone_repository", _explode("distinctive failure text"))

        published = published_frames(pipeline_repo, monkeypatch)

        assert any("distinctive failure text" in frame for frame in published)

    def test_it_retries_three_times(self, pipeline_repo, monkeypatch, stubbed):
        """
        `max_retries=3` means four attempts in total: the original plus three retries. A
        transient clone failure is expected to survive all of them, and the count is worth
        pinning because it is the only bound on how long a bad repository ties up a worker.
        """
        import app.tasks.ingest as ingest_module

        attempts = []

        def counting_clone(*args, **kwargs):
            attempts.append(1)
            raise RuntimeError("clone failed")

        monkeypatch.setattr(ingest_module, "clone_repository", counting_clone)

        run_task(pipeline_repo)

        assert len(attempts) == 4

    def test_an_empty_clone_fails_the_run(self, pipeline_repo, monkeypatch, stubbed, tmp_path):
        """
        A clone that succeeds but contains nothing is not a success. The repository must
        not be left `ready` with no files behind it.
        """
        import app.tasks.ingest as ingest_module

        empty = tmp_path / "empty-clone"
        empty.mkdir()
        monkeypatch.setattr(
            ingest_module,
            "clone_repository",
            lambda *a, **k: (empty, "main", "a" * 40),
        )

        run_task(pipeline_repo)

        assert status_of(pipeline_repo) != "ready"

    def test_a_missing_repository_is_an_error(self, stubbed, pipeline_repo):
        """
        The task is dispatched by id, so a row deleted between dispatch and execution is a
        real race. It must fail rather than half-run against nothing.
        """
        assert run_task(uuid.uuid4()).failed()

    def test_no_partial_ready_state(self, pipeline_repo, monkeypatch, stubbed):
        """A failed run must not leave the repository readable as `ready`."""
        import app.tasks.ingest as ingest_module

        monkeypatch.setattr(ingest_module, "clone_repository", _explode("boom"))

        run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "failed"

    def test_a_failure_does_not_leave_a_guide_behind(self, pipeline_repo, monkeypatch, stubbed):
        """The guide is written last, so a mid-pipeline failure must leave none."""
        import app.tasks.ingest as ingest_module

        monkeypatch.setattr(ingest_module, "clone_repository", _explode("boom"))

        run_task(pipeline_repo)

        assert guide_of(pipeline_repo) is None


class TestReRun:
    """
    What a second execution does to rows the first one already wrote.

    The task retries itself up to three times on any exception, and the retry re-runs the
    whole body -- so "a second execution" is not a hypothetical, it is what happens on the
    first transient OpenAI or GitHub error.
    """

    def test_re_running_does_not_duplicate_files(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)
        first = file_count(pipeline_repo)

        run_task(pipeline_repo)

        assert file_count(pipeline_repo) == first

    def test_re_running_does_not_duplicate_symbols(self, pipeline_repo, stubbed):
        run_task(pipeline_repo)
        first = symbol_count(pipeline_repo)

        run_task(pipeline_repo)

        assert symbol_count(pipeline_repo) == first

    def test_re_running_does_not_duplicate_dependencies(self, pipeline_repo, stubbed):
        """Fan-in and fan-out are derived from these, so a doubled edge set inflates them."""
        run_task(pipeline_repo)
        first = dependency_count(pipeline_repo)

        run_task(pipeline_repo)

        assert dependency_count(pipeline_repo) == first

    def test_re_running_does_not_duplicate_file_paths(self, pipeline_repo, stubbed):
        """
        Stated as the invariant that actually matters: one `File` row per path per
        repository. The `files` table has no `UNIQUE (repository_id, path)`, so nothing in
        the schema enforces it.
        """
        run_task(pipeline_repo)
        run_task(pipeline_repo)

        paths = file_paths(pipeline_repo)
        all_rows = file_row_count(pipeline_repo)

        assert all_rows == len(paths)

    def test_re_running_still_ends_ready(self, pipeline_repo, stubbed):
        """
        The control for the four above: a second run completes successfully. The defect is
        that it duplicates, not that it fails -- which is why it went unnoticed, since the
        repository still reports `ready`.
        """
        run_task(pipeline_repo)
        run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "ready"

    def test_re_running_keeps_commit_rows_singular(self, pipeline_repo, stubbed):
        """
        Commits are inserted with `ON CONFLICT DO NOTHING` on `(repository_id, hash)`, so
        this stage *is* idempotent. It is the contrast that shows the problem is specific
        to the parse stage rather than to re-running as such.
        """
        run_task(pipeline_repo)
        first = commit_count(pipeline_repo)

        run_task(pipeline_repo)

        assert commit_count(pipeline_repo) == first


class TestFailurePathLeavesRepoFailed:
    """
    When a stage raises after a flush has hit the database, the session is in
    a pending-rollback state. The task must ``rollback()`` before reloading the
    repository; otherwise ``status = "failed"`` never persists and the row
    stays at ``parsing``/``embedding`` forever, while the user sees a
    ``failed`` terminal frame over the WebSocket.

    Defect 1 in `improve_plan.md`.
    """

    def test_a_mid_pipeline_failure_marks_the_repository_failed(
        self, pipeline_repo, monkeypatch, stubbed
    ):
        """
        Patch ``process_repository_files`` to dirty the session with an
        uncommitted insert, then raise. The task's except path is reached
        with a poisoned transaction: pre-fix the reload query raises
        ``PendingRollbackError``, which the bare ``except Exception: pass``
        swallows, and the row stays in its last stage forever. Post-fix the
        explicit ``db.rollback()`` clears the session and ``status =
        "failed"`` persists.
        """
        from sqlalchemy.exc import DBAPIError

        # ``process_repository_files`` is now called from
        # ``app.services.pipeline.run_full_analysis``; patch the binding on
        # the module that *calls* it, the same way the ``_parallel`` patches
        # target the importing namespace rather than the service.
        import app.services.pipeline as pipeline_module

        def explode_after_flush(db, redis_client, repo, repo_root):
            # Stage a row in the same session without committing, then raise
            # -- reproducing the exact "pending-rollback" state a real flush
            # failure would leave behind.
            from app.models.file import File

            db.add(
                File(
                    repository_id=repo.id,
                    path="src/__defect1__.py",
                    language="python",
                    loc=1,
                )
            )
            db.flush()  # forces a round trip; any later query needs a rollback
            raise DBAPIError("simulated flush failure", None, Exception())

        monkeypatch.setattr(pipeline_module, "process_repository_files", explode_after_flush)

        run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "failed"

    def test_a_brief_failure_marks_the_repository_failed(self, pipeline_repo, monkeypatch, stubbed):
        """
        The architecture brief runs in its own thread, overlapped with the
        embedder, so its exception surfaces through ``future.result()``
        rather than a direct call. The task must still fail.

        The failure mode this pins is a swallowed future: if the join were
        dropped, or its exception logged and discarded, the ingest would
        reach ``status = "ready"`` with no architecture brief and no error --
        a repository that looks complete and silently is not. Asserting on
        the status rather than the row is deliberate, because the brief's own
        writes land on its own session and would be absent in either case.
        """
        from app.tasks import _parallel as parallel_module

        def _explode_brief(*args, **kwargs):
            raise RuntimeError("simulated brief failure")

        # Patched where ``_parallel`` imported it, not on the service module:
        # the helper holds its own bound reference.
        monkeypatch.setattr(parallel_module, "generate_brief", _explode_brief)

        result = run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "failed"
        assert result.failed(), "a swallowed brief exception would leave the task successful"

    def test_a_failed_run_does_not_poison_the_session(self, pipeline_repo, monkeypatch, stubbed):
        """
        After a failed ingestion a subsequent run of the same repository must
        still succeed. This proves the session is reusable, not just that the
        status row got its label flipped.
        """
        from sqlalchemy.exc import DBAPIError

        # ``process_repository_files`` is now called from
        # ``app.services.pipeline.run_full_analysis``; patch the binding on
        # the module that *calls* it.
        import app.services.pipeline as pipeline_module
        import app.services.scanner as scanner_module

        # First invocation: simulate the failure.
        def explode(db, redis_client, repo, repo_root):
            from app.models.file import File

            db.add(
                File(
                    repository_id=repo.id,
                    path="src/__defect1_b__.py",
                    language="python",
                    loc=1,
                )
            )
            db.flush()
            raise DBAPIError("simulated flush failure", None, Exception())

        monkeypatch.setattr(pipeline_module, "process_repository_files", explode)

        run_task(pipeline_repo)
        assert status_of(pipeline_repo) == "failed"

        # Second invocation: restore the real ``process_repository_files`` but
        # leave the ``stubbed`` fixture (fake clone, OpenAI stub) in place so
        # the recovery run does not reach out to GitHub.
        monkeypatch.setattr(
            pipeline_module,
            "process_repository_files",
            scanner_module.process_repository_files,
        )
        run_task(pipeline_repo)

        assert status_of(pipeline_repo) == "ready"


class TestCriticalitySeesRealData:
    """
    Criticality scoring reads ``File.git_last_modified`` and ``File.has_tests``,
    both populated by ``analyze_git_history``. Running it before that stage hit
    NULL/False values and effectively never fired the volatility or coverage
    rules.

    Defect 2 in `improve_plan.md`.
    """

    def test_criticality_runs_after_git_history_so_modified_is_set(self, pipeline_repo, stubbed):
        """
        Run the happy path, then read back ``File.git_last_modified`` to
        confirm git analysis populated it before criticality ran. The fixture's
        first commit is intentionally stale enough to cross the 180-day
        threshold, which means the staleness rule *should* be capable of
        firing once the column is non-NULL.
        """
        from datetime import UTC, datetime

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.file import File
        from tests.conftest import TEST_SYNC_DB_URL

        run_task(pipeline_repo)

        engine = create_engine(TEST_SYNC_DB_URL)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            files = session.query(File).filter(File.repository_id == pipeline_repo).all()
            assert files, "no files indexed"

            timestamps = [f.git_last_modified for f in files if f.git_last_modified is not None]
            assert timestamps, (
                "git_last_modified is NULL on every file -- criticality ran "
                "before git analysis populated the column"
            )

            stale_count = sum(1 for ts in timestamps if (datetime.now(UTC) - ts).days > 180)
            assert stale_count > 0, (
                "no file is older than 180 days -- the fixture should be old "
                "enough for at least one staleness flag"
            )
        finally:
            session.close()
            engine.dispose()

    def test_calibration_does_not_penalise_repos_without_tests(self, pipeline_repo, stubbed):
        """
        The fixture has no test files. With the calibration in place the
        no-coverage penalty must NOT fire, so scores should reflect only
        fan-in, path patterns, and staleness.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.file import File
        from tests.conftest import TEST_SYNC_DB_URL

        run_task(pipeline_repo)

        engine = create_engine(TEST_SYNC_DB_URL)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            files = session.query(File).filter(File.repository_id == pipeline_repo).all()
            for f in files:
                reasons = f.criticality_reasons or []
                # The fixture has no test files: every no-test-coverage
                # reason we see is a regression of the calibration.
                assert "no test coverage" not in reasons, (
                    f"{f.path} was scored as untested in a repo with no tests -- "
                    "the no-coverage penalty should be silent when the repo "
                    "as a whole has none."
                )
        finally:
            session.close()
            engine.dispose()


class TestFileInsertIdempotence:
    """
    Two parallel parse stages must not leave duplicate File rows. The
    ``files`` table now has ``UNIQUE (repository_id, path)`` and the parse
    stage's insert uses ``ON CONFLICT DO NOTHING`` on that key.

    Both Defect 3 (idempotence) and the supporting schema change live here.
    """

    def test_two_overlapping_inserts_leave_one_row_per_path(self, migrated_db):
        """
        Insert the same ``(repository_id, path)`` pair twice with
        ``on_conflict_do_nothing``. Without the unique constraint the second
        insert would create a duplicate row.
        """
        import uuid as _uuid

        from sqlalchemy import create_engine
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.orm import sessionmaker

        from app.core.security import hash_password
        from app.models.file import File
        from app.models.repository import Repository
        from app.models.user import User
        from tests.conftest import TEST_SYNC_DB_URL

        engine = create_engine(TEST_SYNC_DB_URL)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            # The pipeline_repo fixture's commit happens on a different
            # session; we open our own to insert here.
            user = User(
                id=_uuid.uuid4(),
                email=f"phaseA-{_uuid.uuid4().hex[:8]}@example.com",
                name="Phase A User",
                password=hash_password("correct horse battery staple"),
            )
            session.add(user)
            session.flush()

            repo = Repository(
                user_id=user.id,
                github_url="https://github.com/example/idempotent",
                name="idempotent",
                status="pending",
                primary_language="python",
                default_branch="main",
                ingested_branch="main",
                ingested_commit_sha="0" * 40,
                repo_number=_uuid.uuid4().int % 10_000_000,
            )
            session.add(repo)
            session.flush()

            stmt = (
                pg_insert(File)
                .values(
                    repository_id=repo.id,
                    path="src/app.py",
                    language="python",
                    loc=10,
                )
                .on_conflict_do_nothing(index_elements=["repository_id", "path"])
            )
            session.execute(stmt)
            session.execute(stmt)
            session.commit()

            rows = (
                session.query(File)
                .filter(
                    File.repository_id == repo.id,
                    File.path == "src/app.py",
                )
                .count()
            )
            assert rows == 1, f"expected one row, got {rows}"
        finally:
            session.rollback()
            session.close()
            engine.dispose()


# --- helpers -----------------------------------------------------------------------


def _run_swallowing(repo_id):
    """Run the task, absorbing the retry the failure path raises."""
    try:
        return run_task(repo_id)
    except Exception:
        return None


def _query(repo_id, statement):
    """Run a read-only query against the committed rows."""
    engine, Session = sync_session()
    session = Session()
    try:
        return statement(session, repo_id)
    finally:
        session.close()
        engine.dispose()


def status_of(repo_id) -> str:
    from app.models.repository import Repository

    return _query(
        repo_id,
        lambda s, rid: s.query(Repository.status).filter(Repository.id == rid).scalar(),
    )


def file_count(repo_id) -> int:
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: s.query(File).filter(File.repository_id == rid).count(),
    )


def file_paths(repo_id) -> set[str]:
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: {row.path for row in s.query(File).filter(File.repository_id == rid)},
    )


def languages_of(repo_id) -> set[str]:
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: {
            row.language for row in s.query(File).filter(File.repository_id == rid) if row.language
        },
    )


def file_row_count(repo_id) -> int:
    """Total file rows, counting duplicates -- unlike `file_paths`, which is a set."""
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: s.query(File).filter(File.repository_id == rid).count(),
    )


def symbol_count(repo_id) -> int:
    from app.models.ast_symbol import AstSymbol
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: (
            s.query(AstSymbol)
            .join(File, File.id == AstSymbol.file_id)
            .filter(File.repository_id == rid)
            .count()
        ),
    )


def dependency_count(repo_id) -> int:
    from app.models.ast_symbol import AstSymbol
    from app.models.dependency import Dependency
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: (
            s.query(Dependency)
            .join(AstSymbol, Dependency.source_symbol_id == AstSymbol.id)
            .join(File, File.id == AstSymbol.file_id)
            .filter(File.repository_id == rid)
            .count()
        ),
    )


def symbol_names(repo_id) -> set[str]:
    from app.models.ast_symbol import AstSymbol
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: {
            row.name
            for row in s.query(AstSymbol)
            .join(File, File.id == AstSymbol.file_id)
            .filter(File.repository_id == rid)
        },
    )


def docstrings_by_name(repo_id) -> dict[str, str | None]:
    """
    ``(symbol_name, docstring)`` for every function/class/method in the repo.

    Imports are excluded because they have no docstring by design (the
    parser writes ``None`` for them). The fixture's two negatives
    (``with_license.py``, ``far_comment.py``) carry a function whose
    docstring must surface as ``None``.
    """
    from app.models.ast_symbol import AstSymbol
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: {
            row.name: row.docstring
            for row in (
                s.query(AstSymbol.name, AstSymbol.docstring)
                .join(File, File.id == AstSymbol.file_id)
                .filter(File.repository_id == rid)
                .filter(AstSymbol.kind.in_(("function", "class", "method")))
            )
        },
    )


def glossary_count(repo_id) -> int:
    from app.models.glossary_entry import GlossaryEntry

    return _query(
        repo_id,
        lambda s, rid: s.query(GlossaryEntry).filter(GlossaryEntry.repository_id == rid).count(),
    )


def embedding_count(repo_id) -> int:
    from app.models.embedding import Embedding

    return _query(
        repo_id,
        lambda s, rid: s.query(Embedding).filter(Embedding.repository_id == rid).count(),
    )


def embedded_file_paths(repo_id) -> set[str]:
    """Paths that produced a chunk *of their own*: symbol chunks and file fallbacks.

    Deliberately excludes `commit`, `pull_request` and `document` rows. `Embedding.file_id`
    is non-nullable, so a commit chunk is filed against one of the files it touched -- and
    a commit that happened to touch the file under test would otherwise make it look
    indexed when nothing was embedded from it at all.
    """
    from app.models.embedding import Embedding
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: {
            row.path
            for row in s.query(File)
            .join(Embedding, Embedding.file_id == File.id)
            .filter(File.repository_id == rid)
            .filter(Embedding.source_type.in_(("symbol", "file")))
        },
    )


def chunk_texts(repo_id) -> list[str]:
    from app.models.embedding import Embedding

    return _query(
        repo_id,
        lambda s, rid: [
            row.chunk_text for row in s.query(Embedding).filter(Embedding.repository_id == rid)
        ],
    )


def commit_count(repo_id) -> int:
    from app.models import Commit

    return _query(
        repo_id,
        lambda s, rid: s.query(Commit).filter(Commit.repository_id == rid).count(),
    )


def commit_messages(repo_id) -> list[str]:
    from app.models import Commit

    return _query(
        repo_id,
        lambda s, rid: [row.message for row in s.query(Commit).filter(Commit.repository_id == rid)],
    )


def commit_dates(repo_id) -> list[datetime]:
    from app.models import Commit

    return _query(
        repo_id,
        lambda s, rid: [
            row.authored_at for row in s.query(Commit).filter(Commit.repository_id == rid)
        ],
    )


def ownership_paths(repo_id) -> set[str]:
    from app.models.code_owner import CodeOwner
    from app.models.file import File

    return _query(
        repo_id,
        lambda s, rid: {
            row.path
            for row in s.query(File)
            .join(CodeOwner, CodeOwner.file_id == File.id)
            .filter(File.repository_id == rid)
        },
    )


def guide_of(repo_id):
    from app.models.onboarding_guide import OnboardingGuide

    return _query(
        repo_id,
        lambda s, rid: (
            s.query(OnboardingGuide).filter(OnboardingGuide.repository_id == rid).first()
        ),
    )


def reading_order_of(repo_id) -> list | None:
    guide = guide_of(repo_id)
    return guide.reading_order if guide else None


def brief_of(repo_id) -> dict | None:
    guide = guide_of(repo_id)
    return guide.architecture_brief if guide else None


def fan_out_of(repo_id, path: str) -> int:
    """A file's fan-out read from the File table.

    The stored reading-order payload dropped ``fan_out`` in Phase D
    (only the columns the API actually consumes survive), so any test
    that needs it has to look it up directly. Returns 0 when no such
    file exists -- callers compare against 1.
    """
    from app.models.file import File

    return (
        _query(
            repo_id,
            lambda s, rid: (
                s.query(File.fan_out)
                .filter(File.repository_id == rid)
                .filter(File.path == path)
                .scalar()
            ),
        )
        or 0
    )


class RecordingRedis:
    """
    A Redis client that records instead of publishing.

    Subscribing on a second connection would race the publisher -- the frames are emitted
    synchronously as the task runs, and a subscriber's buffer is drained at whatever
    moment the test looks. The task only ever calls `publish`, so standing in for the
    client is both simpler and exact.
    """

    def __init__(self):
        self.frames: list[str] = []
        self.channels: list[str] = []

    def publish(self, channel: str, payload: str) -> int:
        self.channels.append(channel)
        self.frames.append(payload)
        return 1


def capture_published(repo_id, run, monkeypatch) -> list[str]:
    """Run the task and return every frame it published."""
    import app.tasks.ingest as ingest_module

    recorder = RecordingRedis()
    monkeypatch.setattr(ingest_module, "get_sync_redis", lambda: recorder)
    run(repo_id)
    return recorder.frames


def published_frames(repo_id, monkeypatch):
    """Run the happy path and return the recorded frames."""
    return capture_published(repo_id, run_task, monkeypatch)
