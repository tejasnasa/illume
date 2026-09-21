"""
Persistent non-bare git clones, keyed by repository id.

A persistent clone is a performance optimisation, never a correctness
dependency: every failure mode inside this module falls back to a fresh
``tempfile.mkdtemp`` clone, and wiping the cache at any time is safe.

The contract surfaced to callers is small and stable: ``ensure_clone`` /
``refresh_clone`` each return ``(Path, branch, commit_sha)`` -- the same
shape ``clone_repository`` in :mod:`app.services.cloner` already returns,
so the existing call sites do not change.

Token hygiene is load-bearing. Every fetch re-sets the remote URL with
the *current* token before contacting GitHub, so an expired token from a
previous cache lifetime cannot leave the clone permanently wedged, and a
plaintext credential never lingers in ``.git/config`` longer than the
space of one fetch. ``GIT_TERMINAL_PROMPT=0`` plus a no-op
``GIT_ASKPASS`` makes a credential prompt fail fast rather than hang a
worker indefinitely.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import git

logger = logging.getLogger(__name__)

# Total cap on disk the cache is allowed to consume. Conservative on boxes with
# little free space; the live box has 51 GiB free so 2 GiB is comfortably
# affordable.
CLONE_CACHE_MAX_BYTES: int = 2 * 1024 * 1024 * 1024

# Per-repo ceiling so a single large repository cannot evict everything else.
# Picked below ``CLONE_CACHE_MAX_BYTES`` -- the two together ensure that a repo
# larger than this cannot enter the cache at all (and degrades to an ephemeral
# clone instead).
CLONE_CACHE_MAX_REPO_BYTES: int = 512 * 1024 * 1024

# Global kill switch. When False, ``ensure_clone`` falls straight through to
# the ephemeral ``tempfile.mkdtemp`` path.
CLONE_CACHE_ENABLED: bool = True

# ``git fetch`` ceiling. Long enough that a slow GitHub is still reachable,
# short enough that an expired token or a wedged session cannot pin a worker
# indefinitely.
GIT_FETCH_TIMEOUT_SECONDS: int = 60

# ``git ls-remote`` ceiling for the cheap SHA probe -- the one call the
# common case makes. Has to be cheap enough that an idle sweep never spends
# long on it.
GIT_LS_REMOTE_TIMEOUT_SECONDS: int = 20

# ``git reset --hard`` + ``git clean`` ceiling.
GIT_RESET_TIMEOUT_SECONDS: int = 30

# Where cache bookkeeping lives. Sibling of every per-repo clone directory
# under the cache root itself -- *outside* the clone directory so a
# ``git clean -fdx`` inside the working tree cannot remove it.
_STATE_SUBDIR = ".cache_state"


# --- Cache root ------------------------------------------------------------


def _cache_root() -> Path:
    """Resolve the cache root, creating it on first use.

    No environment override exists by design: changing this requires a code
    change so the same value is baked into the image, the local checkout
    and every worker's container alike. ``tempfile.gettempdir`` is the
    platform-appropriate default on every supported OS.
    """
    root = Path(tempfile.gettempdir()) / "illume" / "clone_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_dir() -> Path:
    """Marker-bookkeeping directory, sibling of every per-repo clone."""
    state = _cache_root() / _STATE_SUBDIR
    state.mkdir(parents=True, exist_ok=True)
    return state


def _repo_dir(repo_id: uuid.UUID | str) -> Path:
    """The directory a given repo's working clone lives in."""
    return _cache_root() / str(repo_id)


def _marker_path(repo_id: uuid.UUID | str) -> Path:
    """Where ``touch`` records branch, head SHA and last-use time for one repo."""
    return _state_dir() / f"{repo_id}.json"


# --- Bookkeeping -----------------------------------------------------------


