"""GitHub pull request fetching service.

Fetches merged pull requests from the GitHub API (paginated, with rate-limit
retry handling) and persists them for a repository, publishing progress
events to Redis along the way.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import PullRequest
from app.services._publish import publish_log

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
MAX_PRS = 200
PER_PAGE = 100
REQUEST_TIMEOUT = 20.0
MAX_RETRIES = 3


def fetch_pull_requests(
    repo,
    access_token: str | None,
    db: Session,
    redis_client,
) -> int:
    """Fetch merged PRs from GitHub and store them in the database.

    Parses the repository's ``github_url``, fetches up to ``MAX_PRS`` merged
    pull requests via the GitHub REST API (paginated at ``PER_PAGE`` per page,
    stopping early when a short page or an unmerged PR run is exhausted), and
    bulk-inserts them idempotently on ``(repository_id, number)``. Progress is
    published to Redis before and after the fetch.

    Args:
        repo: Repository model instance with ``id`` and ``github_url``.
        access_token: Optional GitHub token; unauthenticated requests are
            subject to stricter rate limits.
        db: SQLAlchemy session used to persist the PR rows.
        redis_client: Redis client for publishing progress log events.

    Returns:
        The number of PR rows written (including rows that already existed and
        were skipped by the conflict clause).

    Raises:
        GitHubClientError: If the URL cannot be parsed, the API returns an
            error status, the token is invalid/expired, or the rate limit is
            exceeded after ``MAX_RETRIES`` retries.
    """
    owner, repo_name = _parse_github_url(repo.github_url)

    publish_log(
        redis_client,
        repo.id,
        "prs_fetch_started",
        f"Fetching merged PRs for {owner}/{repo_name}",
    )

    prs = _fetch_merged_prs(owner, repo_name, access_token)

    if not prs:
        publish_log(redis_client, repo.id, "prs_fetch_complete", "No merged PRs found")
        return 0

    inserted = _bulk_insert_pull_requests(db, repo.id, prs)

    publish_log(
        redis_client,
        repo.id,
        "prs_fetch_complete",
        f"Stored {inserted} merged pull requests",
    )
    logger.info("repo=%s  Inserted %d PR rows", repo.id, inserted)
    return inserted


def _parse_github_url(github_url: str) -> tuple[str, str]:
    """Extract (owner, repo_name) from a GitHub URL, stripping a .git suffix."""
    url = github_url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"

    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]

    if len(parts) < 2:
        raise GitHubClientError(f"Cannot parse owner/repo from URL: {github_url!r}")

    owner = parts[0]
    repo_name = parts[1].removesuffix(".git")
    return owner, repo_name


def _fetch_merged_prs(
    owner: str, repo_name: str, access_token: str | None
) -> list[dict]:
    """Page through closed PRs, keeping only merged ones, capped at MAX_PRS."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    results: list[dict] = []
    page = 1

    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        while len(results) < MAX_PRS:
            url = (
                f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/pulls"
                f"?state=closed&sort=updated&direction=desc"
                f"&per_page={PER_PAGE}&page={page}"
            )

            raw_page = _get_with_retry(client, url, headers)

            # Empty page means we've walked past the last PR.
            if not raw_page:
                break

            for pr in raw_page:
                # Closed-but-unmerged PRs are rejected; since results are
                # sorted by updated desc, unmerged runs can still be followed
                # by merged ones, so keep scanning rather than stopping here.
                if pr.get("merged_at") is None:
                    continue
                results.append(_normalise_pr(pr))

                if len(results) >= MAX_PRS:
                    break

            # A short page is the API's signal there are no further pages.
            if len(raw_page) < PER_PAGE:
                break

            page += 1

    return results


def _get_with_retry(
    client: httpx.Client,
    url: str,
    headers: dict,
) -> list[dict]:
    """GET a URL, retrying on 429/403 rate limits using Retry-After hints."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise GitHubClientError(f"HTTP request failed: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        if response.status_code in (429, 403):
            # 403 is included because GitHub also signals rate limiting with it;
            # honour the server-provided wait instead of a fixed backoff.
            retry_after = _parse_retry_after(response)
            logger.warning(
                "GitHub rate limit hit (attempt %d/%d). Waiting %ds.",
                attempt,
                MAX_RETRIES,
                retry_after,
            )
            if attempt < MAX_RETRIES:
                time.sleep(retry_after)
                continue
            raise GitHubClientError(
                f"GitHub rate limit exceeded after {MAX_RETRIES} retries"
            )

        if response.status_code == 404:
            raise GitHubClientError(
                f"Repository not found or token lacks access: {url}"
            )

        if response.status_code == 401:
            raise GitHubClientError(
                "GitHub token is invalid or expired (401 Unauthorized)"
            )

        raise GitHubClientError(
            f"GitHub API returned {response.status_code}: {response.text[:200]}"
        )
    raise GitHubClientError("Exhausted retries without a successful response")


def _parse_retry_after(response: httpx.Response) -> int:
    """Derive wait seconds from Retry-After / X-RateLimit-Reset, default 60."""
    # Prefer Retry-After (explicit delay); fall back to computing seconds
    # until the reset epoch timestamp; both are optional on real responses.
    if retry_after := response.headers.get("Retry-After"):
        try:
            return int(retry_after)
        except ValueError:
            pass

    if reset_ts := response.headers.get("X-RateLimit-Reset"):
        try:
            wait = int(reset_ts) - int(time.time())
            # Clock skew could yield <=0; always sleep at least 1s.
            return max(wait, 1)
        except ValueError:
            pass

    return 60


def _normalise_pr(raw: dict) -> dict:
    """Map a raw GitHub PR payload to the shape used for DB insertion."""
    reviewers: list[str] = [
        r["login"]
        for r in (raw.get("requested_reviewers") or [])
        # GitHub occasionally returns null entries or logins-only payloads.
        if isinstance(r, dict) and r.get("login")
    ]

    changed_files: int = raw.get("changed_files") or 0

    merged_at_raw: str | None = raw.get("merged_at")
    merged_at: datetime | None = None
    if merged_at_raw:
        try:
            # 'Z' isn't accepted by fromisoformat before Python 3.11.
            merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Could not parse merged_at %r", merged_at_raw)

    return {
        "number": raw["number"],
        "title": (raw.get("title") or "").strip(),
        "description": (raw.get("body") or "").strip(),
        "author": (raw.get("user") or {}).get("login", ""),
        "reviewers": reviewers,
        "files_changed": changed_files,
        "merged_at": merged_at,
    }


def _bulk_insert_pull_requests(
    db: Session,
    repo_id: str,
    prs: list[dict],
) -> int:
    """Bulk-insert PR rows, skipping duplicates on (repository_id, number)."""

    if not prs:
        return 0

    rows = [
        {
            "repository_id": repo_id,
            "number": pr["number"],
            "title": pr["title"],
            "description": pr["description"],
            "author": pr["author"],
            "reviewers": json.dumps(pr["reviewers"]),
            "files_changed": pr["files_changed"],
            "merged_at": pr["merged_at"],
        }
        for pr in prs
    ]

    stmt = (
        pg_insert(PullRequest)
        .values(rows)
        # Refetches overlap heavily with stored PRs; skip existing rows so
        # reruns are idempotent. Returned count includes skipped rows.
        .on_conflict_do_nothing(index_elements=["repository_id", "number"])
    )

    db.execute(stmt)
    db.commit()
    return len(rows)


class GitHubClientError(Exception):
    """Raised for any GitHub API failure (bad URL, HTTP error, rate limits)."""

    pass
