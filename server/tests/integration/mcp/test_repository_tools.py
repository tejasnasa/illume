"""The repository tools over the real transport: listing, isolation, errors, limits and logs.

The tools themselves are the agent's registry tools, tested on their own in
``test_agent_tools.py``; these tests cover what the MCP layer adds around them.
Data is created before ``mcp_client`` is requested, because a client's token
checks share the test's one connection.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from typing import Any

import httpx
import pytest
import respx

from app.mcp import limits
from app.mcp.limits import (
    MCP_CALLS_PER_MINUTE,
    MCP_FREE_CALLS_PER_DAY,
    MCP_MODEL_CALLS_PER_MINUTE,
    window_key,
)
from app.mcp.tools import REPO_DESCRIPTION, exposed_tools
from app.services.agent.tools import REGISTRY
from app.services.agent.tools.output import MAX_RESULT_CHARS
from app.services.mcp_tokens import create_token
from tests.factories import make_repo, make_user
from tests.fixtures.agent_tools import MARKER, SECURITY, seed_tool_repos
from tests.fixtures.retrieval import fake_embedder

pytestmark = pytest.mark.integration

EXPOSED = [tool.name for tool in exposed_tools()]
NON_REGISTRY_TOOLS = {"whoami", "list_repositories", "ask_illume"}

EXAMPLES: dict[str, dict[str, Any]] = {
    "search_code": {"query": "Where is `verify_password` defined?", "k": 5},
    "search_symbols": {"name": "verify_password"},
    "grep_code": {"pattern": "def verify_password"},
    "list_files": {"path_prefix": "app/auth/"},
    "list_symbols": {"path": SECURITY},
    "read_symbol": {"name": "verify_password"},
    "read_file": {"path": SECURITY},
    "get_importers": {"path": SECURITY},
    "get_importees": {"path": "app/users/service.py"},
    "find_path": {"source": "app/users/routes.py", "target": SECURITY},
    "get_cochanged": {"path": "app/jobs/retry.py"},
    "search_history": {"query": "why was password hashing switched to bcrypt"},
    "get_file_info": {"path": SECURITY},
    "get_glossary": {"term": "password"},
    "get_overview": {},
}

# Arguments written to match what only repository B holds.
MARKER_EXAMPLES: dict[str, dict[str, Any]] = {
    "search_code": {"query": MARKER, "k": 30},
    "search_symbols": {"name": MARKER},
    "grep_code": {"pattern": MARKER},
    "search_history": {"query": MARKER},
    "get_glossary": {"term": MARKER},
    "read_symbol": {"name": "verify_password", "path": SECURITY},
}

SECURITY_SOURCE = "def verify_password(plain, hashed):\n    return bcrypt.checkpw(plain, hashed)\n"
CONTENTS = r"https://api\.github\.com/repos/.+/contents/.+"
GITHUB_TOKEN = "gh-user-token"
# Ten seconds into a minute, so the window has 50 seconds left.
NOW = 1_700_000_050.0


@dataclasses.dataclass
class Net:
    """The faked outside world: GitHub, and a tripwire on every model endpoint."""

    router: respx.MockRouter
    github: respx.Route
    models: respx.Route


@pytest.fixture(autouse=True)
def net():
    """Answers GitHub file requests, and fails the test if any model endpoint is called."""
    with respx.mock(assert_all_called=False) as router:
        models = router.route(url__regex=r".*/(responses|chat/completions|rerank)(\?.*)?$").respond(
            500
        )
        github = router.get(url__regex=CONTENTS).respond(200, content=SECURITY_SOURCE.encode())
        yield Net(router, github, models)
        assert models.call_count == 0, "an MCP tool call reached a model endpoint"


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    """Query embedding without a network call."""
    monkeypatch.setattr("app.mcp.context.embed_texts", fake_embedder())


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Rate-limit windows that do not end in the middle of a test."""
    monkeypatch.setattr(limits, "_now", lambda: NOW)


@pytest.fixture
async def github_user(db_session, mcp_user):
    mcp_user.github_access_token = GITHUB_TOKEN
    await db_session.flush()
    return mcp_user


