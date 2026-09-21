"""
Clone cache behaviour.

Every test exercises the real cache against a real local git repository
built by ``sample_repo.build``. No network, no Postgres, no Redis: the
cache is a pure filesystem mechanism and the assertions are exactly
that.

The expectations pinned here mirror what ``clone_repository`` already
promises to the rest of the codebase -- a callable shape and an exit
that cannot strand a sync mid-flight. Several of these are direct
regressions for the listed ``refresh_clone`` after a content change,
the LRU cap, per-repo ceiling, fallback to ephemeral when the cache
root is unwritable, token hygiene in ``.git/config``, and the
``.git``/``walk_source_files`` interaction.
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from app.services import repo_cache
from app.services.repo_cache import (
    CLONE_CACHE_ENABLED,
    CLONE_CACHE_MAX_BYTES,
    CLONE_CACHE_MAX_REPO_BYTES,
    cache_size,
    ensure_clone,
    evict_to_cap,
    refresh_clone,
    touch,
)
from app.services.scanner import walk_source_files
from tests.fixtures import sample_repo

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch, tmp_path: Path):
    """Point every cache path at the per-test temp dir for full isolation.

    ``monkeypatch`` reverts every attribute change on teardown, so the
    module-level constants returned to their defaults after each test.
    Without this fixture two tests share the cache root under
    ``tempfile.gettempdir()`` and can evict each other's entries.

    The lambda captures the path, but the directory is created here --
    not lazily inside the production code -- because the production
    fallback path's writability probe would otherwise mis-fire on
    test machines where ``tmp_path`` is on a new filesystem.
    """
    cache_root = tmp_path / "cache"
    state_dir = cache_root / repo_cache._STATE_SUBDIR
    cache_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(repo_cache, "_cache_root", lambda: cache_root)
    monkeypatch.setattr(repo_cache, "_state_dir", lambda: state_dir)
    yield cache_root


def _run(cwd: Path, *args: str) -> str:
    """Run a git subprocess in ``cwd``."""
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _head_sha(cwd: Path) -> str:
    """Current commit SHA of the working tree at ``cwd``."""
    return _run(cwd, "rev-parse", "HEAD")


def _build_source_repo(tmp_path: Path) -> Path:
    """Build the canonical sample repo at ``tmp_path / 'origin'``."""
    origin = tmp_path / "origin"
    return sample_repo.build(origin)


def _file_url(repo: Path) -> str:
    """An absolute ``file://`` URL pointing at ``repo``.

    ``file://`` is the only URL scheme that works without an SSH or
    HTTPS server being available, and git supports it natively.
    """
    return repo.resolve().as_uri()


def _git_remote_url(repo_dir: Path, remote: str = "origin") -> str:
    """Read the stored URL of ``remote`` from ``.git/config``."""
    return _run(repo_dir, "remote", "get-url", remote)


# --- ensure_clone / refresh_clone: lifecycle ---------------------------------


class TestEnsureCloneFirstTime:
    """First ``ensure_clone`` populates the cache; the second reuses it."""

    def test_first_ensure_clone_clones_into_the_cache(self, tmp_path: Path, _isolate_cache: Path):
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()

        repo_dir, branch, sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        assert repo_dir == _isolate_cache / str(repo_id)
        assert branch == "main"
        assert len(sha) == 40
        # The cache root created it on disk, including the bookkeeping dir.
        assert repo_dir.is_dir()
        assert (repo_dir / ".git").is_dir()
        assert (repo_dir / "README.md").is_file()
        # A marker was written as a sibling of the clone directory.
        marker = _isolate_cache / repo_cache._STATE_SUBDIR / f"{repo_id}.json"
        assert marker.is_file()
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["branch"] == "main"
        assert payload["commit_sha"] == sha

    def test_second_ensure_clone_reuses_the_directory(self, _isolate_cache: Path, tmp_path: Path):
        """A repeat call hits the existing cache entry without re-cloning.

        The ``_spy`` function counts how many times the cache code
        invokes ``_fast_forward_clone`` -- the only path that creates a
        new clone. On the first ``ensure_clone`` the directory is empty
        so this is the branch taken; on the second call the directory
        already exists with ``.git/`` so the code falls into
        ``_refresh_existing`` instead, never touching the spy.
        """
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()

        clone_calls: list[int] = []

        original = repo_cache._fast_forward_clone

        def _spy(repo_dir, github_url, access_token, branch):
            clone_calls.append(1)
            return original(repo_dir, github_url, access_token, branch)

        repo_cache._fast_forward_clone = _spy
        try:
            ensure_clone(
                repo_id=repo_id,
                github_url=_file_url(origin),
                access_token=None,
                branch="main",
            )
            ensure_clone(
                repo_id=repo_id,
                github_url=_file_url(origin),
                access_token=None,
                branch="main",
            )
        finally:
            repo_cache._fast_forward_clone = original

        # First call clones; second call refreshes the existing entry
        # via ``_refresh_existing`` rather than ``_fast_forward_clone``.
        assert clone_calls == [1]


class TestRefreshCloneAfterContentChange:
    """``refresh_clone`` brings the working tree to the new head."""

    def test_a_new_commit_advances_head_and_diff_lists_exactly_it(self, tmp_path: Path):
        """A second commit at the origin appears in the cached clone after refresh."""
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        repo_dir, _branch, first_sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )
        assert first_sha == _head_sha(repo_dir)

        # Author a new commit on the origin only.
        added = origin / "src" / "added.py"
        added.write_text(
            '"""A late addition."""\n\ndef late() -> int:\n    return 42\n',
            encoding="utf-8",
        )
        _run(origin, "add", "-A")
        sample_repo._git(origin, "commit", "-m", "feat: add a late file")
        second_sha = _run(origin, "rev-parse", "HEAD")

        repo_dir, branch, sha = refresh_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        assert sha == second_sha
        assert branch == "main"
        # ``git diff --name-status`` reports exactly the added file -- a
        # ``git clean -fdx`` must not remove anything else left over from
        # the earlier fetch, and the new file must round-trip. Paths in
        # ``git`` are always forward-slash regardless of platform.
        diff = _run(repo_dir, "diff", "--name-status", first_sha, second_sha)
        assert diff.strip() == "A\tsrc/added.py"
        assert (repo_dir / "src" / "added.py").is_file()

    def test_refresh_clone_advances_only_when_a_new_commit_exists(self, tmp_path: Path):
        """Without a new commit the working tree's SHA is unchanged."""
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        _repo_dir, _branch, first_sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        repo_dir, _branch, sha = refresh_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        assert sha == first_sha
        assert _head_sha(repo_dir) == first_sha


