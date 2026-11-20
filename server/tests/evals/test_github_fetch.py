"""The GitHub cache: pagination, ancestry classification, back-off and cache hits."""

import time
from pathlib import Path

import httpx
import pytest
import respx

from evals.mining.clones import ensure_clone
from evals.mining.github_cache import load_prs, repo_dir
from evals.mining.github_fetch import (
    MAX_ATTEMPTS,
    GitHubError,
    build_cache,
    load_index,
    make_client,
)

OWNER, REPO = "fixture", "sample"
SLUG = f"{OWNER}/{REPO}"
API = "https://api.github.com"
PULLS = f"{API}/repos/{OWNER}/{REPO}/pulls"
TOKEN = "ghp_SECRETTOKENVALUE0123456789"


def _payload(number, sha, merged_at="2026-03-01T12:00:00Z", *, bot=False, labels=()):
    return {
        "number": number,
        "title": f"PR {number}",
        "body": f"Body of {number}",
        "merged_at": merged_at,
        "merge_commit_sha": sha,
        "user": {"login": "dependabot[bot]" if bot else "ada", "type": "Bot" if bot else "User"},
        "labels": [{"name": name} for name in labels],
    }


def _link(url: str) -> dict:
    return {"Link": f'<{url}>; rel="next"'}


@pytest.fixture
def clone(tmp_path, history):
    return ensure_clone(str(history.root), tmp_path / "clones", slug=SLUG)


@pytest.fixture
def cache_dir(tmp_path) -> Path:
    return tmp_path / "github"


@pytest.fixture
def api():
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def client():
    with make_client(TOKEN) as http:
        yield http


@pytest.fixture
def no_sleep():
    waits: list[float] = []
    return waits, waits.append


def _build(client, clone, cache_dir, history, sleep, **kwargs):
    return build_cache(
        client,
        owner=OWNER,
        repo=REPO,
        cache_dir=cache_dir,
        clone=clone,
        base_commit=history.base,
        sleep=sleep,
        **kwargs,
    )