@pytest.fixture
async def repos(db_session, github_user):
    return await seed_tool_repos(db_session, github_user)


@pytest.fixture
def ref(repos) -> str:
    return str(repos.a.repo.repo_number)


async def call(client, tool: str, **arguments: Any):
    return await client.call_tool(tool, arguments)


def text_of(result) -> str:
    return "\n".join(block.text for block in result.content)


def everything(result) -> str:
    return text_of(result) + json.dumps(result.structured_content)


# --- tools/list ---------------------------------------------------------------------


async def test_every_exposed_registry_tool_is_listed_and_finish_is_not(mcp_client):
    listed = {tool.name: tool for tool in (await mcp_client.list_tools()).tools}

    assert set(listed) == NON_REGISTRY_TOOLS | set(EXPOSED)
    assert set(EXPOSED) == set(REGISTRY.names()) - {"finish"}
    assert "finish" not in listed


@pytest.mark.parametrize("name", EXPOSED)
async def test_a_listed_repository_tool_requires_repo_and_is_read_only(name, mcp_client, mcp_app):
    listed = {tool.name: tool for tool in (await mcp_client.list_tools()).tools}
    tool = listed[name]

    assert tool.input_schema["required"][0] == "repo"
    assert tool.input_schema["properties"]["repo"]["description"] == REPO_DESCRIPTION
    assert tool.input_schema["additionalProperties"] is False
    assert mcp_app.server.get_tool_input_schema(name) == tool.input_schema
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is (name == "read_file")
    assert tool.annotations.title
    description = tool.description.lower()
    assert "finish" not in description
    assert "the run" not in description


# --- isolation ------------------------------------------------------------------------


@pytest.mark.parametrize("name", EXPOSED)
async def test_a_tool_called_on_one_repository_never_returns_the_others_marker(
    name, repos, ref, mcp_client
):
    for arguments in (EXAMPLES[name], MARKER_EXAMPLES.get(name, EXAMPLES[name])):
        result = await call(mcp_client, name, repo=ref, **arguments)

        assert result.is_error is not True, text_of(result)
        assert MARKER not in everything(result)


@pytest.mark.parametrize("name", EXPOSED)
async def test_a_tool_called_on_the_marked_repository_does_show_the_marker_it_holds(
    name, repos, mcp_client
):
    """Without this, the isolation test could pass on a fixture with nothing to leak."""
    if name not in {"search_code", "grep_code", "read_symbol", "search_history", "get_file_info"}:
        pytest.skip("this tool's output carries no free text from the repository")
    arguments = {**EXAMPLES[name], **MARKER_EXAMPLES.get(name, {})}
    if name == "read_symbol":
        arguments = EXAMPLES[name]

    result = await call(mcp_client, name, repo=str(repos.b.repo.repo_number), **arguments)

    assert MARKER in everything(result), text_of(result)


@pytest.fixture
async def other_users_repo(db_session, repos):
    other = await make_user(db_session)
    return await make_repo(
        db_session, other, name="theirs", github_url="https://github.com/other/theirs"
    )


@pytest.mark.parametrize("name", EXPOSED)
async def test_another_users_repository_is_not_found_by_any_tool(
    name, other_users_repo, mcp_client
):
    refs = [
        str(other_users_repo.repo_number),
        str(other_users_repo.id),
        "other/theirs",
    ]
    for ref in refs:
        result = await call(mcp_client, name, repo=ref, **EXAMPLES[name])

        assert result.is_error is True
        assert "No repository matches" in text_of(result)


# --- happy paths ----------------------------------------------------------------------


async def test_search_symbols_finds_a_function(ref, mcp_client):
    result = await call(mcp_client, "search_symbols", repo=ref, name="verify_password")

    assert result.is_error is not True
    top = result.structured_content["items"][0]
    assert (top["path"], top["start_line"]) == (SECURITY, 4)
    assert 'type="code"' in text_of(result)


async def test_get_importers_looks_through_the_barrel(ref, mcp_client):
    result = await call(mcp_client, "get_importers", repo=ref, path=SECURITY, limit=50)

    paths = {item["path"] for item in result.structured_content["items"]}
    assert {"app/users/service.py", "app/deps.py", "tests/test_auth.py"} <= paths
    assert "app/auth/__init__.py" not in paths