# --- LRU eviction ----------------------------------------------------------


class TestLruEviction:
    """The cache stays within cap by evicting the least-recently-used entry."""

    def test_eviction_respects_the_global_cap(
        self, monkeypatch, _isolate_cache: Path, tmp_path: Path
    ):
        """Adding a second repo's worth of data evicts the older one.

        The cap is set to a fraction of one entry's measured size, so the
        second call provably exceeds it. Hard-coding a byte threshold
        would make the test brittle against any future change to the
        fixture.
        """
        monkeypatch.setattr(repo_cache, "CLONE_CACHE_MAX_REPO_BYTES", 10**9)

        origin_a = _build_source_repo(tmp_path / "a")
        origin_b = _build_source_repo(tmp_path / "b")
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()

        # Seed ``id_a`` and measure its size. Then drop the cap below
        # one entry's size, so the next ``ensure_clone`` call's
        # ``evict_to_cap`` pass is forced to drop ``id_a`` before
        # placing ``id_b``.
        ensure_clone(
            repo_id=id_a,
            github_url=_file_url(origin_a),
            access_token=None,
            branch="main",
        )
        first_entry_size = repo_cache._dir_size(_isolate_cache / str(id_a))
        # Just below the first entry's size -- any second clone triggers
        # the eviction pass and ``id_a`` is the only candidate.
        monkeypatch.setattr(
            repo_cache,
            "CLONE_CACHE_MAX_BYTES",
            max(first_entry_size - 1, 1),
        )

        # Force id_a's marker very old so it is the eviction victim.
        marker_path = _isolate_cache / repo_cache._STATE_SUBDIR / f"{id_a}.json"
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        payload["last_used_at"] = "2000-01-01T00:00:00+00:00"
        marker_path.write_text(json.dumps(payload), encoding="utf-8")

        # Adding id_b triggers an eviction pass: id_a is the oldest
        # entry, so it goes. After this, only id_b remains.
        ensure_clone(
            repo_id=id_b,
            github_url=_file_url(origin_b),
            access_token=None,
            branch="main",
        )

        assert not (_isolate_cache / str(id_a)).is_dir()
        assert not (_isolate_cache / repo_cache._STATE_SUBDIR / f"{id_a}.json").is_file()
        assert (_isolate_cache / str(id_b)).is_dir()
        assert (_isolate_cache / repo_cache._STATE_SUBDIR / f"{id_b}.json").is_file()

    def test_eviction_never_drops_the_in_use_repo(
        self, monkeypatch, _isolate_cache: Path, tmp_path: Path
    ):
        """``evict_to_cap(protect_repo_id=...)`` skips the protected entry.

        Two entries exist; both are stamped old; the cap is set so low
        that at least one of them must be evicted. Whichever one is NOT
        ``protect_repo_id`` is the candidate that should go.
        """
        monkeypatch.setattr(repo_cache, "CLONE_CACHE_MAX_REPO_BYTES", 10**9)

        origin_a = _build_source_repo(tmp_path / "a")
        origin_b = _build_source_repo(tmp_path / "b")
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()

        ensure_clone(
            repo_id=id_a,
            github_url=_file_url(origin_a),
            access_token=None,
            branch="main",
        )
        ensure_clone(
            repo_id=id_b,
            github_url=_file_url(origin_b),
            access_token=None,
            branch="main",
        )
        # Force the cap below either entry's size -- any ``evict_to_cap``
        # call now requires dropping at least one entry, and the next
        # call will pick the oldest of the two.
        one_entry = repo_cache._dir_size(_isolate_cache / str(id_a))
        monkeypatch.setattr(
            repo_cache,
            "CLONE_CACHE_MAX_BYTES",
            max(one_entry - 1, 1),
        )

        # ``id_b`` is older than ``id_a`` so LRU hits ``id_b`` first
        # regardless of marker-file iteration order.
        for rid, iso in (
            (id_b, "1999-01-01T00:00:00+00:00"),
            (id_a, "2000-01-01T00:00:00+00:00"),
        ):
            marker_path = _isolate_cache / repo_cache._STATE_SUBDIR / f"{rid}.json"
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
            payload["last_used_at"] = iso
            marker_path.write_text(json.dumps(payload), encoding="utf-8")

        evict_to_cap(protect_repo_id=id_a)
        # ``id_a`` survives, ``id_b`` was evicted because it was the
        # only candidate not protected.
        assert (_isolate_cache / str(id_a)).is_dir()
        assert not (_isolate_cache / str(id_b)).is_dir()

    def test_per_repo_ceiling_evicts_a_single_oversized_entry(
        self, monkeypatch, _isolate_cache: Path, tmp_path: Path
    ):
        """Per-repo ceiling: oversized entry gets an ephemeral clone instead."""
        # Sample repos are small; shrinking the ceiling forces eviction.
        monkeypatch.setattr(repo_cache, "CLONE_CACHE_MAX_REPO_BYTES", 100)
        # Keep the global cap huge so eviction comes from the per-repo rule.
        monkeypatch.setattr(repo_cache, "CLONE_CACHE_MAX_BYTES", 10**9)

        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()

        path, _branch, _sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        # After eviction we got an ephemeral clone: the path is *not* the
        # cache-resident directory for this repo, and the entry is gone.
        assert path != _isolate_cache / str(repo_id)
        assert not (_isolate_cache / str(repo_id)).is_dir()


