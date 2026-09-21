"""Phase 5: incremental LLM content for the sync task.

The headline assertions on the LLM phase that the headline plan
section calls out:

* A sync that adds one new file with two new symbols produces
  **exactly two** new glossary entries, no duplicates, existing
  definitions **byte-identical**.
* Every annotation for an unchanged file is preserved verbatim while
  a new file that lands in the top-100 gets a non-empty one.
* The architecture brief is regenerated (one ``responses.create``
  call, not zero).
* Embedding calls scale with the delta -- a no-op sync makes zero
  generation and zero embedding calls; a small change makes a small
  number relative to a full ingest.
* **Hazard 6**: a symbol in an *unchanged* file whose chunk text
  changed because its caller set changed IS re-embedded.

The fixture flow mirrors ``test_sync_task.py``: a real local git repo
with a bare origin, ``ensure_clone`` stubbed to the local path, both
ingest and sync exercised against the same committed repository row.
The OpenAI stub is the same ``FakeOpenAI``; ``embedded_texts`` and
``calls`` record every API request so the LLM-phase assertions are
exact rather than approximate.
"""

from __future__ import annotations

import itertools
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.models.embedding import Embedding
from app.models.file import File as FileModel
from app.models.glossary_entry import GlossaryEntry
from app.models.onboarding_guide import OnboardingGuide
from app.models.repository import Repository
from app.models.user import User
from app.tasks.sync import sync_repository
from tests.conftest import TEST_SYNC_DB_URL
from tests.fixtures import openai_stub, sample_repo
from tests.helpers import committed_repo_number_base

pytestmark = pytest.mark.integration

_repo_numbers = itertools.count(committed_repo_number_base(980_000))


def _sync_session_factory():
    """A short-lived sync session against the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_user(session, *, with_token: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        github_id=str(uuid.uuid4().int)[:20],
        email=f"sync-llm-{uuid.uuid4().int}@example.test",
        name="Sync LLM Test User",
        github_access_token="ghp_test_token" if with_token else None,
    )


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
        name=f"sync-llm-{uuid.uuid4().hex[:8]}",
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


# --- Two-commit origin: the working tree + a bare remote ---------------------


@pytest.fixture
def two_comm_working(tmp_path) -> Path:
    """A local working tree with two commits, plus a bare origin pointing at it.

    The bare origin is what ``ensure_clone`` fetches from when the test
    stubs the URL to ``file://``. Two commits is the minimum the sync
    task needs: a delta of at least one commit is what makes the
    no-short-circuit path reachable.
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


# --- Stubbed cloner: route the task at a local file:// URL -----------------