async def test_get_importees_lists_what_a_file_imports(ref, mcp_client):
    result = await call(mcp_client, "get_importees", repo=ref, path="app/users/service.py")

    assert {item["path"] for item in result.structured_content["items"]} == {
        "app/users/models.py",
        SECURITY,
        "app/utils/dates.py",
    }


async def test_find_path_connects_two_files(ref, mcp_client):
    result = await call(
        mcp_client, "find_path", repo=ref, source="app/users/routes.py", target=SECURITY
    )

    assert result.structured_content["path"] == [
        "app/users/routes.py",
        "app/users/service.py",
        SECURITY,
    ]


async def test_get_file_info_merges_ownership_and_reading_order(ref, mcp_client):
    result = await call(mcp_client, "get_file_info", repo=ref, path=SECURITY)

    data = result.structured_content
    assert (data["primary_owner"], data["bus_factor"]) == ("Grace Hopper", 2)
    assert data["reading_order_position"] == 1


async def test_get_overview_reports_the_brief(ref, mcp_client):
    result = await call(mcp_client, "get_overview", repo=ref)

    assert result.structured_content["narrative"] == "A small web API with auth, billing and jobs."
    assert result.structured_content["entry_points"] == ["app/main.py"]


async def test_a_repository_can_be_named_by_uuid_or_owner_and_name(repos, mcp_client):
    by_uuid = await call(mcp_client, "get_overview", repo=str(repos.a.repo.id))
    by_name = await call(mcp_client, "get_overview", repo="example/example-repo")

    assert by_uuid.is_error is not True
    # Both seeded repositories live at the same URL, so the name alone is ambiguous.
    assert by_name.is_error is True
    assert "matches 2 repositories" in text_of(by_name)


async def test_search_code_embeds_the_query_and_calls_no_model(ref, mcp_client, net):
    result = await call(mcp_client, "search_code", repo=ref, query="Where is `verify_password`?")

    assert result.is_error is not True
    assert result.structured_content["items"][0]["path"] == SECURITY
    assert net.models.call_count == 0


async def test_search_code_with_the_real_embedder_makes_one_embedding_request_only(
    ref, mcp_client, net, monkeypatch
):
    import app.mcp.context as context
    from app.services.retrieval.embedding import embed_texts

    monkeypatch.setattr(context, "embed_texts", embed_texts)
    vector = (await fake_embedder()(["probe"]))[0]
    embeddings = net.router.post(url__regex=r".*/embeddings$").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
                "data": [
                    {"object": "embedding", "index": index, "embedding": vector}
                    for index in range(len(json.loads(request.content)["input"]))
                ],
            },
        )
    )

    result = await call(mcp_client, "search_code", repo=ref, query="password hashing")

    assert result.is_error is not True
    assert embeddings.call_count == 1
    assert net.models.call_count == 0


# --- read_file ------------------------------------------------------------------------


async def test_read_file_reads_at_the_ingested_commit_with_the_users_github_token(
    repos, ref, mcp_client, net
):
    result = await call(mcp_client, "read_file", repo=ref, path=SECURITY)

    assert result.is_error is not True
    assert "bcrypt.checkpw" in text_of(result)
    (request,) = [c.request for c in net.github.calls]
    assert request.url.params["ref"] == repos.a.repo.ingested_commit_sha
    assert request.headers["Authorization"] == f"Bearer {GITHUB_TOKEN}"


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "src/../../x"])
async def test_read_file_refuses_an_unsafe_path_without_calling_github(path, ref, mcp_client, net):
    result = await call(mcp_client, "read_file", repo=ref, path=path)

    assert result.structured_content["status"] == "refused_path"
    assert net.github.call_count == 0


async def test_read_file_says_when_the_path_is_not_in_the_repository(ref, mcp_client, net):
    result = await call(mcp_client, "read_file", repo=ref, path="src/ghost.py")

    assert result.structured_content["status"] == "not_in_repository"
    assert net.github.call_count == 0


