"""Build the on-disk GitHub cache for one repository.

The cache holds merged pull requests on both sides of the base commit ``B``: up to
``history_prs`` merged before it (text only, they become retrievable history) and every one
merged after it that the default branch contains (with the files they touched, since those
become questions). After the first build the cache is the source of truth and a repeat
call makes no network request.

The harness has its own HTTP client; the token is only ever sent in the ``Authorization``
header and is never logged, printed or written to disk.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from evals.mining.clones import default_tip, is_ancestor
from evals.mining.github_cache import (
    CachedPR,
    CachedPRFile,
    load_prs,
    repo_dir,
    save_pr,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "illume-eval-harness"
DEFAULT_MAX_PAGES = 50
MAX_ATTEMPTS = 5
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60
BACKOFF_BASE_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0


class GitHubError(RuntimeError):
    """Raised when GitHub keeps failing or answers with a client error."""


@dataclass(frozen=True)
class CacheSummary:
    """What a cache holds for one base commit.

    Attributes:
        base_commit: The commit ``B`` the cache was classified against.
        pre_base: Numbers of cached pull requests merged before ``B``, ascending.
        post_base: Numbers of cached pull requests merged after ``B``, ascending.
        skipped: Numbers of merged pull requests whose merge commit is not on the default
            branch (or not in the clone), ascending; these are not stored.
        fetched_at: When the cache was built, ISO 8601.
        from_cache: Whether this summary was read from disk without any request.
    """

    base_commit: str
    pre_base: tuple[int, ...]
    post_base: tuple[int, ...]
    skipped: tuple[int, ...]
    fetched_at: str
    from_cache: bool = field(default=False, compare=False)


def make_client(token: str, *, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Build the HTTP client used for mining.

    Args:
        token: A GitHub token; sent only as a bearer credential.
        transport: Replaces the network transport; tests pass a mock.

    Returns:
        A client with GitHub's JSON media type and API version preset.
    """
    return httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": USER_AGENT,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
        transport=transport,
    )


def index_path(cache_dir: Path, slug: str) -> Path:
    """Return the path of a repository's ``index.json``."""
    return repo_dir(cache_dir, slug) / "index.json"


def load_index(cache_dir: Path, slug: str) -> CacheSummary | None:
    """Read a repository's index from disk.

    Args:
        cache_dir: The cache root.
        slug: ``owner/repo``.

    Returns:
        The summary, or ``None`` when there is no readable index.
    """
    path = index_path(cache_dir, slug)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CacheSummary(
            base_commit=raw["base_commit"],
            pre_base=tuple(raw["pre_base"]),
            post_base=tuple(raw["post_base"]),
            skipped=tuple(raw["skipped"]),
            fetched_at=raw["fetched_at"],
            from_cache=True,
        )
    except ValueError, KeyError, TypeError:
        return None


