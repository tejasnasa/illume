"""Git repository cloning helpers.

Handles cloning a GitHub repository into a temporary directory (with optional
OAuth token injection for private repos), checking out a specific branch or
commit, and cleaning up the clone afterwards.

When the persistent clone cache is enabled, ``clone_repository`` delegates to
:mod:`app.services.repo_cache` instead of cloning into a fresh ``mkdtemp``
directory. The return contract (``(path, branch, commit_sha)``) is identical,
so call sites are unchanged. Every failure inside the cache layer falls back
to an ephemeral clone, so wiping the cache or disabling the kill switch
restores the original behaviour.
"""

import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import git
from sqlalchemy.orm import Session

from app.models import Repository
from app.services._publish import publish_log
from app.services.repo_cache import CLONE_CACHE_ENABLED
from app.services.repo_cache import ensure_clone as _ensure_cached_clone
from app.services.repo_cache import refresh_clone as _refresh_cached_clone

logger = logging.getLogger(__name__)


def _update_status(
    db: Session,
    redis_client,
    repo: Repository,
    status: str,
    manage_status: bool = True,
) -> None:
    """Persist a new repo status and broadcast it over the log stream.

    ``manage_status=False`` is the sync path's escape hatch: a background
    sync must leave ``status='ready'`` alone, so this becomes a no-op for
    the row and the log stream. The frame is suppressed rather than the
    rest of the work, because ``status_update`` frames are what the
    client's ``TerminalLogs`` mounts on -- emitting one mid-sync would
    mount a useless panel against a row that never actually transitioned.
    """
    if not manage_status:
        return
    repo.status = status
    db.commit()
    publish_log(
        redis_client,
        str(repo.id),
        "status_update",
        f"Status changed to {status}",
        status=status,
    )


def _build_clone_url(github_url: str, github_access_token: str | None) -> str:
    """Inject an OAuth token into an HTTPS clone URL for private repo access."""
    if not github_access_token:
        return github_url

    parsed = urlparse(github_url)
    return parsed._replace(netloc=f"{github_access_token}@{parsed.netloc}").geturl()


def _branch_for(repo: Repository, branch: str | None) -> str:
    """Resolve the branch argument into something git can fetch by name.

    ``Repository.default_branch`` is not written by the pipeline in
    production (it is always NULL) -- the plan documents ``illume_exporter``
    papering over the gap with ``or 'main'``. Failing back to ``main``
    here keeps the contract working when ``branch`` was not supplied and
    keeps the cache layer from having to know about the column's history.
    """
    if branch:
        return branch
    if repo.default_branch and repo.default_branch != "detached":
        return repo.default_branch
    return "main"