def _read_marker(repo_id: uuid.UUID | str) -> dict | None:
    """Return the parsed marker for ``repo_id``, or ``None`` when unreadable.

    A partial write, a permissions hiccup, or a corrupted JSON should not
    break the cache. The clone directory and the marker are read
    independently, so a bad marker means we treat the entry as fresh and
    rebuild it on the next touch.
    """
    path = _marker_path(repo_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def touch(repo_id: uuid.UUID | str, branch: str, commit_sha: str) -> None:
    """Record that ``repo_id`` was just used at ``branch``/``commit_sha``.

    The last-use timestamp is what LRU eviction reads -- the entry with
    the oldest timestamp is the first one evicted when the cache is over
    cap. Marker writes are best-effort: losing a touch only costs an
    early eviction, never a correctness problem.
    """
    if not CLONE_CACHE_ENABLED:
        return
    payload = {
        "branch": branch,
        "commit_sha": commit_sha,
        "last_used_at": datetime.now(UTC).isoformat(),
        "repo_id": str(repo_id),
    }
    try:
        _marker_path(repo_id).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to touch clone-cache marker for %s: %s", repo_id, exc)


def _remove_entry(repo_id: uuid.UUID | str) -> None:
    """Delete a repo's clone directory and its marker. Missing files are fine.

    A bare ``shutil.rmtree(ignore_errors=True)`` quietly skips files
    git is still holding open (common on Windows once a Repo object has
    touched ``.git/objects``). The ``onerror`` callback clears the
    read-only bit and retries -- the same one-liner pattern the Python
    docs suggest for locked files. If the directory is gone after the
    call, great; if not, the directory is left in place and the next
    eviction pass will retry.
    """
    repo_dir = _repo_dir(repo_id)

    def _clear_readonly(func, path, _exc_info):
        import stat

        os.chmod(path, stat.S_IWRITE)
        func(path)

    if repo_dir.is_dir():
        shutil.rmtree(repo_dir, onerror=_clear_readonly)
    marker = _marker_path(repo_id)
    if marker.is_file():
        marker.unlink()


def _dir_size(path: Path) -> int:
    """Sum of regular-file sizes under ``path`` (recursive, follows symlinks).

    A one-pass scan; entries we cannot stat (broken symlinks, permissions)
    contribute zero rather than raising, because a partial answer is more
    useful than a broken cache eviction.
    """
    total = 0
    try:
        iterator = os.walk(path)
    except OSError:
        return 0
    for root, _dirs, files in iterator:
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def cache_size() -> int:
    """Total bytes currently used by the on-disk cache (across all entries)."""
    if not CLONE_CACHE_ENABLED:
        return 0
    root = _cache_root()
    if not root.is_dir():
        return 0
    return _dir_size(root)


def _marker_last_used(path: Path) -> datetime | None:
    """Parse the ``last_used_at`` field out of a marker file."""
    payload = _read_marker(path.stem)
    if payload is None:
        return None
    raw = payload.get("last_used_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _list_evictable() -> list[Path]:
    """Marker files sorted oldest-first by ``last_used_at``.

    A marker with no parseable timestamp falls to the front of the list
    -- it is the closest thing we have to "this entry is stale and has
    no useful state".
    """
    entries: list[tuple[datetime | None, Path]] = []
    for marker in _state_dir().glob("*.json"):
        entries.append((_marker_last_used(marker), marker))
    entries.sort(key=lambda pair: (pair[0] is None, pair[0] or datetime.min.replace(tzinfo=UTC)))
    return [marker for _ts, marker in entries]


def evict_to_cap(protect_repo_id: uuid.UUID | str | None = None) -> None:
    """Delete least-recently-used entries until ``cache_size() <= cap``.

    ``protect_repo_id`` (the repo currently being prepared) is never
    evicted -- evicting the entry we are about to read from is a
    footgun, and ``ensure_clone`` is the only public caller that needs
    the lock.

    Eviction is a no-op when the cache is disabled or already within cap.
    Bails out when no evictable candidate is left, so a permanent
    over-cap state never becomes an infinite loop.
    """
    if not CLONE_CACHE_ENABLED:
        return
    while cache_size() > CLONE_CACHE_MAX_BYTES:
        evicted = False
        for marker in _list_evictable():
            victim_id = marker.stem
            if protect_repo_id is not None and str(victim_id) == str(protect_repo_id):
                continue
            _remove_entry(victim_id)
            evicted = True
            break
        if not evicted:
            return


# --- Git plumbing ---------------------------------------------------------


def _build_clone_url(github_url: str, github_access_token: str | None) -> str:
    """Inject an OAuth token into an HTTPS clone URL for private repo access.

    ``file://`` URLs (used in unit tests against a local sample repo)
    cannot carry OAuth credentials usefully -- they are not parsed as
    basic auth by Git, and the ``user:pass@host`` injection only works
    for schemes that route through libcurl's auth machinery. Tokenless
    local URLs are returned unchanged so a test's repo-cache probe does
    not corrupt the URL into one ``git fetch`` will reject.
    """
    if not github_access_token:
        return github_url
    parsed = urlparse(github_url)
    if parsed.scheme != "https" and parsed.scheme != "http":
        return github_url
    return parsed._replace(netloc=f"{github_access_token}@{parsed.netloc}").geturl()


def _git_env(env_extra: dict | None = None) -> dict:
    """Build the environment for git subprocesses.

    ``GIT_TERMINAL_PROMPT=0`` plus a no-op ``GIT_ASKPASS`` makes a
    credential prompt fail fast instead of hanging the worker.
    Forcing ``GIT_CONFIG_GLOBAL`` and ``GIT_CONFIG_SYSTEM`` to
    ``/dev/null`` keeps the developer's local git config or a system
    gitconfig from changing the fetch behaviour -- in particular, a
    ``protocol.*.allow`` setting could otherwise expand what ``git
    fetch`` permits on an untrusted remote URL.
    """
    return {
        **os.environ,
        "GIT_ASKPASS": "echo",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        **(env_extra or {}),
    }


def _run_git(repo_dir: Path, *args: str, timeout: int, env_extra: dict | None = None) -> str:
    """Run a git subprocess inside ``repo_dir`` with a hard timeout.

    On non-zero exit, raise :class:`git.GitCommandError` so the caller
    can treat any git failure uniformly with how GitPython itself
    reports errors.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        env=_git_env(env_extra),
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise git.GitCommandError(
            list(args),
            result.returncode,
            stderr=result.stderr,
            stdout=result.stdout,
        )
    return result.stdout


def _set_remote_token(repo_dir: Path, github_url: str, access_token: str | None) -> None:
    """Rewrite ``origin`` to embed the *current* access token.

    ``.git/config`` would otherwise hold the token indefinitely, and an
    expired token becomes a permanent 401 on every future fetch unless
    we overwrite it here on every refresh.
    """
    url = _build_clone_url(github_url, access_token)
    _run_git(
        repo_dir,
        "remote",
        "set-url",
        "origin",
        url,
        timeout=GIT_RESET_TIMEOUT_SECONDS,
    )


def _ls_remote_sha(github_url: str, access_token: str | None, branch: str) -> str:
    """Return the head SHA of ``branch`` from the remote, no local clone required.

    The cheap probe that powers the "nothing changed" short-circuit.
    Any failure here propagates to the caller, which decides whether to
    escalate to a full clone.
    """
    url = _build_clone_url(github_url, access_token)
    raw = _run_git(
        Path("."),
        "ls-remote",
        url,
        branch,
        timeout=GIT_LS_REMOTE_TIMEOUT_SECONDS,
    ).strip()
    # ``git ls-remote`` prints ``<sha>\t<refname>`` per line; we asked for
    # one ref, but a non-existent ref yields an empty string.
    if not raw:
        return ""
    return raw.split("\t", 1)[0]


def _fast_forward_clone(
    repo_dir: Path,
    github_url: str,
    access_token: str | None,
    branch: str,
) -> None:
    """Initialize ``repo_dir`` (non-bare), add ``origin`` and fetch ``branch``.

    Wipes any pre-existing contents of ``repo_dir`` first so a half-
    written clone from a previous attempt cannot poison a retry. The
    final ``checkout --track`` lands the working tree on a real local
    branch (not a detached HEAD) so ``active_branch.name`` returns the
    expected name downstream -- the sync path keys branch behaviour on
    it.
    """
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    repo_dir.mkdir(parents=True, exist_ok=True)
    git.Repo.init(repo_dir)
    url = _build_clone_url(github_url, access_token)
    _run_git(
        repo_dir,
        "remote",
        "add",
        "origin",
        url,
        timeout=GIT_RESET_TIMEOUT_SECONDS,
    )
    _run_git(
        repo_dir,
        "fetch",
        "origin",
        branch,
        timeout=GIT_FETCH_TIMEOUT_SECONDS,
    )
    _run_git(
        repo_dir,
        "checkout",
        "--track",
        f"origin/{branch}",
        timeout=GIT_RESET_TIMEOUT_SECONDS,
    )


def _refresh_existing(
    repo_dir: Path,
    github_url: str,
    access_token: str | None,
    branch: str,
) -> None:
    """Reset an already-cloned ``repo_dir`` to the head of ``origin/<branch>``.

    Non-bare clones accumulate untracked files between runs (locally
    generated build artefacts, dropped test caches); ``git clean -fdx``
    takes the tree back to a pristine state so the next
    ``walk_source_files`` walk sees exactly what is committed.
    """
    _set_remote_token(repo_dir, github_url, access_token)
    _run_git(
        repo_dir,
        "fetch",
        "origin",
        branch,
        timeout=GIT_FETCH_TIMEOUT_SECONDS,
    )
    _run_git(
        repo_dir,
        "reset",
        "--hard",
        f"origin/{branch}",
        timeout=GIT_RESET_TIMEOUT_SECONDS,
    )
    _run_git(
        repo_dir,
        "clean",
        "-fdx",
        timeout=GIT_RESET_TIMEOUT_SECONDS,
    )


def _git_head_sha(repo_dir: Path) -> str:
    """The commit SHA the working tree is currently on."""
    return _run_git(
        repo_dir,
        "rev-parse",
        "HEAD",
        timeout=GIT_RESET_TIMEOUT_SECONDS,
    ).strip()


def _git_active_branch(repo_dir: Path) -> str:
    """The branch name the working tree is on, or ``'detached'``."""
    try:
        return git.Repo(repo_dir).active_branch.name
    except (git.InvalidGitRepositoryError, TypeError):
        return "detached"


# --- Ephemeral fallback ----------------------------------------------------


def _ephemeral_clone(
    github_url: str,
    access_token: str | None,
    branch: str | None,
    commit_sha: str | None,
) -> tuple[Path, str, str]:
    """Clone into a fresh ``tempfile.mkdtemp`` directory, returning (path, branch, sha).

    The original ``clone_from`` path, preserved verbatim so the failure
    mode is identical to what the codebase has produced since the start.
    Lives separately from the raising variant so the raise-on-failure
    cleanup can know which directory to remove on error.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="illume_ephemeral_"))
    clone_kwargs: dict = {}
    if branch:
        clone_kwargs["branch"] = branch
    # Full history is only needed when a specific commit must be checked out.
    if not commit_sha:
        clone_kwargs["single_branch"] = True
    clone_url = _build_clone_url(github_url, access_token)
    git_repo = git.Repo.clone_from(clone_url, tmp_dir, **clone_kwargs)
    if commit_sha:
        git_repo.git.checkout(commit_sha)
    try:
        actual_branch = git_repo.active_branch.name
    except TypeError:
        actual_branch = branch or "detached"
    actual_sha = git_repo.head.commit.hexsha
    return tmp_dir, actual_branch, actual_sha


