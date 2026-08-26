"""Git repository cloning helpers.

Handles cloning a GitHub repository into a temporary directory (with optional
OAuth token injection for private repos), checking out a specific branch or
commit, and cleaning up the clone afterwards.
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

logger = logging.getLogger(__name__)


def _update_status(db: Session, redis_client, repo: Repository, status: str) -> None:
    """Persist a new repo status and broadcast it over the log stream."""
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


def clone_repository(
    db: Session,
    redis_client,
    repo: Repository,
    github_access_token: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> tuple[Path, str, str]:
    """Clone a repository into a fresh temp directory.

    Args:
        db: Database session used to persist status changes.
        redis_client: Redis client for publishing progress logs.
        repo: Repository record containing the GitHub URL.
        github_access_token: Optional OAuth token injected into the clone URL
            for private repositories.
        branch: Optional branch to check out instead of the default.
        commit_sha: Optional commit SHA to check out after cloning. When set,
            the full history is fetched so detached checkout is possible.

    Returns:
        Tuple of (clone directory path, actual branch name, actual commit SHA).
        The branch is "detached" when a specific commit is checked out.

    Raises:
        RuntimeError: If the git clone or checkout command fails. The temp
            directory is removed before raising.
    """
    _update_status(db, redis_client, repo, "cloning")
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


def cleanup_clone(tmp_dir: Path) -> None:
    """Recursively delete a cloned temp directory, ignoring errors."""
    shutil.rmtree(tmp_dir, ignore_errors=True)