# --- errors ---------------------------------------------------------------------------


async def test_an_extra_argument_is_an_error_the_model_can_read(ref, mcp_client):
    result = await call(mcp_client, "list_symbols", repo=ref, path=SECURITY, bogus=1)

    assert result.is_error is True
    assert text_of(result).startswith("[invalid_arguments] ")
    assert "`bogus` is not an argument" in text_of(result)


async def test_a_wrong_type_is_an_error(ref, mcp_client):
    result = await call(mcp_client, "list_symbols", repo=ref, path=5)

    assert result.is_error is True
    assert text_of(result).startswith("[invalid_arguments] ")


@pytest.mark.parametrize("repo", [None, True, 1.5, "", "   ", ["1"]])
async def test_a_missing_or_unusable_repo_is_an_error(repo, mcp_client):
    arguments = {"path": SECURITY} if repo is None else {"path": SECURITY, "repo": repo}

    result = await call(mcp_client, "list_symbols", **arguments)

    assert result.is_error is True
    assert "`repo` is required" in text_of(result)


async def test_a_repository_number_sent_as_a_json_number_is_accepted(repos, mcp_client):
    result = await call(mcp_client, "get_overview", repo=repos.a.repo.repo_number)

    assert result.is_error is not True
    assert "B_MARKER" not in text_of(result)


async def test_an_unknown_repository_is_an_error(repos, mcp_client):
    result = await call(mcp_client, "get_overview", repo="9999999")

    assert result.is_error is True
    assert "No repository matches" in text_of(result)
    assert "list_repositories" in text_of(result)


@pytest.fixture
async def parsing_repo(db_session, github_user):
    return await make_repo(
        db_session,
        github_user,
        name="busy",
        github_url="https://github.com/acme/busy",
        status="parsing",
    )


async def test_a_repository_still_ingesting_is_an_error(parsing_repo, mcp_client):
    result = await call(mcp_client, "get_overview", repo=str(parsing_repo.repo_number))

    assert result.is_error is True
    assert "still ingesting" in text_of(result)


async def test_a_tool_that_times_out_is_an_error_and_the_tool_is_restored(
    ref, mcp_client, monkeypatch
):
    original = REGISTRY.get("get_overview")

    async def slow(ctx, args):
        import asyncio

        await asyncio.sleep(5)

    monkeypatch.setitem(
        REGISTRY._tools, "get_overview", dataclasses.replace(original, timeout_s=0.05, handler=slow)
    )

    result = await call(mcp_client, "get_overview", repo=ref)

    assert result.is_error is True
    assert text_of(result).startswith("[timeout] ")
    monkeypatch.undo()
    assert REGISTRY.get("get_overview") is original


async def test_an_oversized_result_is_truncated_with_its_fences_closed(ref, mcp_client, net):
    net.github.respond(200, content=("x" * 99 + "\n").encode() * 400)

    result = await call(mcp_client, "read_file", repo=ref, path=SECURITY)

    text = text_of(result)
    assert result.is_error is not True
    assert result.structured_content["path"] == SECURITY
    assert "[output truncated" in text
    assert len(text) <= MAX_RESULT_CHARS
    assert text.count("<source ") == text.count("</source>") >= 1


# --- rate limits ----------------------------------------------------------------------


async def test_the_call_after_sixty_in_a_minute_is_rate_limited(ref, mcp_client):
    for _ in range(MCP_CALLS_PER_MINUTE):
        assert (await call(mcp_client, "get_overview", repo=ref)).is_error is not True

    result = await call(mcp_client, "get_overview", repo=ref)

    assert result.is_error is True
    assert "Rate limited, retry in 50 s" in text_of(result)


