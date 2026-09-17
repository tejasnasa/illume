"""Repository statistics aggregation."""

import pytest

from tests.factories import (
    make_code_owner,
    make_file,
    make_ingested_repo,
    make_repo,
    make_symbol,
    make_user,
)
from tests.helpers import authenticate, random_uuid

pytestmark = pytest.mark.integration


def stats_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/stats"


@pytest.fixture
async def populated(client, db_session):
    """
    A signed-in user with a fully populated repository.

    The factory chains three files of 10 lines each with two dependency edges. One file
    is a knowledge silo, and Ada owns two of the three.
    """
    user = await make_user(db_session)
    repo, files = await make_ingested_repo(db_session, user)
    await make_code_owner(db_session, files[0], primary_owner="Ada Lovelace", bus_factor=2)
    await make_code_owner(
        db_session,
        files[1],
        primary_owner="Grace Hopper",
        bus_factor=1,
        is_knowledge_silo=True,
    )
    await make_code_owner(db_session, files[2], primary_owner="Ada Lovelace", bus_factor=1)
    await authenticate(client, user)
    return user, repo, files


class TestTotals:
    async def test_counts_files_and_lines(self, client, populated):
        _, repo, files = populated

        body = (await client.get(stats_url(repo))).json()

        assert body["total_files"] == len(files)
        assert body["total_loc"] == 30  # the factory writes 10 lines per file

    async def test_echoes_the_repository_id(self, client, populated):
        _, repo, _ = populated

        body = (await client.get(stats_url(repo))).json()

        assert body["repository_id"] == str(repo.id)

    async def test_counts_dependency_edges(self, client, populated):
        _, repo, _ = populated

        body = (await client.get(stats_url(repo))).json()

        assert body["total_dependencies"] == 2  # a three-file chain

    async def test_an_empty_repository_reports_zeros_not_nulls(self, client, db_session):
        """
        `SUM` over no rows is NULL in SQL. Left uncoerced it would serialize as null and
        break the client's arithmetic.
        """
        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        body = (await client.get(stats_url(repo))).json()

        assert body["total_files"] == 0
        assert body["total_loc"] == 0
        assert body["total_dependencies"] == 0
        assert body["total_contributors"] == 0
        assert body["knowledge_silo_count"] == 0
        assert body["language_breakdown"] == []
        assert body["top_contributors"] == []


class TestLanguageBreakdown:
    async def test_groups_files_by_language(self, client, db_session, populated):
        _, repo, _ = populated
        await make_file(db_session, repo, path="web/app.ts", language="typescript", loc=25)

        body = (await client.get(stats_url(repo))).json()

        by_lang = {row["language"]: row for row in body["language_breakdown"]}
        assert by_lang["python"]["file_count"] == 3
        assert by_lang["python"]["loc_count"] == 30
        assert by_lang["typescript"]["file_count"] == 1
        assert by_lang["typescript"]["loc_count"] == 25

    async def test_a_null_language_is_labelled_unknown(self, client, db_session, populated):
        """`language` is nullable on the model, and the client renders this string."""
        _, repo, _ = populated
        await make_file(db_session, repo, path="mystery", language=None, loc=5)

        body = (await client.get(stats_url(repo))).json()

        assert "Unknown" in {row["language"] for row in body["language_breakdown"]}


class TestContributors:
    async def test_counts_distinct_owners(self, client, populated):
        _, repo, _ = populated

        body = (await client.get(stats_url(repo))).json()

        assert body["total_contributors"] == 2

    async def test_ranks_the_owner_of_the_most_files_first(self, client, populated):
        _, repo, _ = populated

        body = (await client.get(stats_url(repo))).json()

        assert body["top_contributors"][0] == {"name": "Ada Lovelace", "files_owned": 2}
        assert body["top_contributors"][1] == {"name": "Grace Hopper", "files_owned": 1}

    async def test_caps_the_leaderboard_at_five(self, client, db_session, populated):
        _, repo, _ = populated
        for index in range(6):
            file = await make_file(db_session, repo, path=f"extra/{index}.py")
            await make_code_owner(db_session, file, primary_owner=f"Contributor {index}")

        body = (await client.get(stats_url(repo))).json()

        assert len(body["top_contributors"]) == 5

    async def test_counts_knowledge_silos(self, client, populated):
        _, repo, _ = populated

        body = (await client.get(stats_url(repo))).json()

        assert body["knowledge_silo_count"] == 1


class TestScoping:
    async def test_stats_never_include_another_repositorys_rows(self, client, db_session):
        """
        Every aggregate joins through `File.repository_id`. If one of them forgot that
        filter the totals would silently include unrelated rows, so the two repos are
        given deliberately different sizes.
        """
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        my_repo, _ = await make_ingested_repo(db_session, mine)
        their_repo, their_files = await make_ingested_repo(db_session, theirs, file_count=6)
        for file in their_files:
            await make_code_owner(db_session, file, primary_owner="Someone Else")
        await authenticate(client, mine)

        body = (await client.get(stats_url(my_repo))).json()

        assert body["total_files"] == 3
        assert body["total_contributors"] == 0

    async def test_a_dependency_into_another_repository_is_not_counted(self, client, db_session):
        """
        The dependency count joins `Dependency -> source_symbol -> File`. The join is on
        the *source* side only, so an edge originating outside this repo is excluded while
        one terminating here would still be counted.
        """
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        my_repo, my_files = await make_ingested_repo(db_session, mine)
        _, their_files = await make_ingested_repo(db_session, theirs, file_count=2)

        from tests.factories import make_dependency

        their_symbol = await make_symbol(db_session, their_files[0], name="outsider")
        my_symbol = await make_symbol(db_session, my_files[0], name="mine")
        await make_dependency(db_session, their_symbol, my_symbol)
        await authenticate(client, mine)

        body = (await client.get(stats_url(my_repo))).json()

        assert body["total_dependencies"] == 2  # unchanged by the cross-repo edge


class TestGuards:
    async def test_another_users_repository_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await authenticate(client, mine)

        assert (await client.get(stats_url(their_repo))).status_code == 404

    async def test_an_unknown_id_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(f"/api/v1/repository/{random_uuid()}/stats")).status_code == 404

    async def test_a_malformed_id_is_a_validation_error(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get("/api/v1/repository/not-a-uuid/stats")).status_code == 422

    async def test_requires_authentication(self, client, populated):
        _, repo, _ = populated
        client.cookies.clear()

        assert (await client.get(stats_url(repo))).status_code == 401
