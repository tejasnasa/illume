"""GitHub REST helpers shared by the pull request fetcher and the file reader."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

DEFAULT_RETRY_AFTER_SECONDS = 60


def parse_github_url(github_url: str) -> tuple[str, str]:
    """Extracts ``(owner, repo_name)`` from a GitHub URL, stripping a ``.git`` suffix.

    Raises:
        ValueError: When the URL has no owner and repository segments.
    """
    url = github_url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"

    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Cannot parse owner/repo from URL: {github_url!r}")
    return parts[0], parts[1].removesuffix(".git")


def retry_after_seconds(response: httpx.Response) -> int:
    """How long GitHub asks the caller to wait before retrying.

    Prefers ``Retry-After`` (an explicit delay), then the time until the epoch in
    ``X-RateLimit-Reset``, then :data:`DEFAULT_RETRY_AFTER_SECONDS`. Both headers
    are optional on real responses, and a malformed value is ignored.
    """
    if retry_after := response.headers.get("Retry-After"):
        try:
            return int(retry_after)
        except ValueError:
            pass

    if reset_ts := response.headers.get("X-RateLimit-Reset"):
        try:
            # Clock skew could yield a non-positive wait; always ask for at least a second.
            return max(int(reset_ts) - int(time.time()), 1)
        except ValueError:
            pass

    return DEFAULT_RETRY_AFTER_SECONDS


def is_rate_limited(response: httpx.Response) -> bool:
    """Whether a response is GitHub refusing because a rate limit is used up.

    A 429 always is. GitHub also answers 403 for a limit, and for a token that
    lacks access; only a 403 carrying ``Retry-After`` or an exhausted
    ``X-RateLimit-Remaining`` is counted as the former.
    """
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    return "Retry-After" in response.headers or response.headers.get("X-RateLimit-Remaining") == "0"
