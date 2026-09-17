"""GitHub proxy happy paths.

respx intercepts the outbound `httpx` calls, so nothing here touches github.com. The
proxy holding the user's OAuth token is the whole reason this router exists -- the client
never sees the token -- so the abuse matrix lives separately in
`tests/security/test_github_proxy_abuse.py`.
"""

import httpx
import pytest
import respx

from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

API = "https://api.github.com"
TOKEN = "gho_supersecret_token_value"

REPO = {
    "full_name": "example/cool-project",
    "name": "cool-project",
    "private": False,
    "default_branch": "main",
    "description": "A project.",
    "language": "Python",
    "updated_at": "2026-01-01T00:00:00Z",
    "html_url": "https://github.com/example/cool-project",
    "stargazers_count": 42,
}


@pytest.fixture
async def linked(client, db_session):
    """A signed-in user whose GitHub account is linked."""
    user = await make_user(db_session, github_access_token=TOKEN)
    await authenticate(client, user)
    return user


@pytest.fixture
async def unlinked(client, db_session):
    """A signed-in user with no GitHub token."""
    user = await make_user(db_session, github_access_token=None)
    await authenticate(client, user)
    return user


class TestListRepos:
    @respx.mock
    async def test_returns_the_users_repositories(self, client, linked):
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[REPO]))

        response = await client.get("/api/v1/github/repos")

        assert response.status_code == 200
        assert response.json()[0]["full_name"] == "example/cool-project"

    @respx.mock
    async def test_maps_the_token_onto_the_outbound_request(self, client, linked):
        route = respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[REPO]))

        await client.get("/api/v1/github/repos")

        assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"

    @respx.mock
    async def test_forwards_pagination(self, client, linked):
        route = respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[REPO]))

        await client.get("/api/v1/github/repos?page=3&per_page=10")

        params = route.calls.last.request.url.params
        assert params["page"] == "3"
        assert params["per_page"] == "10"

    @respx.mock
    async def test_filters_locally_by_name_substring(self, client, linked):
        """
        `q` is applied after the fetch, not forwarded to GitHub, so the upstream call is
        unaffected and the response is narrowed in Python.
        """
        other = {**REPO, "name": "unrelated", "full_name": "example/unrelated"}
        route = respx.get(f"{API}/user/repos").mock(
            return_value=httpx.Response(200, json=[REPO, other])
        )

        body = (await client.get("/api/v1/github/repos?q=cool")).json()

        assert [r["name"] for r in body] == ["cool-project"]
        assert "q" not in route.calls.last.request.url.params

    @respx.mock
    async def test_the_name_filter_is_case_insensitive(self, client, linked):
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[REPO]))

        body = (await client.get("/api/v1/github/repos?q=COOL")).json()

        assert len(body) == 1

    @respx.mock
    async def test_an_empty_filter_returns_everything(self, client, linked):
        other = {**REPO, "name": "unrelated", "full_name": "example/unrelated"}
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[REPO, other]))

        assert len((await client.get("/api/v1/github/repos?q=")).json()) == 2

    @respx.mock
    async def test_a_missing_field_falls_back_to_a_default(self, client, linked):
        """GitHub omits some keys on older repos; the response model has defaults."""
        sparse = {
            "full_name": "example/bare",
            "name": "bare",
            "updated_at": "2026-01-01T00:00:00Z",
            "html_url": "https://github.com/example/bare",
        }
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=[sparse]))

        body = (await client.get("/api/v1/github/repos")).json()

        assert body[0]["private"] is False
        assert body[0]["default_branch"] == "main"
        assert body[0]["stargazers_count"] == 0

    @pytest.mark.parametrize(
        ("param", "value"),
        [("per_page", "101"), ("per_page", "0"), ("page", "0"), ("page", "-1")],
        ids=["per-page-too-large", "per-page-zero", "page-zero", "page-negative"],
    )
    async def test_rejects_out_of_range_pagination(self, client, linked, param, value):
        """Rejected before any outbound call, so no mock is needed."""
        response = await client.get(f"/api/v1/github/repos?{param}={value}")

        assert response.status_code == 422

    @respx.mock
    async def test_an_expired_token_surfaces_as_401(self, client, linked):
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(401, json={}))

        response = await client.get("/api/v1/github/repos")

        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @respx.mock
    async def test_an_upstream_failure_surfaces_as_502(self, client, linked):
        respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(500, text="boom"))

        assert (await client.get("/api/v1/github/repos")).status_code == 502


