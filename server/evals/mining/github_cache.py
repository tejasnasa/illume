"""On-disk cache of merged pull requests.

Mining writes one JSON file per pull request; ingestion reads them back. The layout is
``<cache_dir>/<owner>__<repo>/prs/<number>.json`` with a stable key order, so a refetch of
unchanged data rewrites byte-identical files and the cache diffs cleanly.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CachedPRFile:
    """One file touched by a pull request.

    Attributes:
        path: Repo-relative path after the change.
        status: GitHub's file status (``added``, ``modified``, ``removed``, ``renamed``...).
        previous_path: The path before a rename, otherwise ``None``.
        additions: Lines added.
        deletions: Lines deleted.
    """

    path: str
    status: str
    previous_path: str | None
    additions: int
    deletions: int


@dataclass(frozen=True)
class CachedPR:
    """One merged pull request as stored in the cache.

    Attributes:
        number: The pull request number.
        title: The title.
        body: The description; empty when there is none.
        author: The author's login.
        merged_at: When it merged, timezone-aware.
        merge_commit_sha: The commit the merge produced on the base branch.
        files: The files it touched, or ``None`` when they were not fetched (pull requests
            merged before the base commit only need their text).
        labels: Label names.
        user_type: GitHub's account type for the author (``User``, ``Bot``...).
    """

    number: int
    title: str
    body: str
    author: str
    merged_at: datetime
    merge_commit_sha: str
    files: tuple[CachedPRFile, ...] | None
    labels: tuple[str, ...]
    user_type: str


def repo_dir(cache_dir: Path, repo_slug: str) -> Path:
    """Return the directory holding one repository's cached data.

    Args:
        cache_dir: The cache root.
        repo_slug: ``owner/repo``.

    Returns:
        ``<cache_dir>/<owner>__<repo>``.
    """
    return Path(cache_dir) / repo_slug.replace("/", "__")


def _pr_to_dict(pr: CachedPR) -> dict:
    """Serialise a pull request with a fixed key order."""
    return {
        "number": pr.number,
        "title": pr.title,
        "body": pr.body,
        "author": pr.author,
        "merged_at": pr.merged_at.isoformat(),
        "merge_commit_sha": pr.merge_commit_sha,
        "files": (
            None
            if pr.files is None
            else [
                {
                    "path": f.path,
                    "status": f.status,
                    "previous_path": f.previous_path,
                    "additions": f.additions,
                    "deletions": f.deletions,
                }
                for f in pr.files
            ]
        ),
        "labels": list(pr.labels),
        "user_type": pr.user_type,
    }


def _pr_from_dict(raw: dict) -> CachedPR:
    """Rebuild a pull request from its serialised form."""
    files = raw["files"]
    return CachedPR(
        number=raw["number"],
        title=raw["title"],
        body=raw["body"],
        author=raw["author"],
        merged_at=datetime.fromisoformat(raw["merged_at"]),
        merge_commit_sha=raw["merge_commit_sha"],
        files=(
            None
            if files is None
            else tuple(
                CachedPRFile(
                    path=f["path"],
                    status=f["status"],
                    previous_path=f["previous_path"],
                    additions=f["additions"],
                    deletions=f["deletions"],
                )
                for f in files
            )
        ),
        labels=tuple(raw["labels"]),
        user_type=raw["user_type"],
    )


def save_pr(cache_dir: Path, repo_slug: str, pr: CachedPR) -> Path:
    """Write one pull request to the cache, replacing any earlier copy.

    Args:
        cache_dir: The cache root.
        repo_slug: ``owner/repo``.
        pr: The pull request to store.

    Returns:
        The file written.
    """
    target = repo_dir(cache_dir, repo_slug) / "prs" / f"{pr.number}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_pr_to_dict(pr), indent=2, ensure_ascii=False) + "\n"
    target.write_bytes(text.encode("utf-8"))
    return target


def load_prs(cache_dir: Path, repo_slug: str) -> list[CachedPR]:
    """Read every cached pull request for a repository.

    Args:
        cache_dir: The cache root.
        repo_slug: ``owner/repo``.

    Returns:
        The pull requests sorted by number; empty when nothing is cached.
    """
    prs_dir = repo_dir(cache_dir, repo_slug) / "prs"
    if not prs_dir.is_dir():
        return []
    prs = [
        _pr_from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in prs_dir.glob("*.json")
    ]
    return sorted(prs, key=lambda pr: pr.number)