def _serve_pulls(api, pages: list[list[dict]]):
    """Serve ``pages`` from the pulls listing, linking each page to the next."""

    def respond(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        headers = _link(f"{PULLS}?state=closed&page={page + 1}") if page < len(pages) else {}
        return httpx.Response(200, json=pages[page - 1], headers=headers)

    return api.get(PULLS).mock(side_effect=respond)


def _serve_files(api, number: int, pages: list[list[dict]]):
    url = f"{PULLS}/{number}/files"

    def respond(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        headers = _link(f"{url}?page={page + 1}") if page < len(pages) else {}
        return httpx.Response(200, json=pages[page - 1], headers=headers)

    return api.get(url).mock(side_effect=respond)


def _file(name, status="modified", previous=None):
    return {
        "filename": name,
        "status": status,
        "previous_filename": previous,
        "additions": 3,
        "deletions": 1,
    }


@pytest.mark.integration
class TestClassificationAndPagination:
    def test_pull_requests_are_classified_by_ancestry_across_pages(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        prs = history.prs
        listing = _serve_pulls(
            api,
            [
                [
                    _payload(102, prs[102], "2026-05-01T12:00:00Z"),
                    {**_payload(150, "0" * 40), "merged_at": None},
                    _payload(101, prs[101], "2026-02-15T12:00:00Z", labels=("feature", "docs")),
                ],
                [
                    _payload(103, prs[103], "2026-01-15T12:00:00Z"),
                    _payload(90, history.second, "2026-02-01T12:00:00Z", bot=True),
                    _payload(80, "e" * 40, "2026-01-05T12:00:00Z"),
                ],
            ],
        )
        files = _serve_files(
            api,
            102,
            [
                [_file("docs/feature_b.md", "added")],
                [_file("src/util.py", "renamed", "src/old.py")],
            ],
        )

        summary = _build(client, clone, cache_dir, history, no_sleep[1])

        assert listing.call_count == 2
        assert files.call_count == 2
        assert summary.pre_base == (90, 101)
        assert summary.post_base == (102,)
        assert summary.skipped == (80, 103)
        assert not summary.from_cache

        by_number = {pr.number: pr for pr in load_prs(cache_dir, SLUG)}
        assert set(by_number) == {90, 101, 102}
        assert by_number[101].files is None
        assert by_number[101].labels == ("feature", "docs")
        assert by_number[101].author == "ada" and by_number[101].user_type == "User"
        assert by_number[90].user_type == "Bot" and by_number[90].author == "dependabot[bot]"
        post_files = by_number[102].files
        assert post_files is not None
        assert [(f.path, f.status, f.previous_path) for f in post_files] == [
            ("docs/feature_b.md", "added", None),
            ("src/util.py", "renamed", "src/old.py"),
        ]

    def test_the_early_dated_merge_is_not_classified_by_its_timestamp(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        _serve_pulls(api, [[_payload(103, history.prs[103], "2026-01-15T12:00:00Z")]])
        summary = _build(client, clone, cache_dir, history, no_sleep[1])
        assert summary.pre_base == () and summary.post_base == ()
        assert summary.skipped == (103,)
        assert load_prs(cache_dir, SLUG) == []

    def test_paging_stops_once_enough_history_is_found(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        listing = _serve_pulls(
            api,
            [
                [
                    _payload(101, history.prs[101], "2026-02-15T12:00:00Z"),
                    _payload(90, history.second, "2026-02-01T12:00:00Z"),
                ],
                [_payload(80, history.first, "2026-01-01T12:00:00Z")],
            ],
        )
        summary = _build(client, clone, cache_dir, history, no_sleep[1], history_prs=1)
        assert listing.call_count == 1
        assert summary.pre_base == (101,)
        assert [pr.number for pr in load_prs(cache_dir, SLUG)] == [101]

    def test_max_pages_bounds_the_listing(self, api, client, clone, cache_dir, history, no_sleep):
        listing = _serve_pulls(
            api,
            [[_payload(n, "e" * 40, "2026-05-01T12:00:00Z")] for n in (1, 2, 3)],
        )
        _build(client, clone, cache_dir, history, no_sleep[1], max_pages=2)
        assert listing.call_count == 2

    def test_an_empty_listing_writes_an_empty_index(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        _serve_pulls(api, [[]])
        summary = _build(client, clone, cache_dir, history, no_sleep[1])
        assert summary.pre_base == summary.post_base == summary.skipped == ()
        assert load_index(cache_dir, SLUG) is not None


@pytest.mark.integration
class TestBackOff:
    def test_a_rate_limit_with_retry_after_sleeps_once_for_that_long(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        waits, sleep = no_sleep
        listing = api.get(PULLS).mock(
            side_effect=[
                httpx.Response(403, headers={"Retry-After": "7", "X-RateLimit-Remaining": "0"}),
                httpx.Response(200, json=[]),
            ]
        )
        _build(client, clone, cache_dir, history, sleep)
        assert waits == [7]
        assert listing.call_count == 2

    def test_an_exhausted_limit_waits_until_the_reset_time(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        waits, sleep = no_sleep
        reset = int(time.time()) + 30
        api.get(PULLS).mock(
            side_effect=[
                httpx.Response(
                    403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}
                ),
                httpx.Response(200, json=[]),
            ]
        )
        _build(client, clone, cache_dir, history, sleep)
        assert len(waits) == 1
        assert 27 <= waits[0] <= 31

    def test_a_429_is_treated_as_a_rate_limit(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        waits, sleep = no_sleep
        api.get(PULLS).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}),
                httpx.Response(200, json=[]),
            ]
        )
        _build(client, clone, cache_dir, history, sleep)
        assert waits == [2]

    def test_a_server_error_is_retried_with_exponential_back_off(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        waits, sleep = no_sleep
        listing = api.get(PULLS).mock(
            side_effect=[
                httpx.Response(502),
                httpx.Response(503),
                httpx.Response(200, json=[]),
            ]
        )
        _build(client, clone, cache_dir, history, sleep)
        assert listing.call_count == 3
        assert waits == [1.0, 2.0]

    def test_a_dropped_connection_is_retried(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        waits, sleep = no_sleep
        api.get(PULLS).mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=[])])
        _build(client, clone, cache_dir, history, sleep)
        assert waits == [1.0]

    def test_a_plain_403_is_not_retried(self, api, client, clone, cache_dir, history, no_sleep):
        waits, sleep = no_sleep
        listing = api.get(PULLS).mock(return_value=httpx.Response(403, json={"message": "no"}))
        with pytest.raises(GitHubError, match="403"):
            _build(client, clone, cache_dir, history, sleep)
        assert listing.call_count == 1
        assert waits == []

    def test_a_404_raises(self, api, client, clone, cache_dir, history, no_sleep):
        api.get(PULLS).mock(return_value=httpx.Response(404))
        with pytest.raises(GitHubError, match="404"):
            _build(client, clone, cache_dir, history, no_sleep[1])

    def test_retries_are_bounded(self, api, client, clone, cache_dir, history, no_sleep):
        waits, sleep = no_sleep
        listing = api.get(PULLS).mock(return_value=httpx.Response(500))
        with pytest.raises(GitHubError, match="gave up"):
            _build(client, clone, cache_dir, history, sleep)
        assert listing.call_count == MAX_ATTEMPTS
        assert len(waits) == MAX_ATTEMPTS

    def test_a_rate_limit_while_fetching_files_is_retried_too(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        waits, sleep = no_sleep
        _serve_pulls(api, [[_payload(102, history.prs[102], "2026-05-01T12:00:00Z")]])
        files = api.get(f"{PULLS}/102/files").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "4"}),
                httpx.Response(200, json=[_file("docs/feature_b.md", "added")]),
            ]
        )
        _build(client, clone, cache_dir, history, sleep)
        assert waits == [4]
        assert files.call_count == 2