def _ephemeral_clone_raising(
    github_url: str,
    access_token: str | None,
    branch: str | None,
    commit_sha: str | None,
) -> tuple[Path, str, str]:
    """Ephemeral clone that cleans up its directory on failure and re-raises.

    Mirrors :func:`app.services.cloner.clone_repository`'s contract:
    any git error becomes a ``RuntimeError``, and the half-built temp
    directory is removed before the raise so the caller does not have
    to know it existed.
    """
    tmp_dir: Path | None = None
    try:
        tmp_dir, actual_branch, actual_sha = _ephemeral_clone(
            github_url, access_token, branch, commit_sha
        )
        return tmp_dir, actual_branch, actual_sha
    except (git.GitCommandError, OSError, subprocess.TimeoutExpired) as exc:
        if tmp_dir is not None and tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if isinstance(exc, subprocess.TimeoutExpired):
            raise RuntimeError("Git clone timed out") from exc
        raise RuntimeError(f"Git clone/checkout failed: {exc}") from exc


# --- Public API ------------------------------------------------------------


def _head_and_branch(repo_dir: Path) -> tuple[str, str]:
    """Read the working tree's current branch and commit SHA."""
    return _git_active_branch(repo_dir), _git_head_sha(repo_dir)


def ensure_clone(
    repo_id: uuid.UUID | str,
    github_url: str,
    access_token: str | None,
    branch: str,
    commit_sha: str | None = None,
) -> tuple[Path, str, str]:
    """Return a working tree for ``repo_id``, ready for analysis.

    The cache is keyed by ``repo_id``; ``branch`` selects which branch
    the working tree is checked out on. ``commit_sha`` is honoured by
    falling back to an ephemeral clone when set, because the persistent
    cache only tracks a single branch per repo.

    Every failure mode falls back to an ephemeral ``tempfile.mkdtemp``
    clone: unwritable cache root, repository larger than
    ``CLONE_CACHE_MAX_REPO_BYTES``, oversized cache that cannot be
    evicted, git errors, network timeouts. Raising here would deny the
    caller a path to the analysis.
    """
    if not CLONE_CACHE_ENABLED:
        return _ephemeral_clone_raising(github_url, access_token, branch, commit_sha)

    if commit_sha:
        return _ephemeral_clone_raising(github_url, access_token, branch, commit_sha)

    # Probe writability once so the path can fall back cheaply. Reading
    # is cheap; a write probe catches every permission failure mode we
    # care about.
    root = _cache_root()
    try:
        probe = root / ".illume_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        logger.warning(
            "Clone cache root %s is not writable (%s); using ephemeral clone.", root, exc
        )
        return _ephemeral_clone_raising(github_url, access_token, branch, None)

    evict_to_cap(protect_repo_id=repo_id)
    repo_dir = _repo_dir(repo_id)

    try:
        if not repo_dir.is_dir() or not (repo_dir / ".git").exists():
            _fast_forward_clone(repo_dir, github_url, access_token, branch)
        else:
            _refresh_existing(repo_dir, github_url, access_token, branch)
    except (git.GitCommandError, OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "Clone cache refresh failed for %s (%s); falling back to ephemeral clone.",
            repo_id,
            exc,
        )
        _remove_entry(repo_id)
        return _ephemeral_clone_raising(github_url, access_token, branch, None)

    # A single repo larger than the per-repo ceiling is evicted instead
    # of held -- it would otherwise wedge the cache by occupying more
    # than its share of the global cap.
    try:
        size = _dir_size(repo_dir)
    except OSError:
        size = 0
    if size > CLONE_CACHE_MAX_REPO_BYTES:
        logger.warning(
            "Repository %s exceeds per-repo cache ceiling (%d > %d); using ephemeral clone.",
            repo_id,
            size,
            CLONE_CACHE_MAX_REPO_BYTES,
        )
        _remove_entry(repo_id)
        return _ephemeral_clone_raising(github_url, access_token, branch, None)

    actual_branch, actual_sha = _head_and_branch(repo_dir)
    touch(repo_id, actual_branch, actual_sha)
    return repo_dir, actual_branch, actual_sha