class TestBranches:
    @respx.mock
    async def test_marks_the_default_branch(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "develop"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"name": "main", "commit": {"sha": "a" * 40}},
                    {"name": "develop", "commit": {"sha": "b" * 40}},
                ],
            )
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/branches")).json()

        by_name = {b["name"]: b for b in body}
        assert by_name["develop"]["is_default"] is True
        assert by_name["main"]["is_default"] is False

    @respx.mock
    async def test_a_repository_github_does_not_have_is_404(self, client, linked):
        respx.get(f"{API}/repos/example/nope").mock(return_value=httpx.Response(404, json={}))

        response = await client.get("/api/v1/github/repos/example/nope/branches")

        assert response.status_code == 404

    @respx.mock
    async def test_a_failing_branch_fetch_is_502(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(500, text="boom")
        )

        response = await client.get("/api/v1/github/repos/example/cool-project/branches")

        assert response.status_code == 502


class TestCommits:
    def commit(self, sha="a" * 40, message="feat: a thing", author="Ada Lovelace"):
        return {
            "sha": sha,
            "commit": {
                "message": message,
                "author": {"name": author, "date": "2026-01-01T00:00:00Z"},
            },
            "author": {"login": "ada", "avatar_url": "https://avatars.example/ada"},
            "parents": [],
        }

    @respx.mock
    async def test_returns_commits(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[self.commit()])
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/commits")).json()

        assert body[0]["author_name"] == "Ada Lovelace"
        assert body[0]["authored_at"] == "2026-01-01T00:00:00Z"

    @respx.mock
    async def test_shortens_the_sha_to_seven_characters(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[self.commit()])
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/commits")).json()

        assert body[0]["short_sha"] == "a" * 7

    @respx.mock
    async def test_keeps_only_the_first_line_of_a_message(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(
                200, json=[self.commit(message="feat: subject\n\nA long body.")]
            )
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/commits")).json()

        assert body[0]["message"] == "feat: subject"

    @respx.mock
    async def test_falls_back_to_the_login_when_the_commit_author_is_unset(self, client, linked):
        """A commit made through the web UI can have no `commit.author` at all."""
        orphan = {
            "sha": "b" * 40,
            "commit": {"message": "chore: x", "author": None},
            "author": {"login": "ghost", "avatar_url": None},
            "parents": [],
        }
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[orphan])
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/commits")).json()

        assert body[0]["author_name"] == "ghost"

    @respx.mock
    async def test_a_commit_with_no_author_at_all_is_unknown(self, client, linked):
        orphan = {
            "sha": "c" * 40,
            "commit": {"message": "chore: x", "author": None},
            "author": None,
            "parents": [],
        }
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[orphan])
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/commits")).json()

        assert body[0]["author_name"] == "Unknown"

    @respx.mock
    async def test_a_missing_date_falls_back_to_the_epoch(self, client, linked):
        """
        The fallback is a fixed sentinel rather than `now()`, so a commit without a date
        sorts to the bottom instead of jumping to the top on every request.
        """
        orphan = {
            "sha": "d" * 40,
            "commit": {"message": "chore: x", "author": {}},
            "author": None,
            "parents": [],
        }
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[orphan])
        )

        body = (await client.get("/api/v1/github/repos/example/cool-project/commits")).json()

        assert body[0]["authored_at"].startswith("2000-01-01")

    @respx.mock
    async def test_forwards_the_sha_filter(self, client, linked):
        route = respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[])
        )

        await client.get("/api/v1/github/repos/example/cool-project/commits?sha=develop")

        assert route.calls.last.request.url.params["sha"] == "develop"

    @respx.mock
    async def test_an_unknown_branch_is_404(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(404, json={})
        )

        response = await client.get("/api/v1/github/repos/example/cool-project/commits")

        assert response.status_code == 404


