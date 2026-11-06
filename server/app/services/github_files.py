"""Whole-file reads from GitHub at a pinned commit.

Ingestion stores symbol bodies, not files, so a file that has to be read in full
comes from the GitHub Contents API at the commit the repository was ingested at.
Nothing is cached: every read is a request, and file text is held only for the
length of the call that asked for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from app.services.github_http import (
    GITHUB_API_BASE,
    GITHUB_API_VERSION,
    is_rate_limited,
    parse_github_url,
    retry_after_seconds,
)

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024
BINARY_SNIFF_BYTES = 8192
REQUEST_TIMEOUT_SECONDS = 20.0

FetchStatus = Literal[
    "ok", "not_found", "rate_limited", "denied", "too_large", "binary", "unavailable"
]


@dataclass(frozen=True)
class FileFetch:
    """The outcome of reading one file.

    Attributes:
        status: ``ok`` when ``content`` is set; otherwise why it is not.
        content: The decoded text, for ``ok``.
        message: A readable explanation for any status other than ``ok``.
        retry_after: Seconds GitHub asked the caller to wait, for ``rate_limited``.
    """

    status: FetchStatus
    content: str | None = None
    message: str = ""
    retry_after: int | None = None


def _too_large(size: int | None) -> FileFetch:
    shown = f"{size:,} bytes" if size is not None else f"over {MAX_FILE_BYTES:,} bytes"
    return FileFetch(
        "too_large",
        message=(
            f"The file is {shown}; the limit is {MAX_FILE_BYTES:,}. "
            "Use read_symbol or grep_code to reach the part you need."
        ),
    )


def _accept(data: bytes) -> FileFetch:
    if len(data) > MAX_FILE_BYTES:
        return _too_large(len(data))
    if b"\x00" in data[:BINARY_SNIFF_BYTES]:
        return FileFetch("binary", message="The file is binary and cannot be shown as text.")
    return FileFetch("ok", content=data.decode("utf-8", errors="replace"))


def _failure(response: httpx.Response, *, authenticated: bool, commit_sha: str) -> FileFetch:
    status = response.status_code
    if is_rate_limited(response):
        wait = retry_after_seconds(response)
        hint = "" if authenticated else " Requests are unauthenticated, which allows 60 per hour."
        return FileFetch(
            "rate_limited",
            message=f"GitHub's rate limit is used up; retry in about {wait} seconds.{hint}",
            retry_after=wait,
        )
    if status == 404:
        return FileFetch(
            "not_found",
            message=(
                f"The file is not at commit {commit_sha[:8]} on GitHub. The repository may be "
                "private to a token that is not available, or the commit may no longer exist."
            ),
        )
    if status in (401, 403):
        hint = (
            ""
            if authenticated
            else " The request was unauthenticated; a private repository needs its owner's token."
        )
        return FileFetch("denied", message=f"GitHub refused access ({status}).{hint}")
    return FileFetch("unavailable", message=f"GitHub answered {status}; try again later.")


async def _download(
    *, github_url: str, commit_sha: str, path: str, token: str | None
) -> bytes | FileFetch:
    """The file's bytes, or the typed reason they could not be had."""
    try:
        owner, name = parse_github_url(github_url)
    except ValueError:
        return FileFetch("unavailable", message="The repository's GitHub address is not valid.")

    url = (
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
        f"/contents/{quote(path, safe='/')}"
    )
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with (
            httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client,
            client.stream("GET", url, params={"ref": commit_sha}, headers=headers) as response,
        ):
            if response.status_code != 200:
                return _failure(response, authenticated=bool(token), commit_sha=commit_sha)
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > MAX_FILE_BYTES:
                return _too_large(int(declared))
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_FILE_BYTES:
                    return _too_large(None)
            return bytes(body)
    except httpx.HTTPError as error:
        logger.warning("GitHub file request failed: %s", type(error).__name__)
        return FileFetch("unavailable", message="GitHub could not be reached; try again later.")


async def fetch_file(
    *,
    github_url: str,
    commit_sha: str,
    path: str,
    token: str | None,
) -> FileFetch:
    """Reads one file at one commit from GitHub.

    The caller is responsible for ``path`` being safe and belonging to the
    repository; this only moves bytes.

    Args:
        github_url: The repository's GitHub address.
        commit_sha: The commit to read at.
        path: Repository-relative path.
        token: The owner's GitHub token, or ``None`` to read unauthenticated.
    """
    downloaded = await _download(
        github_url=github_url, commit_sha=commit_sha, path=path, token=token
    )
    if isinstance(downloaded, FileFetch):
        return downloaded
    return _accept(downloaded)