def _write_index(cache_dir: Path, slug: str, summary: CacheSummary) -> None:
    """Write ``index.json`` with a fixed key order."""
    target = index_path(cache_dir, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_commit": summary.base_commit,
        "fetched_at": summary.fetched_at,
        "pre_base": list(summary.pre_base),
        "post_base": list(summary.post_base),
        "skipped": list(summary.skipped),
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _wait_seconds(response: httpx.Response) -> int:
    """How long GitHub asks the caller to wait after a rate-limit response."""
    if retry_after := response.headers.get("Retry-After"):
        try:
            return max(int(retry_after), 0)
        except ValueError:
            pass
    if reset := response.headers.get("X-RateLimit-Reset"):
        try:
            return max(int(reset) - int(time.time()), 1)
        except ValueError:
            pass
    return DEFAULT_RATE_LIMIT_WAIT_SECONDS


def _is_rate_limited(response: httpx.Response) -> bool:
    """Whether a response is GitHub refusing because a rate limit is used up."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    return "Retry-After" in response.headers or response.headers.get("X-RateLimit-Remaining") == "0"


def _get(
    client: httpx.Client,
    url: str,
    params: dict | None,
    sleep: Callable[[float], None],
) -> httpx.Response:
    """GET with bounded retries for rate limits, server errors and dropped connections.

    Raises:
        GitHubError: On a client error that is not a rate limit, or when every attempt fails.
    """
    last = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            last = f"transport error: {type(exc).__name__}"
            sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        status = response.status_code
        if status < 400:
            return response
        if _is_rate_limited(response):
            wait = _wait_seconds(response)
            last = f"rate limited ({status})"
            logger.warning("github rate limit, waiting %ss", wait)
            sleep(wait)
            continue
        if status >= 500:
            last = f"server error ({status})"
            sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        raise GitHubError(f"GET {httpx.URL(url).path} failed with status {status}")
    raise GitHubError(f"GET {httpx.URL(url).path} gave up after {MAX_ATTEMPTS} attempts: {last}")


def _paginate(
    client: httpx.Client,
    url: str,
    params: dict,
    sleep: Callable[[float], None],
):
    """Yield each page's decoded JSON list, following ``Link: rel="next"``."""
    next_url: str | None = url
    next_params: dict | None = params
    while next_url:
        response = _get(client, next_url, next_params, sleep)
        yield response.json()
        link = response.links.get("next")
        next_url = link["url"] if link else None
        next_params = None


def _parse_time(value: str) -> datetime:
    """Parse a GitHub timestamp as timezone-aware."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _pr_from_payload(raw: dict) -> CachedPR:
    """Build a cached pull request (without files) from a list-endpoint item."""
    user = raw.get("user") or {}
    return CachedPR(
        number=raw["number"],
        title=raw.get("title") or "",
        body=raw.get("body") or "",
        author=user.get("login") or "ghost",
        merged_at=_parse_time(raw["merged_at"]),
        merge_commit_sha=raw["merge_commit_sha"],
        files=None,
        labels=tuple(label["name"] for label in raw.get("labels") or []),
        user_type=user.get("type") or "User",
    )


def _fetch_files(
    client: httpx.Client, owner: str, repo: str, number: int, sleep: Callable[[float], None]
) -> tuple[CachedPRFile, ...]:
    """Fetch every file a pull request touched."""
    files: list[CachedPRFile] = []
    for page in _paginate(
        client,
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/files",
        {"per_page": 100},
        sleep,
    ):
        for item in page:
            files.append(
                CachedPRFile(
                    path=item["filename"],
                    status=item.get("status", "modified"),
                    previous_path=item.get("previous_filename"),
                    additions=item.get("additions", 0),
                    deletions=item.get("deletions", 0),
                )
            )
    return tuple(files)


def build_cache(
    client: httpx.Client,
    *,
    owner: str,
    repo: str,
    cache_dir: Path,
    clone: Path,
    base_commit: str,
    history_prs: int = 200,
    max_pages: int = DEFAULT_MAX_PAGES,
    refresh: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> CacheSummary:
    """Fetch merged pull requests around the base commit and store them on disk.

    Pull requests are listed newest-created first and classified by ancestry in the
    clone, not by date: pre-``B`` when the merge commit is an ancestor of ``B``, post-``B``
    when it is on the default branch's history but not an ancestor of ``B``, otherwise
    skipped. Paging stops once ``history_prs`` pre-``B`` pull requests are found, the
    listing ends, or ``max_pages`` pages were read. Post-``B`` pull requests also get their
    file lists.

    A request is retried on rate limits (honouring ``Retry-After`` or
    ``X-RateLimit-Reset``), on server errors and on dropped connections, up to a bounded
    number of attempts. If ``index.json`` already records this base commit and ``refresh``
    is false, nothing is requested. Pull requests already on disk are reused, and so are
    their file lists.

    Args:
        client: The HTTP client (see ``make_client``).
        owner: Repository owner.
        repo: Repository name.
        cache_dir: The cache root.
        clone: A clone containing ``base_commit`` and the default branch.
        base_commit: The pinned commit ``B``.
        history_prs: How many pre-``B`` pull requests to keep.
        max_pages: The most listing pages to read.
        refresh: Ignore the index and any stored pull request and fetch again.
        sleep: Called with the number of seconds to wait; replaceable for tests.

    Returns:
        The summary that was written (or, on a cache hit, read).

    Raises:
        GitHubError: If GitHub keeps failing or returns a client error.
        RuntimeError: If the clone has no default branch tip.
    """
    slug = f"{owner}/{repo}"
    if not refresh:
        cached = load_index(cache_dir, slug)
        if cached is not None and cached.base_commit == base_commit:
            return cached

    tip = default_tip(clone)
    if tip is None:
        raise RuntimeError(f"cannot resolve the default branch tip in {clone}")

    on_disk = {} if refresh else {pr.number: pr for pr in load_prs(cache_dir, slug)}
    pre: list[CachedPR] = []
    post: list[CachedPR] = []
    skipped: list[int] = []
    seen: set[int] = set()

    pages = 0
    for page in _paginate(
        client,
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
        {"state": "closed", "sort": "created", "direction": "desc", "per_page": 100},
        sleep,
    ):
        pages += 1
        for raw in page:
            if not raw.get("merged_at") or not raw.get("merge_commit_sha"):
                continue
            number = raw["number"]
            if number in seen:
                continue
            seen.add(number)
            sha = raw["merge_commit_sha"]
            if is_ancestor(clone, sha, base_commit):
                pre.append(on_disk.get(number) or _pr_from_payload(raw))
            elif is_ancestor(clone, sha, tip):
                post.append(on_disk.get(number) or _pr_from_payload(raw))
            else:
                skipped.append(number)
        if len(pre) >= history_prs or pages >= max_pages:
            break

    pre.sort(key=lambda pr: (pr.merged_at, pr.number), reverse=True)
    pre = pre[:history_prs]

    for pr in pre:
        save_pr(cache_dir, slug, pr)
    for pr in post:
        if pr.files is None:
            pr = CachedPR(
                number=pr.number,
                title=pr.title,
                body=pr.body,
                author=pr.author,
                merged_at=pr.merged_at,
                merge_commit_sha=pr.merge_commit_sha,
                files=_fetch_files(client, owner, repo, pr.number, sleep),
                labels=pr.labels,
                user_type=pr.user_type,
            )
        save_pr(cache_dir, slug, pr)

    summary = CacheSummary(
        base_commit=base_commit,
        pre_base=tuple(sorted(pr.number for pr in pre)),
        post_base=tuple(sorted(pr.number for pr in post)),
        skipped=tuple(sorted(skipped)),
        fetched_at=datetime.now(UTC).isoformat(),
    )
    _write_index(cache_dir, slug, summary)
    return summary