def clone_repository(
    db: Session,
    redis_client,
    repo: Repository,
    github_access_token: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
    manage_status: bool = True,
) -> tuple[Path, str, str]:
    """Clone a repository into a working tree and return ``(path, branch, sha)``.

    When the persistent clone cache is enabled, the working tree is a
    persistent non-bare clone under the cache root and every later
    invocation against the same repo reuses the same on-disk contents
    (a fetch + reset to bring it up to date). When the cache is
    disabled, the original ``tempfile.mkdtemp`` path is restored, with
    the same per-call ``shutil.rmtree`` cleanup at the caller's
    discretion.

    Args:
        db: Database session used to persist status changes.
        redis_client: Redis client for publishing progress logs.
        repo: Repository record containing the GitHub URL.
        github_access_token: Optional OAuth token injected into the clone URL
            for private repositories.
        branch: Optional branch to check out instead of the default.
        commit_sha: Optional commit SHA to check out after cloning. When set,
            the full history is fetched so detached checkout is possible; the
            persistent cache cannot honour a pinned commit, so this falls back
            to an ephemeral clone.
        manage_status: When ``False``, suppress the ``status='cloning'``
            flip and the ``status_update`` log frame. The sync task runs
            against an already-ready repo and uses this to keep the row,
            the graph endpoint and the live-log panel from reacting.

    Returns:
        Tuple of (clone directory path, actual branch name, actual commit SHA).
        The branch is "detached" when a specific commit is checked out.

    Raises:
        RuntimeError: If the git clone or checkout command fails. For
            ephemeral clones the temp directory is removed before raising;
            for cached clones the cache entry is removed before raising.
    """
    _update_status(db, redis_client, repo, "cloning", manage_status=manage_status)

    target_branch = _branch_for(repo, branch)

    if CLONE_CACHE_ENABLED:
        # Status/log framing for the cache path deliberately mirrors the
        # ephemeral path -- ``clone_started``/``clone_complete`` are the
        # frames the TerminalLogs panel already keys off.
        publish_log(
            redis_client,
            str(repo.id),
            "clone_started",
            f"Preparing repository (branch={target_branch}, commit={commit_sha or 'HEAD'})...",
        )
        path, actual_branch, actual_sha = _ensure_cached_clone(
            repo.id,
            repo.github_url,
            github_access_token,
            target_branch,
            commit_sha=commit_sha,
        )
        publish_log(
            redis_client,
            str(repo.id),
            "clone_complete",
            f"Clone complete at branch={actual_branch}, commit={actual_sha[:7]}.",
        )
        return path, actual_branch, actual_sha

    publish_log(
        redis_client,
        str(repo.id),
        "clone_started",
        f"Cloning repository (branch={branch or 'default'}, commit={commit_sha or 'HEAD'})...",
    )

    clone_url = _build_clone_url(repo.github_url, github_access_token)
    tmp_dir = tempfile.mkdtemp(prefix=f"illume_{repo.id}_")

    try:
        clone_kwargs = {}
        if branch:
            clone_kwargs["branch"] = branch
        # Full history is only needed when a specific commit must be checked out.
        if not commit_sha:
            clone_kwargs["single_branch"] = True

        git_repo = git.Repo.clone_from(clone_url, tmp_dir, **clone_kwargs)

        if commit_sha:
            publish_log(
                redis_client,
                str(repo.id),
                "checkout_started",
                f"Checking out commit {commit_sha[:7]}...",
            )
            git_repo.git.checkout(commit_sha)

        try:
            actual_branch = git_repo.active_branch.name
        except TypeError:
            # Detached HEAD has no active branch (GitPython raises TypeError).
            actual_branch = branch or "detached"
        actual_sha = git_repo.head.commit.hexsha

    except git.GitCommandError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"Git clone/checkout failed: {e.stderr.strip()}") from e

    publish_log(
        redis_client,
        str(repo.id),
        "clone_complete",
        f"Clone complete at branch={actual_branch}, commit={actual_sha[:7]}.",
    )
    return Path(tmp_dir), actual_branch, actual_sha


def refresh_repository(
    db: Session,
    redis_client,
    repo: Repository,
    github_access_token: str | None = None,
    branch: str | None = None,
) -> tuple[Path, str, str]:
    """Bring an already-cloned cached repo up to the current head of ``branch``.

    No-op-safe when the cache is disabled -- falls through to a fresh
    ephemeral clone, identical to :func:`clone_repository`. Provided as
    a public entry point so the sync task can rely on the cache layer
    directly instead of duplicating the ``git fetch`` /
    ``git reset --hard`` plumbing here.

    The returned path is the same directory across invocations for one
    repo when the cache is enabled, so callers must not delete it on
    shutdown -- the cache owns the lifecycle now.
    """
    target_branch = _branch_for(repo, branch)
    return _refresh_cached_clone(
        repo.id,
        repo.github_url,
        github_access_token,
        target_branch,
    )


def cleanup_clone(tmp_dir: Path) -> None:
    """Recursively delete a cloned temp directory, ignoring errors."""
    shutil.rmtree(tmp_dir, ignore_errors=True)
