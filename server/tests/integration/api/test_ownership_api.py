"""Per-file code ownership and knowledge-silo detection."""

import pytest

from tests.factories import make_code_owner, make_ingested_repo, make_user
from tests.helpers import authenticate, random_uuid

pytestmark = pytest.mark.integration


def map_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/ownership"


def silos_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/ownership/silos"


TWO_CONTRIBUTORS = [
    {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "percentage": 80.0,
        "last_commit": "2026-01-01",
    },
    {
        "name": "Grace Hopper",
        "email": "grace@example.com",
        "percentage": 20.0,
        "last_commit": "2025-12-01",
    },
]


@pytest.fixture
async def owned(client, db_session):
    """
    A signed-in user with three owned files.

    The factory chains files 0 -> 1 -> 2, so ownership is attached per file and one of
    them is flagged as a silo.
    """
    user = await make_user(db_session)
    repo, files = await make_ingested_repo(db_session, user)
    await make_code_owner(
        db_session,
        files[0],
        primary_owner="Ada Lovelace",
        contributors=TWO_CONTRIBUTORS,
        bus_factor=2,
    )
    await make_code_owner(
        db_session,
        files[1],
        primary_owner="Grace Hopper",
        bus_factor=1,
        is_knowledge_silo=True,
    )
    await make_code_owner(
        db_session,
        files[2],
        primary_owner="Ada Lovelace",
        contributors=[{"name": "Ada Lovelace", "email": "ada@example.com", "percentage": 100.0}],
        bus_factor=1,
    )
    await authenticate(client, user)
    return user, repo, files


class TestOwnershipMap:
    async def test_lists_every_owned_file(self, client, owned):
        _, repo, files = owned

        body = (await client.get(map_url(repo))).json()

        assert body["total"] == len(files)
        assert len(body["files"]) == len(files)

    async def test_orders_by_file_path(self, client, owned):
        _, repo, _ = owned

        body = (await client.get(map_url(repo))).json()

        paths = [f["file_path"] for f in body["files"]]
        assert paths == sorted(paths)

    async def test_reports_the_primary_owner(self, client, owned):
        _, repo, _ = owned

        body = (await client.get(map_url(repo))).json()

        by_path = {f["file_path"]: f for f in body["files"]}
        assert by_path["src/module_1.py"]["primary_owner"] == "Grace Hopper"

    async def test_expands_the_contributor_list(self, client, owned):
        _, repo, _ = owned

        body = (await client.get(map_url(repo))).json()

        by_path = {f["file_path"]: f for f in body["files"]}
        contributors = by_path["src/module_0.py"]["contributors"]
        assert [c["name"] for c in contributors] == ["Ada Lovelace", "Grace Hopper"]
        assert contributors[0]["percentage"] == 80.0
        assert contributors[0]["last_commit"] == "2026-01-01"

    async def test_reports_bus_factor_and_silo_flag(self, client, owned):
        _, repo, _ = owned

        body = (await client.get(map_url(repo))).json()

        by_path = {f["file_path"]: f for f in body["files"]}
        assert by_path["src/module_0.py"]["bus_factor"] == 2
        assert by_path["src/module_0.py"]["is_knowledge_silo"] is False
        assert by_path["src/module_1.py"]["is_knowledge_silo"] is True

    async def test_a_null_contributor_list_becomes_empty(self, client, db_session):
        """`contributors` is a nullable JSONB column; the response type is a list."""
        user = await make_user(db_session)
        repo, files = await make_ingested_repo(db_session, user)
        await make_code_owner(db_session, files[0], contributors=None)
        await authenticate(client, user)

        body = (await client.get(map_url(repo))).json()

        assert body["files"][0]["contributors"] == []

    async def test_paginates_while_reporting_the_full_total(self, client, owned):
        _, repo, files = owned

        body = (await client.get(f"{map_url(repo)}?page_size=2&page=1")).json()

        assert len(body["files"]) == 2
        assert body["total"] == len(files)

    async def test_the_second_page_holds_the_remainder(self, client, owned):
        _, repo, files = owned

        body = (await client.get(f"{map_url(repo)}?page_size=2&page=2")).json()

        assert len(body["files"]) == len(files) - 2

    async def test_filters_by_exact_file_path(self, client, owned):
        _, repo, _ = owned

        body = (await client.get(f"{map_url(repo)}?file_path=src/module_1.py")).json()

        assert body["total"] == 1
        assert body["files"][0]["file_path"] == "src/module_1.py"

    async def test_the_filter_narrows_the_total_too(self, client, owned):
        """
        The count query repeats the filter rather than reusing the page query. If that
        drifts, the pager shows a total that does not match the rows.
        """
        _, repo, _ = owned

        body = (await client.get(f"{map_url(repo)}?file_path=src/module_0.py")).json()

        assert body["total"] == 1

    async def test_an_unowned_repository_returns_nothing(self, client, db_session):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await authenticate(client, user)

        body = (await client.get(map_url(repo))).json()

        assert body["files"] == []
        assert body["total"] == 0

    @pytest.mark.parametrize(
        ("param", "value"),
        [("page", "0"), ("page_size", "0"), ("page_size", "201")],
        ids=["page-zero", "size-zero", "size-too-large"],
    )
    async def test_rejects_out_of_range_pagination(self, client, owned, param, value):
        _, repo, _ = owned

        assert (await client.get(f"{map_url(repo)}?{param}={value}")).status_code == 422


class TestKnowledgeSilos:
    async def test_returns_only_flagged_files(self, client, owned):
        _, repo, _ = owned

        body = (await client.get(silos_url(repo))).json()

        assert body["total"] == 1
        assert body["silos"][0]["file_path"] == "src/module_1.py"

    async def test_a_silo_entry_carries_its_owner(self, client, owned):
        _, repo, _ = owned

        silo = (await client.get(silos_url(repo))).json()["silos"][0]

        assert silo["primary_owner"] == "Grace Hopper"
        assert silo["bus_factor"] == 1
        assert silo["is_knowledge_silo"] is True

    async def test_is_empty_when_nothing_is_flagged(self, client, db_session):
        user = await make_user(db_session)
        repo, files = await make_ingested_repo(db_session, user)
        await make_code_owner(db_session, files[0], bus_factor=3, is_knowledge_silo=False)
        await authenticate(client, user)

        body = (await client.get(silos_url(repo))).json()

        assert body["silos"] == []
        assert body["total"] == 0


class TestGuards:
    @pytest.mark.parametrize("path", ["ownership", "ownership/silos"])
    async def test_another_users_repository_is_not_found(self, client, db_session, path):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, files = await make_ingested_repo(db_session, theirs)
        await make_code_owner(db_session, files[0])
        await authenticate(client, mine)

        assert (await client.get(f"/api/v1/repository/{their_repo.id}/{path}")).status_code == 404

    async def test_an_unknown_id_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        url = f"/api/v1/repository/{random_uuid()}/ownership"
        assert (await client.get(url)).status_code == 404

    async def test_a_malformed_id_is_a_validation_error(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get("/api/v1/repository/not-a-uuid/ownership")).status_code == 422

    @pytest.mark.parametrize("path", ["ownership", "ownership/silos"])
    async def test_requires_authentication(self, client, db_session, path):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        client.cookies.clear()

        assert (await client.get(f"/api/v1/repository/{repo.id}/{path}")).status_code == 401