# --- Fallback paths --------------------------------------------------------


class TestFallbacks:
    """Every cache failure degrades to an ephemeral clone, never a raise."""

    def test_unwritable_cache_root_falls_back(self, _isolate_cache: Path, tmp_path: Path):
        """When the cache root cannot be made into a directory, we get an ephemeral clone."""
        import app.services.repo_cache as rc

        # Replace the cache root with a *file*, so its ``mkdir(parents=True, exist_ok=True)``
        # raises ``FileExistsError`` -- portable across OSes. The autouse
        # fixture uses ``monkeypatch.setattr`` and will restore the
        # module-level function on teardown, so the manual restore here
        # is belt-and-braces.
        block = _isolate_cache.parent / "block_root"
        block.write_text("not a directory", encoding="utf-8")

        prior = rc._cache_root
        rc._cache_root = lambda: block
        try:
            origin = _build_source_repo(tmp_path)
            repo_id = uuid.uuid4()
            path, _branch, _sha = ensure_clone(
                repo_id=repo_id,
                github_url=_file_url(origin),
                access_token=None,
                branch="main",
            )
        finally:
            rc._cache_root = prior

        # We got an ephemeral, NOT a cached, clone.
        assert path != block / str(repo_id)
        assert path.is_dir()
        assert (path / ".git").exists() or (path / "README.md").exists()
        # The block file was never promoted into a directory.
        assert block.is_file()

    def test_ensure_clone_with_pinned_commit_falls_back_to_ephemeral(
        self, _isolate_cache: Path, tmp_path: Path
    ):
        """``commit_sha`` bypasses the cache layer entirely."""
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        pinned_sha = _run(origin, "rev-parse", "HEAD")

        path, branch, sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
            commit_sha=pinned_sha,
        )

        assert sha == pinned_sha
        # The cache root has no entry for this repo.
        assert not (_isolate_cache / str(repo_id)).is_dir()

    def test_kill_switch_disables_the_cache(
        self, monkeypatch, _isolate_cache: Path, tmp_path: Path
    ):
        """``CLONE_CACHE_ENABLED=False`` returns an ephemeral clone every time."""
        monkeypatch.setattr(repo_cache, "CLONE_CACHE_ENABLED", False)

        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        path, _branch, _sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        # No marker, no cache directory.
        assert not (_isolate_cache / str(repo_id)).is_dir()
        assert path.is_dir()
        # And it is not the canonical cache location for this repo.
        assert path != _isolate_cache / str(repo_id)