async def test_calls_on_two_tokens_of_one_user_share_one_limit(
    db_session, mcp_user, ref, mcp_connect, auth_headers
):
    _, second = await create_token(db_session, mcp_user.id, "second", 30)

    async with (
        mcp_connect(**auth_headers) as first_client,
        mcp_connect(authorization=f"Bearer {second}") as second_client,
    ):
        for client in (first_client, second_client):
            for _ in range(MCP_CALLS_PER_MINUTE // 2):
                assert (await call(client, "get_overview", repo=ref)).is_error is not True

        for client in (first_client, second_client):
            assert (await call(client, "get_overview", repo=ref)).is_error is True


async def test_the_account_tools_count_toward_the_per_minute_limit_only(
    mcp_user, ref, mcp_client, mcp_redis
):
    for _ in range(MCP_CALLS_PER_MINUTE):
        assert (await call(mcp_client, "whoami")).is_error is not True

    assert (await call(mcp_client, "list_repositories")).is_error is True
    assert (await call(mcp_client, "get_overview", repo=ref)).is_error is True

    keys = await mcp_redis.client().keys("*")
    assert keys == [window_key("calls", mcp_user.id, 60, NOW)]


async def test_a_model_or_network_tool_is_limited_to_twenty_a_minute(ref, mcp_client):
    for _ in range(MCP_MODEL_CALLS_PER_MINUTE):
        assert (await call(mcp_client, "read_file", repo=ref, path="../x")).is_error is not True

    over = await call(mcp_client, "read_file", repo=ref, path="../x")
    free = await call(mcp_client, "search_symbols", repo=ref, name="verify_password")

    assert over.is_error is True
    assert "Rate limited" in text_of(over)
    assert free.is_error is not True


async def test_a_user_without_an_ai_key_has_a_daily_cap(ref, mcp_user, mcp_client, mcp_redis):
    key = window_key("daily", mcp_user.id, 86_400, NOW)
    await mcp_redis.client().set(key, MCP_FREE_CALLS_PER_DAY - 1)

    last = await call(mcp_client, "get_overview", repo=ref)
    over = await call(mcp_client, "get_overview", repo=ref)

    assert last.is_error is not True
    assert over.is_error is True
    assert "per day" in text_of(over)


async def test_a_user_with_their_own_ai_key_has_no_daily_cap(db_session, mcp_connect, mcp_redis):
    owner = await make_user(db_session, ai_api_key="sk-own")
    repo = await make_repo(db_session, owner)
    _, token = await create_token(db_session, owner.id, "own", 30)
    await mcp_redis.client().set(
        window_key("daily", owner.id, 86_400, NOW), MCP_FREE_CALLS_PER_DAY * 10
    )

    async with mcp_connect(authorization=f"Bearer {token}") as client:
        result = await call(client, "list_files", repo=str(repo.repo_number))

    assert result.is_error is not True


async def test_calls_still_work_when_redis_is_down(ref, mcp_client, mcp_redis, caplog):
    mcp_redis.down = True
    caplog.set_level(logging.WARNING, logger="app.mcp.limits")

    result = await call(mcp_client, "get_overview", repo=ref)

    assert result.is_error is not True
    assert "rate limiter unavailable" in caplog.text


# --- logs -----------------------------------------------------------------------------


async def test_each_call_logs_one_line_without_arguments_or_the_token(
    repos, ref, mcp_client, mcp_user, mcp_token, caplog
):
    caplog.set_level(logging.INFO, logger="app.mcp.tools")

    await call(mcp_client, "search_symbols", repo=ref, name="zzq_unique_probe")

    lines = [r.getMessage() for r in caplog.records if r.name == "app.mcp.tools"]
    assert len(lines) == 1
    assert re.fullmatch(
        rf"mcp_tool user={mcp_user.id} repo={repos.a.repo.id} tool=search_symbols "
        r"status=ok ms=\d+ truncated=False",
        lines[0],
    )
    assert "zzq_unique_probe" not in caplog.text
    assert mcp_token not in caplog.text


async def test_a_refused_call_is_logged_with_its_status(ref, mcp_client, caplog):
    caplog.set_level(logging.INFO, logger="app.mcp.tools")

    await call(mcp_client, "list_symbols", repo=ref, path=SECURITY, bogus=1)
    await call(mcp_client, "get_overview", repo="9999999")

    lines = [r.getMessage() for r in caplog.records if r.name == "app.mcp.tools"]
    assert "tool=list_symbols status=invalid_arguments" in lines[0]
    assert "tool=get_overview status=repo_error" in lines[1]
    assert " repo=- " in lines[1]
