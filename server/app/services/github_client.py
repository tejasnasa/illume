from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from app.models import PullRequest
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
MAX_PRS = 200
PER_PAGE = 100
REQUEST_TIMEOUT = 20.0
MAX_RETRIES = 3

_REDIS_CHANNEL_PREFIX = "ingest:progress"


def fetch_pull_requests(
    repo,
    # access_token: str,
    db: Session,
    redis_client,
) -> int:
    owner, repo_name = _parse_github_url(repo.github_url)

    _publish(
        redis_client,
        repo.id,
        "prs_fetch_started",
        f"Fetching merged PRs for {owner}/{repo_name}",
    )

    prs = _fetch_merged_prs(owner, repo_name)

    if not prs:
        _publish(redis_client, repo.id, "prs_fetch_complete", "No merged PRs found")
        return 0

    inserted = _bulk_insert_pull_requests(db, repo.id, prs)

    _publish(
        redis_client,
        repo.id,
        "prs_fetch_complete",
        f"Stored {inserted} merged pull requests",
    )
    logger.info("repo=%s  Inserted %d PR rows", repo.id, inserted)
    return inserted


def _parse_github_url(github_url: str) -> tuple[str, str]:
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


def _fetch_merged_prs(owner: str, repo_name: str) -> list[dict]:
    headers = {
        # "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

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

            if not raw_page:
                break

            for pr in raw_page:
                if pr.get("merged_at") is None:
                    continue
                results.append(_normalise_pr(pr))

                if len(results) >= MAX_PRS:
                    break

            if len(raw_page) < PER_PAGE:
                break

            page += 1

    return results


def _get_with_retry(
    client: httpx.Client,
    url: str,
    headers: dict,
) -> list[dict]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise GitHubClientError(f"HTTP request failed: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        if response.status_code in (429, 403):
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
    if retry_after := response.headers.get("Retry-After"):
        try:
            return int(retry_after)
        except ValueError:
            pass

    if reset_ts := response.headers.get("X-RateLimit-Reset"):
        try:
            wait = int(reset_ts) - int(time.time())
            return max(wait, 1)
        except ValueError:
            pass

    return 60


def _normalise_pr(raw: dict) -> dict:
    reviewers: list[str] = [
        r["login"]
        for r in (raw.get("requested_reviewers") or [])
        if isinstance(r, dict) and r.get("login")
    ]

    changed_files: int = raw.get("changed_files") or 0

    merged_at_raw: str | None = raw.get("merged_at")
    merged_at: datetime | None = None
    if merged_at_raw:
        try:
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
        .on_conflict_do_nothing(index_elements=["repository_id", "number"])
    )

    db.execute(stmt)
    db.commit()
    return len(rows)


def _publish(
    redis_client,
    repo_id: str,
    event: str,
    message: str,
) -> None:
    channel = f"{_REDIS_CHANNEL_PREFIX}:{repo_id}"
    payload = json.dumps(
        {
            "event": event,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        redis_client.publish(channel, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis publish failed (channel=%s): %s", channel, exc)


class GitHubClientError(Exception):
    pass
