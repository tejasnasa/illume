"""``whoami`` and ``list_repositories`` over the real transport, with real tokens."""

from __future__ import annotations

import pytest

from app.services.mcp_tokens import create_token
from tests.factories import make_repo, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def mcp_repos(db_session, mcp_user):
    """Two ready repositories for the token owner, plus a pending one."""
    first = await make_repo(
        db_session, mcp_user, name="alpha", github_url="https://github.com/acme/alpha"
    )
    second = await make_repo(
        db_session, mcp_user, name="beta", github_url="https://github.com/acme/beta.git"
    )
    pending = await make_repo(
        db_session,
        mcp_user,
        name="gamma",
        github_url="https://github.com/acme/gamma",
        status="parsing",
    )
    return first, second, pending


# A client's requests check its token on a session that shares the test's one
# connection, so rows are created before the client connects, never while it is.


class TestWhoami:
    async def test_it_returns_the_token_owner_and_repository_count(
        self, mcp_user, mcp_repos, mcp_client
    ):
        result = await mcp_client.call_tool("whoami", {})

        assert result.is_error is not True
        assert result.structured_content == {
            "email": mcp_user.email,
            "repositories_count": 3,
        }
        assert mcp_user.email in result.content[0].text

    async def test_it_does_not_count_other_users_repositories(
        self, mcp_connect, db_session, auth_headers
    ):
        other = await make_user(db_session)
        await make_repo(db_session, other)

        async with mcp_connect(**auth_headers) as client:
            result = await client.call_tool("whoami", {})

        assert result.structured_content["repositories_count"] == 0


class TestListRepositories:
    async def test_the_tool_declares_a_strict_schema_and_read_only_hints(self, mcp_client):
        tool = next(
            t for t in (await mcp_client.list_tools()).tools if t.name == "list_repositories"
        )

        assert tool.input_schema["additionalProperties"] is False
        assert tool.input_schema["properties"]["status"]["enum"] == ["ready", "all"]
        assert tool.title == "List repositories"
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False

    async def test_by_default_only_ready_repositories_are_listed(self, mcp_repos, mcp_client):
        first, second, _ = mcp_repos

        result = await mcp_client.call_tool("list_repositories", {})

        repos = result.structured_content["repositories"]
        assert [r["number"] for r in repos] == [first.repo_number, second.repo_number]
        assert {r["status"] for r in repos} == {"ready"}

    async def test_status_all_includes_repositories_that_are_not_ready(self, mcp_repos, mcp_client):
        result = await mcp_client.call_tool("list_repositories", {"status": "all"})

        repos = result.structured_content["repositories"]
        assert [r["name"] for r in repos] == ["alpha", "beta", "gamma"]
        assert repos[2]["status"] == "parsing"

    async def test_an_entry_carries_everything_a_model_needs(self, mcp_repos, mcp_client):
        first, *_ = mcp_repos

        result = await mcp_client.call_tool("list_repositories", {})

        entry = result.structured_content["repositories"][0]
        assert entry == {
            "repo": str(first.repo_number),
            "number": first.repo_number,
            "id": str(first.id),
            "name": "alpha",
            "github_url": "https://github.com/acme/alpha",
            "status": "ready",
            "ingested_branch": first.ingested_branch,
            "ingested_commit_sha": first.ingested_commit_sha,
            "created_at": first.created_at.isoformat(),
            "last_synced_at": None,
        }
        assert f"repo={first.repo_number}" in result.content[0].text
        assert "https://github.com/acme/alpha" in result.content[0].text

    async def test_only_the_token_owners_repositories_are_returned(
        self, mcp_connect, db_session, mcp_repos, mcp_user, auth_headers
    ):
        stranger = await make_user(db_session)
        await make_repo(db_session, stranger, name="theirs-1", github_url="https://github.com/x/t1")
        await make_repo(db_session, stranger, name="theirs-2", github_url="https://github.com/x/t2")
        _, stranger_token = await create_token(db_session, stranger.id, "stranger", 30)

        async with mcp_connect(**auth_headers) as mine:
            mine_names = [
                r["name"]
                for r in (
                    await mine.call_tool("list_repositories", {"status": "all"})
                ).structured_content["repositories"]
            ]
        async with mcp_connect(authorization=f"Bearer {stranger_token}") as theirs:
            their_names = [
                r["name"]
                for r in (
                    await theirs.call_tool("list_repositories", {"status": "all"})
                ).structured_content["repositories"]
            ]

        assert mine_names == ["alpha", "beta", "gamma"]
        assert their_names == ["theirs-1", "theirs-2"]

    async def test_a_user_with_no_repositories_gets_an_empty_list(self, mcp_client):
        result = await mcp_client.call_tool("list_repositories", {})

        assert result.is_error is not True
        assert result.structured_content == {"repositories": []}
        assert "No ready repositories" in result.content[0].text

    @pytest.mark.parametrize("arguments", [{"status": "pending"}, {"status": 1}, {"bogus": True}])
    async def test_invalid_arguments_are_an_error_result_not_an_exception(
        self, mcp_client, arguments
    ):
        result = await mcp_client.call_tool("list_repositories", arguments)

        assert result.is_error is True
        assert "ready" in result.content[0].text
