"""Dependency graph rendering at file and symbol level."""

import pytest

from tests.factories import make_ingested_repo, make_repo, make_user
from tests.helpers import authenticate, random_uuid

pytestmark = pytest.mark.integration


def graph_url(repo, level: str | None = None) -> str:
    url = f"/api/v1/repository/{repo.id}/graph"
    return f"{url}?level={level}" if level else url


@pytest.fixture
async def ingested(client, db_session):
    """A signed-in user with a fully populated repository."""
    user = await make_user(db_session)
    repo, files = await make_ingested_repo(db_session, user)
    await authenticate(client, user)
    return user, repo, files


class TestFileLevel:
    async def test_returns_one_node_per_file(self, client, ingested):
        _, repo, files = ingested

        response = await client.get(graph_url(repo))

        assert response.status_code == 200
        assert len(response.json()["nodes"]) == len(files)

    async def test_collapses_symbol_edges_onto_files(self, client, ingested):
        """
        The factory links each file to the next through their symbols, so the file-level
        graph must show that chain rather than three disconnected nodes.
        """
        _, repo, _ = ingested

        body = (await client.get(graph_url(repo))).json()

        assert len(body["links"]) == 2

    async def test_labels_a_node_with_its_basename_and_path(self, client, ingested):
        _, repo, _ = ingested

        node = (await client.get(graph_url(repo))).json()["nodes"][0]

        assert node["label"] == node["path"].split("/")[-1]

    async def test_a_link_carries_a_type_and_a_weight(self, client, ingested):
        _, repo, _ = ingested

        link = (await client.get(graph_url(repo))).json()["links"][0]

        assert link["type"] == "imports"
        assert link["weight"] == 1

    async def test_metadata_counts_nodes_and_edges(self, client, ingested):
        _, repo, files = ingested

        metadata = (await client.get(graph_url(repo))).json()["metadata"]

        assert metadata["total_nodes"] == len(files)
        assert metadata["total_edges"] == 2

    async def test_scores_criticality_at_request_time(self, client, ingested):
        """`criticality_score` is derived per request, not a stored column."""
        _, repo, _ = ingested

        node = (await client.get(graph_url(repo))).json()["nodes"][0]

        assert node["criticality"] == "safe"
        assert node["criticality_score"] == 25

    async def test_is_the_default_level(self, client, ingested):
        _, repo, _ = ingested

        with_param = (await client.get(graph_url(repo, "file"))).json()
        without_param = (await client.get(graph_url(repo))).json()

        assert len(without_param["nodes"]) == len(with_param["nodes"])


class TestSymbolLevel:
    async def test_returns_symbol_nodes(self, client, ingested):
        _, repo, files = ingested

        body = (await client.get(graph_url(repo, "symbol"))).json()

        assert len(body["nodes"]) == len(files)  # one function per file in the factory

    async def test_excludes_non_function_and_class_kinds(self, client, db_session, ingested):
        """
        The symbol graph is deliberately narrower than the symbol table -- an import
        symbol must not become a node.
        """
        from tests.factories import make_symbol

        _, repo, files = ingested
        await make_symbol(db_session, files[0], name="some_import", kind="import")

        body = (await client.get(graph_url(repo, "symbol"))).json()

        assert "some_import" not in {n["label"] for n in body["nodes"]}

    async def test_symbol_nodes_carry_complexity_and_loc(self, client, ingested):
        _, repo, _ = ingested

        node = (await client.get(graph_url(repo, "symbol"))).json()["nodes"][0]

        assert "complexity" in node
        assert node["loc"] >= 1


class TestEmptyGraph:
    async def test_a_repo_with_no_files_yields_no_nodes(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status="ready")
        await authenticate(client, user)

        body = (await client.get(graph_url(repo))).json()

        assert body["nodes"] == []
        assert body["links"] == []

    async def test_metadata_is_zeroed_not_null(self, client, db_session):
        """Clients read these as numbers; a null here would break rendering."""
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status="ready")
        await authenticate(client, user)

        metadata = (await client.get(graph_url(repo))).json()["metadata"]

        assert metadata == {"total_nodes": 0, "total_edges": 0, "clusters": 0}


class TestGuards:
    @pytest.mark.parametrize("status", ["pending", "cloning", "parsing", "embedding", "failed"])
    async def test_refuses_a_repository_that_is_not_ready(self, client, db_session, status):
        """
        `ready` is the gate. Every other member of the enum must be refused, and 409 is
        the documented code rather than 404 -- the repo exists, it just has no graph yet.
        """
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status=status)
        await authenticate(client, user)

        response = await client.get(graph_url(repo))

        assert response.status_code == 409
        assert status in response.json()["detail"]

    async def test_another_users_repository_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, theirs)
        await authenticate(client, mine)

        response = await client.get(graph_url(repo))

        assert response.status_code == 404

    async def test_an_unknown_id_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(f"/api/v1/repository/{random_uuid()}/graph")).status_code == 404

    async def test_a_malformed_id_is_a_validation_error(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get("/api/v1/repository/not-a-uuid/graph")).status_code == 422

    async def test_an_unknown_level_is_a_validation_error(self, client, ingested):
        _, repo, _ = ingested

        assert (await client.get(graph_url(repo, "galaxy"))).status_code == 422

    async def test_requires_authentication(self, client, ingested):
        _, repo, _ = ingested
        client.cookies.clear()

        assert (await client.get(graph_url(repo))).status_code == 401
