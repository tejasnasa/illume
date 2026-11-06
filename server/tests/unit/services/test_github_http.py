"""Rate-limit reading shared by the pull request fetcher and the file reader."""

import httpx
import pytest

from app.services.github_http import is_rate_limited, parse_github_url, retry_after_seconds

pytestmark = pytest.mark.unit


def response(status: int, **headers: str) -> httpx.Response:
    return httpx.Response(status, headers=headers)


def test_the_wait_comes_from_retry_after_then_the_reset_time_then_a_default():
    assert retry_after_seconds(response(429, **{"Retry-After": "12"})) == 12
    assert retry_after_seconds(response(403, **{"X-RateLimit-Reset": "1"})) == 1
    assert retry_after_seconds(response(403, **{"Retry-After": "soon"})) == 60


def test_a_403_is_a_rate_limit_only_when_github_says_so():
    assert is_rate_limited(response(429))
    assert is_rate_limited(response(403, **{"X-RateLimit-Remaining": "0"}))
    assert not is_rate_limited(response(403))


def test_owner_and_name_are_read_from_a_url():
    assert parse_github_url("https://github.com/acme/widgets.git/") == ("acme", "widgets")
    with pytest.raises(ValueError):
        parse_github_url("https://github.com/acme")
