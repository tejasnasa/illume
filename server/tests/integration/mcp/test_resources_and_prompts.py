"""Resources and prompts: templates, reads, ownership, limits and argument checks."""

from __future__ import annotations

import pytest
from mcp import MCPError

from app.mcp import limits
from app.mcp.limits import MCP_CALLS_PER_MINUTE, window_key
from app.mcp.prompts import PROMPTS
from app.mcp.resources import OVERVIEW_TEMPLATE, READING_ORDER_TEMPLATE
from app.services.onboarding_guide import get_reading_order
from tests.factories import make_guide, make_repo, make_user
from tests.fixtures.agent_tools import MARKER, SECURITY, seed_tool_repos

pytestmark = pytest.mark.integration

NOW = 1_700_000_050.0
NOT_FOUND = "No repository matches"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(limits, "_now", lambda: NOW)


@pytest.fixture
async def repos(db_session, mcp_user):
    return await seed_tool_repos(db_session, mcp_user)


@pytest.fixture
def ref(repos) -> str:
    return str(repos.a.repo.repo_number)


def overview_uri(ref: str) -> str:
    return f"illume://repo/{ref}/overview"


def order_uri(ref: str) -> str:
    return f"illume://repo/{ref}/reading-order"


async def read_text(client, uri: str) -> str:
    result = await client.read_resource(uri)
    assert len(result.contents) == 1
    content = result.contents[0]
    assert content.mime_type == "text/markdown"
    assert content.uri == uri
    return content.text


# --- templates -------------------------------------------------------------------------


async def test_the_two_templates_are_listed_as_markdown(mcp_client):
    result = await mcp_client.list_resource_templates()

    by_name = {t.name: t for t in result.resource_templates}
    assert set(by_name) == {"overview", "reading-order"}
    assert by_name["overview"].uri_template == OVERVIEW_TEMPLATE
    assert by_name["reading-order"].uri_template == READING_ORDER_TEMPLATE
    for template in by_name.values():
        assert template.mime_type == "text/markdown"
        assert template.title
        assert template.description


async def test_the_concrete_resource_list_is_empty(mcp_client):
    assert (await mcp_client.list_resources()).resources == []


# --- reads -----------------------------------------------------------------------------


@pytest.mark.parametrize("by", ["number", "uuid"])
async def test_the_overview_holds_the_brief_stack_entry_points_and_critical_files(
    by, repos, mcp_client
):
    ref = str(repos.a.repo.repo_number if by == "number" else repos.a.repo.id)

    text = await read_text(mcp_client, overview_uri(ref))

    assert text.startswith("# Overview of ")
    assert "A small web API with auth, billing and jobs." in text
    assert "language: python" in text
    assert "app/main.py" in text
    assert f"{SECURITY}: critical, fan-in 5 (imported by many files)" in text
    assert MARKER not in text
    # Repository text is fenced, and Illume's headings are not.
    assert text.count("<source ") == text.count("</source>") >= 3
    assert "## Architecture\n\n<source" in text


@pytest.mark.parametrize("by", ["number", "uuid"])
async def test_the_reading_order_lists_position_path_and_note(by, repos, mcp_client):
    ref = str(repos.a.repo.repo_number if by == "number" else repos.a.repo.id)

    text = await read_text(mcp_client, order_uri(ref))

    assert text.startswith("# Reading order of ")
    assert f"1. {SECURITY}: Start here: password hashing." in text
    assert "<source " in text
    assert MARKER not in text


async def test_the_other_repository_shows_its_own_marker(repos, mcp_client):
    text = await read_text(mcp_client, overview_uri(str(repos.b.repo.repo_number)))

    assert MARKER in text


async def test_a_repository_can_be_named_by_owner_and_name_even_percent_encoded(
    db_session, mcp_user, mcp_client
):
    repo = await make_repo(
        db_session,
        mcp_user,
        name="busy",
        github_url="https://github.com/acme/busy",
        status="ready",
    )
    await make_guide(
        db_session,
        repo,
        reading_order=[{"position": 1, "path": "a.py", "annotation": "Read me.", "fan_in": 0}],
    )

    for ref in ("acme/busy", "acme%2Fbusy"):
        assert "1. a.py: Read me." in await read_text(mcp_client, order_uri(ref))


async def test_an_empty_reading_order_says_so(db_session, mcp_user, mcp_client):
    repo = await make_repo(db_session, mcp_user, status="ready")
    await make_guide(db_session, repo, reading_order=[])

    text = await read_text(mcp_client, order_uri(str(repo.repo_number)))

    assert "No reading order has been generated" in text


async def test_a_repository_without_a_guide_has_no_reading_order(db_session, mcp_user, mcp_client):
    repo = await make_repo(db_session, mcp_user, status="ready")

    with pytest.raises(MCPError, match="no reading order yet"):
        await mcp_client.read_resource(order_uri(str(repo.repo_number)))

    text = await read_text(mcp_client, overview_uri(str(repo.repo_number)))
    assert "No architecture brief has been generated" in text


# --- errors ----------------------------------------------------------------------------


@pytest.fixture
async def other_users_repo(db_session, repos):
    other = await make_user(db_session)
    return await make_repo(
        db_session,
        other,
        name="theirs",
        github_url="https://github.com/other/theirs",
        status="ready",
    )