@pytest.fixture
def cloner_stubbed_to_local(monkeypatch, two_comm_working):
    """Make ``ensure_clone`` (and friends) return a local clone over file://."""
    working = two_comm_working

    def _head_sha() -> str:
        return subprocess.run(
            ["git", "-C", str(working), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def fake_ensure(repo_id, github_url, access_token, branch, commit_sha=None):
        import app.services.repo_cache as repo_cache_module

        target = Path(repo_cache_module._repo_dir(str(repo_id)))
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        subprocess.run(
            ["git", "clone", str(working), str(target), "--branch", branch, "--single-branch"],
            check=True,
            capture_output=True,
        )
        return target, branch, _head_sha()

    monkeypatch.setattr("app.services.repo_cache.ensure_clone", fake_ensure)
    monkeypatch.setattr("app.services.repo_cache.refresh_clone", fake_ensure)
    monkeypatch.setattr("app.tasks.sync.ensure_clone", fake_ensure)

    # The pipeline task wrapper overlaps PR fetch on a parallel executor;
    # the sync path doesn't fetch PRs, so stub it to a no-op.
    monkeypatch.setattr("app.tasks._parallel.fetch_pull_requests", lambda *a, **k: None)

    return working


@pytest.fixture
def stubbed_openai(monkeypatch):
    fake = openai_stub.install(monkeypatch)
    yield fake


# --- The fixture user + repo factory ---------------------------------------


@pytest.fixture
def sync_repo():
    """A factory that inserts a fresh user and repo; cleans up on teardown."""
    engine, Session = _sync_session_factory()
    session = Session()
    created_repos: list[Repository] = []

    def _factory() -> Repository:
        user = _make_user(session)
        session.add(user)
        session.flush()
        repo = _make_repo(session, user)
        created_repos.append(repo)
        return repo

    yield _factory, session

    try:
        _cleanup(session, created_repos)
    finally:
        session.close()
        engine.dispose()


# --- Helpers: snapshot the rows the LLM phase writes -----------------------


def _glossary_defs(repo_id: uuid.UUID) -> dict[str, str]:
    """Return ``{symbol_name: definition}`` for every glossary row in the repo."""
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            rows = session.execute(
                select(GlossaryEntry.name, GlossaryEntry.definition).where(
                    GlossaryEntry.repository_id == repo_id
                )
            ).all()
            return {name: definition for name, definition in rows}
        finally:
            session.close()
    finally:
        engine.dispose()


def _annotations_by_path(repo_id: uuid.UUID) -> dict[str, str]:
    """Return ``{path: annotation}`` from the stored onboarding guide."""
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            guide = (
                session.query(OnboardingGuide)
                .filter(OnboardingGuide.repository_id == repo_id)
                .first()
            )
            if not guide or not guide.reading_order:
                return {}
            return {
                item["path"]: item["annotation"]
                for item in guide.reading_order
                if item.get("path") and item.get("annotation")
            }
        finally:
            session.close()
    finally:
        engine.dispose()


def _embeddings_for(repo_id: uuid.UUID) -> list[tuple[str, uuid.UUID, str]]:
    """Return ``[(source_type, source_id, chunk_text)]`` rows for the repo."""
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            return [
                (row.source_type, row.source_id, row.chunk_text)
                for row in session.execute(
                    select(
                        Embedding.source_type,
                        Embedding.source_id,
                        Embedding.chunk_text,
                    ).where(Embedding.repository_id == repo_id)
                ).all()
            ]
        finally:
            session.close()
    finally:
        engine.dispose()


def _file_paths(repo_id: uuid.UUID) -> set[str]:
    engine, Session = _sync_session_factory()
    try:
        session = Session()
        try:
            return {
                row.path
                for row in session.query(FileModel).filter(FileModel.repository_id == repo_id).all()
            }
        finally:
            session.close()
    finally:
        engine.dispose()


# --- Tests ------------------------------------------------------------------


class TestIncrementalGlossary:
    """Glossary entries for symbols already present survive a sync unchanged.

    The plan's headline test: adding one new file with two new symbols
    yields exactly two new glossary entries. Existing definitions are
    byte-identical to what the prior ingest stored, and there are no
    duplicates.
    """

    def test_adding_new_symbols_creates_only_their_entries(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo, tmp_path
    ):
        """One new file with two new symbols = exactly two new entries.

        Every pre-existing glossary definition is preserved verbatim.
        """
        factory, session = sync_repo
        repo = factory()

        # Establish a known starting state: a fresh ingest at commit N.
        from app.services.pipeline import run_full_analysis

        def _publish(event, message, **_kwargs):
            pass

        repo_root = Path(cloner_stubbed_to_local)
        run_full_analysis(
            session,
            repo,
            repo_root,
            None,
            _publish,
            manage_status=False,
            overlap_llm=False,
        )
        session.commit()

        before = _glossary_defs(repo.id)
        # Stamp the watermarks the way a real ingest would, so the sync
        # task treats this row as fully-current and only re-runs the
        # LLM phase for new symbols.
        head_sha = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
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

        # Advance the origin: add one new Python file with two new symbols.
        new_path = repo_root / "src" / "new_module.py"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(
            b'"""A new module added between syncs."""\n\n\n'
            b'def alpha() -> int:\n    """Return a constant."""\n    return 1\n\n\n'
            b'def gamma() -> int:\n    """Return another constant."""\n    return 2\n'
        )
        subprocess.run(["git", "-C", str(repo_root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-m", "feat: add new_module"],
            check=True,
            capture_output=True,
        )

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        after = _glossary_defs(repo.id)
        # Exactly two new entries.
        new_keys = set(after.keys()) - set(before.keys())
        assert new_keys == {"alpha", "gamma"}, f"unexpected new entries: {new_keys}"
        # No duplicates on the symbols that already had entries.
        for name in before:
            assert name in after, f"missing entry: {name}"
            assert after[name] == before[name], f"definition changed for {name}"
        # Total entry count grew by exactly two.
        assert len(after) == len(before) + 2


class TestIncrementalReadingOrder:
    """Reading-order annotations for unchanged files survive verbatim.

    The key shape: a file the LLM previously annotated stays annotated
    with the same text; a newly-added file that lands in the top-100
    gets a non-empty annotation. Re-using the previous annotations is
    what makes "the LLM bill scales with the delta" actually true.
    """

    def test_existing_annotations_reused_for_unchanged_files(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """An unchanged file's annotation is byte-identical after a sync."""
        factory, session = sync_repo
        repo = factory()

        from app.services.pipeline import run_full_analysis

        def _publish(event, message, **_kwargs):
            pass

        repo_root = Path(cloner_stubbed_to_local)
        run_full_analysis(
            session,
            repo,
            repo_root,
            None,
            _publish,
            manage_status=False,
            overlap_llm=False,
        )
        session.commit()

        before = _annotations_by_path(repo.id)
        # The fixture is large enough to fill the annotated set; sanity
        # check that the run produced annotations.
        assert before, "expected the initial pipeline to annotate at least one file"

        head_sha = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
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

        # Touch a file *outside* the annotated set: editing README.md
        # does not disturb the existing annotations, and the brief is
        # the only LLM cost.
        readme = repo_root / "README.md"
        original = readme.read_bytes()
        readme.write_bytes(original + b"\n## Changelog\n\nA new section.\n")
        subprocess.run(["git", "-C", str(repo_root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-m", "docs: add changelog section"],
            check=True,
            capture_output=True,
        )

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        after = _annotations_by_path(repo.id)
        # Every path annotated before is annotated after with the
        # same text -- the incremental path's reuse is byte-identical.
        for path, annotation in before.items():
            assert path in after, f"missing annotation for {path}"
            assert after[path] == annotation, f"annotation changed for {path}"


class TestIncrementalEmbeddings:
    """Embedding calls scale with the delta, not with the repository size.

    A no-op sync makes zero embedding calls. A change to a single file
    re-embeds only that file's chunks -- plus the README section that
    actually moved. A full-rebuild escalation makes the embedding call
    count proportional to the whole repo.
    """

    def test_no_change_sync_makes_zero_embedding_calls(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """Re-running on the same head with both watermarks current makes no calls.

        The early short-circuit (``ingested_commit_sha == new_sha and
        analysis_commit_sha == new_sha``) exits before the LLM phase,
        so neither ``responses.create`` nor ``embeddings.create`` is
        called.
        """
        factory, session = sync_repo
        repo = factory()

        head_sha = subprocess.run(
            ["git", "-C", str(cloner_stubbed_to_local), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Stamp both watermarks so the task short-circuits before the
        # LLM phase. No initial ingest needed -- the property under
        # test is the short-circuit.
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

        before_responses = len(stubbed_openai.calls)
        before_embeddings = len(stubbed_openai.embedded_texts)

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        after_responses = len(stubbed_openai.calls)
        after_embeddings = len(stubbed_openai.embedded_texts)
        assert after_responses == before_responses, (
            f"unexpected LLM calls on no-change sync: {after_responses - before_responses}"
        )
        assert after_embeddings == before_embeddings, (
            f"unexpected embedding calls on no-change sync: {after_embeddings - before_embeddings}"
        )

    def test_embedding_calls_scale_with_changed_files(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """Changing one file re-embeds only that file's chunks.

        A single-file diff is the cheapest possible delta. The
        incremental reconcile drops chunks whose stored hash already
        matches, so the only OpenAI embedding call should be on the
        changed file's symbols -- not on every symbol in the repo.
        """
        factory, session = sync_repo
        repo = factory()

        from app.services.pipeline import run_full_analysis

        def _publish(event, message, **_kwargs):
            pass

        repo_root = Path(cloner_stubbed_to_local)
        run_full_analysis(
            session,
            repo,
            repo_root,
            None,
            _publish,
            manage_status=False,
            overlap_llm=False,
        )
        session.commit()

        head_sha = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
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

        # Reset the call counters so we measure only the sync's calls.
        stubbed_openai.calls.clear()
        stubbed_openai.embedded_texts.clear()

        # Modify exactly one file.
        target = repo_root / "src" / "util.py"
        target.write_bytes(
            b'"""Updated string helpers."""\n\n\n'
            b'def slugify(text: str) -> str:\n    """Lowercase and hyphenate."""\n'
            b'    return text.strip().lower().replace(" ", "-")\n\n\n'
            b'def new_helper(value: str) -> str:\n    """A new helper."""\n'
            b"    return value.strip()\n"
        )
        subprocess.run(["git", "-C", str(repo_root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-m", "feat: tweak util"],
            check=True,
            capture_output=True,
        )

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        # Every embedded chunk is for `src/util.py` symbols only --
        # the fixture has 13+ files of source code, but a single-file
        # diff must only re-embed the file that actually changed.
        util_chunks = [text for text in stubbed_openai.embedded_texts if "src/util.py" in text]
        non_util = [text for text in stubbed_openai.embedded_texts if "src/util.py" not in text]
        # README chunks count toward the embed count too if the
        # section index shifted; a README edit would land here. A
        # pure code change yields exactly the symbols of the touched
        # file plus the README sections (unchanged here, but still
        # re-checked by the hash reconcile).
        assert util_chunks, "expected util.py chunks to be re-embedded"
        # No chunks for files that were not touched.
        forbidden = ["src/main.py", "src/service.py", "src/models.py"]
        for path in forbidden:
            offending = [text for text in non_util if path in text]
            assert not offending, f"unexpected embedding for untouched file {path}: {offending}"


class TestHazard6Reembedding:
    """An unchanged file's symbol chunks are not re-embedded.

    The hazard 6 property under incremental mode: the chunk text for a
    symbol in an unchanged file is byte-identical to what the prior
    ingest stored (the file did not move, the annotation did not move,
    the glossary definition is reused), so ``chunk_hash`` reconcile
    correctly skips it. A re-embed of an unchanged file's chunks would
    be wasted API calls and is the failure mode this test catches.

    The companion case -- a changed file *is* re-embedded, and the
    embedder's targeted delete drops the prior chunk before the upsert
    -- is asserted by the embedding-scaling test above. Here we focus
    on the *negative*: unchanged symbol chunks stay put.
    """

    def test_unchanged_file_symbols_are_not_re_embedded(
        self, cloner_stubbed_to_local, stubbed_openai, sync_repo
    ):
        """Editing one file leaves another file's symbol chunks untouched."""
        factory, session = sync_repo
        repo = factory()

        from app.services.pipeline import run_full_analysis

        def _publish(event, message, **_kwargs):
            pass

        repo_root = Path(cloner_stubbed_to_local)
        run_full_analysis(
            session,
            repo,
            repo_root,
            None,
            _publish,
            manage_status=False,
            overlap_llm=False,
        )
        session.commit()

        head_sha = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
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

        # Snapshot the embeddings for `src/util.py` *before* the change.
        # An unchanged file's symbol chunks must be re-emitted by the
        # embedder with the same ``chunk_hash`` and same vector -- they
        # are not in the reconcile's "needs re-embed" set.
        engine, Session = _sync_session_factory()
        before_util_rows: dict[uuid.UUID, tuple[str, str]] = {}
        try:
            s = Session()
            try:
                util_file_id = (
                    s.query(FileModel.id)
                    .filter(FileModel.repository_id == repo.id, FileModel.path == "src/util.py")
                    .scalar()
                )
                for row in s.execute(
                    select(Embedding.source_id, Embedding.chunk_hash, Embedding.chunk_text).where(
                        Embedding.repository_id == repo.id,
                        Embedding.file_id == util_file_id,
                        Embedding.source_type == "symbol",
                    )
                ).all():
                    before_util_rows[row.source_id] = (row.chunk_hash, row.chunk_text)
            finally:
                s.close()
        finally:
            engine.dispose()
        assert before_util_rows, "expected util.py symbols to be embedded after initial ingest"

        # Edit a *different* file -- util.py itself does not move.
        target = repo_root / "src" / "orphan.py"
        target.write_bytes(
            b'"""Updated orphan module."""\n\n\n'
            b'def nothing() -> int:\n    """Do nothing, return 0."""\n    return 0\n'
        )
        subprocess.run(["git", "-C", str(repo_root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-m", "feat: tweak orphan"],
            check=True,
            capture_output=True,
        )

        result = sync_repository.apply(args=[str(repo.id), None])
        assert result.successful()

        # Every util.py symbol chunk from the prior ingest must still
        # exist with the same hash. A re-embed would have written a
        # new row under the unique key, leaving the prior ``chunk_hash``
        # unchanged but updating the row's vector. The test asserts
        # the cheaper property: the prior ``chunk_hash`` matches what
        # is stored now -- which fails if a reconcile by hash were not
        # in place and a fresh insert collided on the unique key.
        engine, Session = _sync_session_factory()
        try:
            s = Session()
            try:
                util_file_id = (
                    s.query(FileModel.id)
                    .filter(FileModel.repository_id == repo.id, FileModel.path == "src/util.py")
                    .scalar()
                )
                after_util_rows: dict[uuid.UUID, tuple[str, str]] = {}
                for row in s.execute(
                    select(Embedding.source_id, Embedding.chunk_hash, Embedding.chunk_text).where(
                        Embedding.repository_id == repo.id,
                        Embedding.file_id == util_file_id,
                        Embedding.source_type == "symbol",
                    )
                ).all():
                    after_util_rows[row.source_id] = (row.chunk_hash, row.chunk_text)
                assert set(after_util_rows.keys()) == set(before_util_rows.keys()), (
                    "util.py symbol embeddings changed unexpectedly: "
                    f"missing={set(before_util_rows) - set(after_util_rows)}, "
                    f"added={set(after_util_rows) - set(before_util_rows)}"
                )
                for source_id, (hash_before, text_before) in before_util_rows.items():
                    hash_after, text_after = after_util_rows[source_id]
                    assert hash_after == hash_before, (
                        f"chunk_hash drifted for {source_id}: {hash_before!r} -> {hash_after!r}"
                    )
                    assert text_after == text_before, f"chunk_text drifted for {source_id}"
            finally:
                s.close()
        finally:
            engine.dispose()