@pytest.mark.integration
class TestCacheHits:
    @pytest.fixture
    def populated(self, api, client, clone, cache_dir, history, no_sleep):
        listing = _serve_pulls(
            api,
            [
                [
                    _payload(102, history.prs[102], "2026-05-01T12:00:00Z"),
                    _payload(101, history.prs[101], "2026-02-15T12:00:00Z"),
                ]
            ],
        )
        files = _serve_files(api, 102, [[_file("docs/feature_b.md", "added")]])
        _serve_files(api, 101, [[_file("docs/feature_a.md", "added")]])
        summary = _build(client, clone, cache_dir, history, no_sleep[1])
        return listing, files, summary

    def test_a_current_cache_makes_no_request(
        self, api, client, clone, cache_dir, history, no_sleep, populated
    ):
        _, _, first = populated
        before = api.calls.call_count
        again = _build(client, clone, cache_dir, history, no_sleep[1])
        assert api.calls.call_count == before
        assert again.from_cache
        assert (again.pre_base, again.post_base, again.skipped) == (
            first.pre_base,
            first.post_base,
            first.skipped,
        )

    def test_refresh_fetches_again(
        self, api, client, clone, cache_dir, history, no_sleep, populated
    ):
        listing, files, _ = populated
        _build(client, clone, cache_dir, history, no_sleep[1], refresh=True)
        assert listing.call_count == 2
        assert files.call_count == 2

    def test_a_pull_request_already_on_disk_is_not_refetched(
        self, api, client, clone, cache_dir, history, no_sleep, populated
    ):
        listing, files, _ = populated
        (repo_dir(cache_dir, SLUG) / "index.json").unlink()
        summary = _build(client, clone, cache_dir, history, no_sleep[1])
        assert listing.call_count == 2
        assert files.call_count == 1
        assert not summary.from_cache
        post = next(pr for pr in load_prs(cache_dir, SLUG) if pr.number == 102)
        assert post.files is not None and len(post.files) == 1

    def test_a_different_base_commit_is_not_a_cache_hit(
        self, api, client, clone, cache_dir, history, no_sleep, populated
    ):
        listing, _, _ = populated
        build_cache(
            client,
            owner=OWNER,
            repo=REPO,
            cache_dir=cache_dir,
            clone=clone,
            base_commit=history.first,
            sleep=no_sleep[1],
        )
        assert listing.call_count == 2

    def test_an_unreadable_index_is_ignored(
        self, api, client, clone, cache_dir, history, no_sleep, populated
    ):
        (repo_dir(cache_dir, SLUG) / "index.json").write_text("{not json", encoding="utf-8")
        assert load_index(cache_dir, SLUG) is None
        summary = _build(client, clone, cache_dir, history, no_sleep[1])
        assert not summary.from_cache


@pytest.mark.integration
class TestToken:
    def test_the_token_is_sent_as_a_bearer_header_and_never_stored(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        listing = _serve_pulls(
            api,
            [
                [
                    _payload(102, history.prs[102], "2026-05-01T12:00:00Z"),
                    _payload(101, history.prs[101], "2026-02-15T12:00:00Z"),
                ]
            ],
        )
        _serve_files(api, 102, [[_file("docs/feature_b.md", "added")]])
        _build(client, clone, cache_dir, history, no_sleep[1])

        request = listing.calls[0].request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"

        stored = [path for path in cache_dir.rglob("*") if path.is_file()]
        assert stored
        for path in stored:
            assert TOKEN not in path.read_text(encoding="utf-8")
            assert "SECRETTOKEN" not in str(path)

    def test_an_error_message_does_not_contain_the_token(
        self, api, client, clone, cache_dir, history, no_sleep
    ):
        api.get(PULLS).mock(return_value=httpx.Response(401))
        with pytest.raises(GitHubError) as excinfo:
            _build(client, clone, cache_dir, history, no_sleep[1])
        assert TOKEN not in str(excinfo.value)