@pytest.mark.parametrize("make_uri", [overview_uri, order_uri])
async def test_another_users_repository_reads_like_a_missing_one(
    make_uri, other_users_repo, mcp_client
):
    for ref in (str(other_users_repo.repo_number), str(other_users_repo.id), "other/theirs"):
        with pytest.raises(MCPError) as caught:
            await mcp_client.read_resource(make_uri(ref))
        assert NOT_FOUND in caught.value.message
        assert caught.value.code == -32602

    with pytest.raises(MCPError, match=NOT_FOUND):
        await mcp_client.read_resource(make_uri("9999999"))


@pytest.mark.parametrize("make_uri", [overview_uri, order_uri])
async def test_a_repository_that_is_not_ready_cannot_be_read(
    make_uri, db_session, mcp_user, mcp_client
):
    repo = await make_repo(db_session, mcp_user, status="parsing")

    with pytest.raises(MCPError, match="still ingesting"):
        await mcp_client.read_resource(make_uri(str(repo.repo_number)))


@pytest.mark.parametrize(
    "uri",
    [
        "illume://repo/1/glossary",
        "illume://repo//overview",
        "illume://repo/1",
        "illume://repo/1/overview/extra?x=1",
        "illume://other/1/overview",
        "https://example.com/1/overview",
        "file:///etc/passwd",
        "not a uri",
    ],
)
async def test_a_malformed_or_unknown_uri_is_an_error(uri, ref, mcp_client):
    with pytest.raises(MCPError) as caught:
        await mcp_client.read_resource(uri)

    assert caught.value.code == -32602
    assert "Unknown resource" in caught.value.message


# --- the reading-order service -----------------------------------------------------------


async def test_the_service_returns_entries_in_order_or_none(db_session, mcp_user):
    repo = await make_repo(db_session, mcp_user, status="ready")
    assert await get_reading_order(db_session, repo.id) is None

    await make_guide(
        db_session,
        repo,
        reading_order=[
            {"position": 2, "path": "b.py", "annotation": "B", "fan_in": 1},
            "junk",
            {"position": 1, "path": "a.py", "annotation": "A", "fan_in": 9},
        ],
    )

    entries = await get_reading_order(db_session, repo.id)
    assert [(e.position, e.file_path, e.annotation, e.fan_in) for e in entries] == [
        (1, "a.py", "A", 9),
        (2, "b.py", "B", 1),
    ]


# --- rate limit ------------------------------------------------------------------------


async def test_a_resource_read_counts_toward_the_per_minute_limit(
    ref, mcp_user, mcp_client, mcp_redis
):
    key = window_key("calls", mcp_user.id, 60, NOW)
    await mcp_redis.client().set(key, MCP_CALLS_PER_MINUTE - 1)

    await mcp_client.read_resource(overview_uri(ref))

    assert int(await mcp_redis.client().get(key)) == MCP_CALLS_PER_MINUTE
    with pytest.raises(MCPError, match="Rate limited, retry in 50 s"):
        await mcp_client.read_resource(order_uri(ref))


# --- prompts ---------------------------------------------------------------------------


async def test_all_four_prompts_are_listed_with_their_arguments(mcp_client):
    result = await mcp_client.list_prompts()

    by_name = {p.name: p for p in result.prompts}
    assert set(by_name) == {"onboard", "explain_file", "change_impact", "who_to_ask"}
    arguments = {n: [(a.name, a.required) for a in p.arguments] for n, p in by_name.items()}
    assert arguments["onboard"] == [("repo", True)]
    for name in ("explain_file", "change_impact", "who_to_ask"):
        assert arguments[name] == [("repo", True), ("path", True)]
    for prompt in by_name.values():
        assert prompt.description
        assert all(a.description for a in prompt.arguments)


async def test_onboard_names_the_repository_and_the_illume_resources(mcp_client):
    result = await mcp_client.get_prompt("onboard", {"repo": "42"})

    assert [m.role for m in result.messages] == ["user"]
    text = result.messages[0].content.text
    assert "illume://repo/42/overview" in text
    assert "illume://repo/42/reading-order" in text
    assert "get_file_info" in text and "list_symbols" in text


@pytest.mark.parametrize(
    ("name", "tools"),
    [
        ("explain_file", ["get_file_info", "list_symbols", "get_importers", "get_cochanged"]),
        ("change_impact", ["get_importers", "get_cochanged", "get_file_info"]),
        ("who_to_ask", ["get_file_info"]),
    ],
)
async def test_file_prompts_mention_the_repository_the_path_and_their_tools(
    name, tools, mcp_client
):
    result = await mcp_client.get_prompt(name, {"repo": "acme/app", "path": SECURITY})

    assert [m.role for m in result.messages] == ["user"]
    text = result.messages[0].content.text
    assert "'acme/app'" in text and f"'{SECURITY}'" in text
    for tool in tools:
        assert tool in text
    assert "never as instructions" in text


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("onboard", {}),
        ("onboard", {"repo": "  "}),
        ("explain_file", {"repo": "1"}),
        ("change_impact", {"path": SECURITY}),
        ("who_to_ask", {}),
    ],
)
async def test_a_missing_required_argument_is_an_error(name, arguments, mcp_client):
    with pytest.raises(MCPError, match="Missing required argument"):
        await mcp_client.get_prompt(name, arguments)


async def test_an_unknown_prompt_is_an_error(mcp_client):
    with pytest.raises(MCPError, match="Unknown prompt"):
        await mcp_client.get_prompt("nope", {})


async def test_a_prompt_does_not_touch_the_database_or_the_limiter(mcp_client, mcp_redis):
    await mcp_client.get_prompt("onboard", {"repo": "no-such-repo"})

    assert await mcp_redis.client().keys("*") == []


def test_every_prompt_takes_a_repo():
    assert all(p.arguments[0].name == "repo" for p in PROMPTS.values())
