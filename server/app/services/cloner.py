import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import git
from app.models import Repository
from app.services._publish import publish_log
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _update_status(db: Session, redis_client, repo: Repository, status: str) -> None:
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
    # Inject the OAuth token into the clone URL for private repos like https://github.com/user/repo -> https://<token>@github.com/user/repo
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
    _update_status(db, redis_client, repo, "cloning")
    publish_log(redis_client, str(repo.id), "clone_started", f"Cloning repository (branch={branch or 'default'}, commit={commit_sha or 'HEAD'})...")

    clone_url = _build_clone_url(repo.github_url, github_access_token)
    tmp_dir = tempfile.mkdtemp(prefix=f"illume_{repo.id}_")

    try:
        clone_kwargs = {}
        if branch:
            clone_kwargs["branch"] = branch
        if not commit_sha:
            clone_kwargs["single_branch"] = True

        git_repo = git.Repo.clone_from(
            clone_url,
            tmp_dir,
            **clone_kwargs
        )

        if commit_sha:
            publish_log(redis_client, str(repo.id), "checkout_started", f"Checking out commit {commit_sha[:7]}...")
            git_repo.git.checkout(commit_sha)

        try:
            actual_branch = git_repo.active_branch.name
        except TypeError:
            actual_branch = branch or "detached"
        actual_sha = git_repo.head.commit.hexsha

    except git.GitCommandError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"Git clone/checkout failed: {e.stderr.strip()}") from e

    publish_log(redis_client, str(repo.id), "clone_complete", f"Clone complete at branch={actual_branch}, commit={actual_sha[:7]}.")
    return Path(tmp_dir), actual_branch, actual_sha


def cleanup_clone(tmp_dir: Path) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)