# --- Token hygiene ---------------------------------------------------------


class TestTokenHygiene:
    """``git remote set-url`` clears the token from ``.git/config`` on every fetch."""

    def test_token_does_not_appear_in_the_stored_remote_url(
        self, _isolate_cache: Path, tmp_path: Path
    ):
        """A token-bearing HTTPS URL is rewritten without the token before storage.

        ``file://`` URLs go through ``_build_clone_url`` unchanged; the
        URL rewriting only happens for ``http(s)`` URLs. An
        HTTPS-shaped URL exercises the rewriting branch directly so the
        regression we are guarding against is ``.git/config`` holding
        the secret.
        """
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        # Clone against the local ``file://`` origin -- the cache layer
        # never reaches GitHub here, but writes the URL we pass straight
        # into ``.git/config``. We then stage a token-leaking remote URL
        # to reproduce the failure mode the test pins.
        file_url = _file_url(origin)
        repo_dir, _branch, _sha = ensure_clone(
            repo_id=repo_id,
            github_url=file_url,
            access_token=None,
            branch="main",
        )
        # Stage a token-leaking remote URL -- a credential persisting
        # across one cache rotation is the regression we are guarding.
        leaky = "https://secr3t-token-do-not-leak@github.com/example/repo.git"
        _run(repo_dir, "remote", "set-url", "origin", leaky)
        assert "secr3t-token-do-not-leak" in _git_remote_url(repo_dir)

        refresh_clone(
            repo_id=repo_id,
            github_url=file_url,
            access_token=None,
            branch="main",
        )

        stored_url = _git_remote_url(repo_dir)
        assert "secr3t-token-do-not-leak" not in stored_url
        # And the new URL is the (tokenless) file:// URL we just passed.
        assert stored_url == file_url