def refresh_clone(
    repo_id: uuid.UUID | str,
    github_url: str,
    access_token: str | None,
    branch: str,
) -> tuple[Path, str, str]:
    """Bring an already-cached repo up to the current head of ``branch``.

    No-op when the cache is disabled or the repo is not cached.
    ``ensure_clone`` is called when the cache does not have the repo yet
    -- the two functions cover the full lifecycle from "first seen" to
    "fully populated". Failure to refresh removes the cache entry and
    returns an ephemeral clone.
    """
    if not CLONE_CACHE_ENABLED:
        return _ephemeral_clone_raising(github_url, access_token, branch, None)

    repo_dir = _repo_dir(repo_id)
    if not repo_dir.is_dir() or not (repo_dir / ".git").exists():
        return ensure_clone(repo_id, github_url, access_token, branch)

    try:
        _refresh_existing(repo_dir, github_url, access_token, branch)
    except (git.GitCommandError, OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "Clone cache refresh failed for %s (%s); falling back to ephemeral clone.",
            repo_id,
            exc,
        )
        _remove_entry(repo_id)
        return _ephemeral_clone_raising(github_url, access_token, branch, None)

    actual_branch, actual_sha = _head_and_branch(repo_dir)
    touch(repo_id, actual_branch, actual_sha)
    return repo_dir, actual_branch, actual_sha
