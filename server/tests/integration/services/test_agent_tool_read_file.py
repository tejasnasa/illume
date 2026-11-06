"""``read_file``: what it refuses before any network call, and how it reads when it does call.

GitHub is faked with respx. A refused path must make zero requests, so each
refusal asserts on the router's call count.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import respx

from app.services.agent.tools import REGISTRY
from app.services.github_files import MAX_FILE_BYTES
from tests.factories import make_file, make_repo, make_user
from tests.fixtures.agent_tools import make_tool_context, session_factory_for

pytestmark = pytest.mark.integration

PATH = "src/app.py"
CONTENTS = r"https://api\.github\.com/repos/example/example-repo/contents/.+"
SHA = "0" * 40


@pytest.fixture
def github():
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
async def repo(db_session):
    repo = await make_repo(db_session, await make_user(db_session))
    await make_file(db_session, repo, path=PATH)
    return repo


@pytest.fixture
def ctx(db_session, repo):
    return make_tool_context(session_factory_for(db_session.bind), repo, github_token="gh-token")


async def read(ctx, **arguments):
    return await REGISTRY.call("read_file", arguments, ctx)


def lines(count: int) -> bytes:
    return "".join(f"line {n}\n" for n in range(1, count + 1)).encode()


# --- refused before any request ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "src/../../etc/passwd",
        "/etc/passwd",
        "%2e%2e%2fetc/passwd",
        "src%5c..%5cpasswd",
        "src\\app.py",
        "src/app.py\x00.txt",
        "C:/Windows/win.ini",
        "src//app.py",
    ],
)
async def test_an_unsafe_path_is_refused_without_any_request(ctx, github, path):
    route = github.get(url__regex=CONTENTS).respond(200, content=b"secret")

    result = await read(ctx, path=path)

    assert result.data["status"] == "refused_path"
    assert not route.called
    assert github.calls.call_count == 0


async def test_a_path_that_ingestion_did_not_record_is_refused_without_any_request(ctx, github):
    route = github.get(url__regex=CONTENTS).respond(200, content=b"secret")

    result = await read(ctx, path="src/not_ingested.py")

    assert result.data["status"] == "not_in_repository"
    assert "list_files" in result.text
    assert not route.called


# --- reading --------------------------------------------------------------------


async def test_a_file_is_fetched_at_the_ingested_commit(ctx, github):
    route = github.get(url__regex=CONTENTS).respond(200, content=lines(3))

    result = await read(ctx, path=PATH)

    assert result.status == "ok"
    assert "2  line 2" in result.text
    (request,) = [call.request for call in route.calls]
    assert request.url.params["ref"] == SHA
    assert request.headers["Accept"] == "application/vnd.github.raw+json"
    assert request.headers["Authorization"] == "Bearer gh-token"


async def test_nothing_is_cached_so_every_read_is_a_request(ctx, github):
    route = github.get(url__regex=CONTENTS).respond(200, content=lines(3))

    await read(ctx, path=PATH)
    again = await read(ctx, path=PATH)

    assert "line 3" in again.text
    assert route.call_count == 2


async def test_a_file_without_a_token_is_read_unauthenticated(ctx, github):
    route = github.get(url__regex=CONTENTS).respond(200, content=lines(1))
    ctx = replace(ctx, github_token=None)

    await read(ctx, path=PATH)

    assert "Authorization" not in route.calls.last.request.headers


async def test_a_missing_file_is_not_at_this_commit(ctx, github):
    github.get(url__regex=CONTENTS).respond(404, json={"message": "Not Found"})

    result = await read(ctx, path=PATH)

    assert result.data["status"] == "not_found"
    assert f"not at commit {SHA[:8]}" in result.text


async def test_a_rate_limit_is_a_typed_result_and_a_plain_403_is_not(ctx, github):
    route = github.get(url__regex=CONTENTS)
    route.respond(403, headers={"Retry-After": "7"})

    limited = await read(ctx, path=PATH)

    assert limited.data["status"] == "rate_limited"
    assert limited.data["retry_after"] == 7

    route.respond(403)
    unauthenticated = await read(replace(ctx, github_token=None), path=PATH)
    assert unauthenticated.data["status"] == "denied"
    assert "unauthenticated" in unauthenticated.text


async def test_a_file_over_two_megabytes_is_refused(ctx, github):
    github.get(url__regex=CONTENTS).respond(200, content=b"x" * (MAX_FILE_BYTES + 1))

    result = await read(ctx, path=PATH)

    assert result.data["status"] == "too_large"


async def test_a_binary_file_is_refused(ctx, github):
    github.get(url__regex=CONTENTS).respond(200, content=b"\x89PNG\r\n\x00\x00data")

    result = await read(ctx, path=PATH)

    assert result.data["status"] == "binary"


async def test_a_long_file_is_returned_in_windows_with_a_continuation_note(ctx, github):
    github.get(url__regex=CONTENTS).respond(200, content=lines(1000))

    first = await read(ctx, path=PATH)
    assert "lines 1 to 400 of 1,000; call again with start_line=401" in first.text
    assert "400  line 400" in first.text
    assert "line 401" not in first.text

    last = await read(ctx, path=PATH, start_line=901)
    assert "lines 901 to 1,000 of 1,000." in last.text
    assert "call again" not in last.text

    ranged = await read(ctx, path=PATH, start_line=10, end_line=12)
    assert ranged.data["end_line"] == 12

    past = await read(ctx, path=PATH, start_line=2000)
    assert past.data["status"] == "out_of_range"