# --- Touch / cache_size ----------------------------------------------------


class TestTouch:
    """``touch`` updates the marker; ``cache_size`` reports the on-disk total."""

    def test_touch_updates_last_used_at(self, _isolate_cache: Path, tmp_path: Path):
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )
        marker_path = _isolate_cache / repo_cache._STATE_SUBDIR / f"{repo_id}.json"
        first = json.loads(marker_path.read_text(encoding="utf-8"))["last_used_at"]

        # The marker is ISO-8601 with microsecond precision; a brief
        # sleep on the wall clock is enough to drive a non-equal
        # ``last_used_at`` without pulling in ``freezegun`` for one
        # assertion.
        import time as _time

        _time.sleep(0.01)

        touch(repo_id, "main", "0" * 40)
        second = json.loads(marker_path.read_text(encoding="utf-8"))["last_used_at"]

        assert second > first

    def test_cache_size_aggregates_known_entries(self, _isolate_cache: Path, tmp_path: Path):
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        repo_dir, _branch, _sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        # ``cache_size`` returns the sum across every entry under the
        # cache root, including the bookkeeping directory.
        assert cache_size() >= repo_cache._dir_size(repo_dir)

    def test_cache_size_returns_zero_when_disabled(self, monkeypatch):
        monkeypatch.setattr(repo_cache, "CLONE_CACHE_ENABLED", False)
        assert cache_size() == 0


# --- Scanner interaction ---------------------------------------------------


class TestScannerInteraction:
    """``.git`` excluded from ``walk_source_files`` -- the SKIP_DIRS pin."""

    def test_walk_source_files_excludes_git_internals(self, _isolate_cache: Path, tmp_path: Path):
        origin = _build_source_repo(tmp_path)
        repo_id = uuid.uuid4()
        repo_dir, _branch, _sha = ensure_clone(
            repo_id=repo_id,
            github_url=_file_url(origin),
            access_token=None,
            branch="main",
        )

        walked = walk_source_files(repo_dir)

        # No path under ``walked`` should live inside ``.git``.
        # ``walk_source_files`` only keeps recognized source
        # extensions, but the regression we are guarding against is
        # the directory *itself*: a ``.py`` file inside ``.git`` would
        # not exist but the rule must hold regardless of git internals.
        for path in walked:
            # ``Path.is_relative_to`` is 3.9+; ``scanner.py`` already
            # requires it, so the project is on a recent Python.
            assert not path.is_relative_to(repo_dir / ".git"), path


# --- Defensive smoke tests -------------------------------------------------


class TestConstants:
    """The constants exist with sensible defaults and are not silently zero."""

    def test_global_cap_is_positive(self):
        assert CLONE_CACHE_MAX_BYTES > 0
        assert isinstance(CLONE_CACHE_MAX_BYTES, int)

    def test_per_repo_cap_below_global_cap(self):
        assert CLONE_CACHE_MAX_REPO_BYTES > 0
        assert CLONE_CACHE_MAX_REPO_BYTES <= CLONE_CACHE_MAX_BYTES

    def test_kill_switch_is_a_bool(self):
        assert isinstance(CLONE_CACHE_ENABLED, bool)