class TestMultiBranchCommits:
    @respx.mock
    async def test_merges_commits_across_branches(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}, {"name": "develop"}])
        )
        shared = {
            "sha": "a" * 40,
            "commit": {
                "message": "shared",
                "author": {"name": "Ada", "date": "2026-01-02T00:00:00Z"},
            },
            "author": None,
            "parents": [],
        }
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=[shared]
                if request.url.params["sha"] == "main"
                else [
                    shared,
                    {
                        **shared,
                        "sha": "b" * 40,
                        "commit": {**shared["commit"], "message": "only-develop"},
                    },
                ],
            )
        )

        body = (
            await client.get("/api/v1/github/repos/example/cool-project/commits-multibranch")
        ).json()

        assert {c["message"] for c in body} == {"shared", "only-develop"}

    @respx.mock
    async def test_records_every_branch_a_commit_appears_on(self, client, linked):
        """Dedupe is by SHA; the branch list is what survives the merge."""
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}, {"name": "develop"}])
        )
        shared = {
            "sha": "a" * 40,
            "commit": {
                "message": "shared",
                "author": {"name": "Ada", "date": "2026-01-02T00:00:00Z"},
            },
            "author": None,
            "parents": [],
        }
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[shared])
        )

        body = (
            await client.get("/api/v1/github/repos/example/cool-project/commits-multibranch")
        ).json()

        assert len(body) == 1
        assert sorted(body[0]["branches"]) == ["develop", "main"]

    @respx.mock
    async def test_sorts_newest_first(self, client, linked):
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}])
        )

        def build(sha, date):
            return {
                "sha": sha,
                "commit": {"message": sha, "author": {"name": "Ada", "date": date}},
                "author": None,
                "parents": [],
            }

        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(
                200,
                json=[
                    build("a" * 40, "2026-01-01T00:00:00Z"),
                    build("b" * 40, "2026-06-01T00:00:00Z"),
                ],
            )
        )

        body = (
            await client.get("/api/v1/github/repos/example/cool-project/commits-multibranch")
        ).json()

        assert body[0]["authored_at"].startswith("2026-06")

    @respx.mock
    async def test_a_branch_whose_fetch_fails_is_skipped_not_fatal(self, client, linked):
        """
        Individual branch fetches swallow failures and return empty, so one bad branch
        must not take down the merged view.
        """
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "develop"}])
        )
        respx.get(f"{API}/repos/example/cool-project/commits").mock(
            side_effect=lambda request: httpx.Response(
                200 if request.url.params["sha"] == "main" else 500,
                json=[
                    {
                        "sha": "a" * 40,
                        "commit": {
                            "message": "ok",
                            "author": {"name": "Ada", "date": "2026-01-01T00:00:00Z"},
                        },
                        "author": None,
                        "parents": [],
                    }
                ],
            )
        )

        response = await client.get("/api/v1/github/repos/example/cool-project/commits-multibranch")

        assert response.status_code == 200
        assert [c["message"] for c in response.json()] == ["ok"]

    @respx.mock
    async def test_caps_the_fan_out_at_five_branches(self, client, linked):
        """
        Only the default plus four others are fetched. One request per branch means this
        cap is what bounds GitHub API usage per page view.
        """
        respx.get(f"{API}/repos/example/cool-project").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(f"{API}/repos/example/cool-project/branches").mock(
            return_value=httpx.Response(200, json=[{"name": f"b{i}"} for i in range(10)])
        )
        commits = respx.get(f"{API}/repos/example/cool-project/commits").mock(
            return_value=httpx.Response(200, json=[])
        )

        await client.get("/api/v1/github/repos/example/cool-project/commits-multibranch")

        assert commits.call_count == 5


class TestGuards:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/github/repos",
            "/api/v1/github/repos/example/cool-project/branches",
            "/api/v1/github/repos/example/cool-project/commits",
            "/api/v1/github/repos/example/cool-project/commits-multibranch",
        ],
    )
    async def test_an_unlinked_account_is_403(self, client, unlinked, path):
        response = await client.get(path)

        assert response.status_code == 403
        assert "not linked" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/github/repos",
            "/api/v1/github/repos/example/cool-project/branches",
        ],
    )
    async def test_requires_authentication(self, client, path):
        """
        The middleware rejects these before `get_current_user` runs, so an anonymous
        caller gets 401 rather than the 403 an unlinked account would see.
        """
        client.cookies.clear()

        assert (await client.get(path)).status_code == 401
