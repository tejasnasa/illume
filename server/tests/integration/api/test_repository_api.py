"""Repository CRUD, ingestion dispatch, and re-ingestion."""

import uuid

import pytest

from tests.factories import make_ingested_repo, make_repo, make_user
from tests.fixtures.golden import assert_matches_golden
from tests.helpers import BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY, authenticate

pytestmark = pytest.mark.integration

COLLECTION = "/api/v1/repository"
GITHUB_URL = "https://github.com/example/cool-project"


@pytest.fixture
def dispatched(monkeypatch):
    """
    Capture Celery dispatch instead of sending it.

    `create_repository` calls `ingest_repository.delay(...)`, which would try to reach
    the broker. The dispatch itself is what these tests assert on; whether a worker
    would pick the message up is not this layer's concern.
    """
    calls: list[tuple] = []

    def fake_delay(repo_id, token, **kwargs):
        calls.append((repo_id, token, kwargs))

    import app.api.v1.repository as repository_module

    monkeypatch.setattr(repository_module.ingest_repository, "delay", fake_delay)
    return calls


@pytest.fixture
async def owner(client, db_session):
    user = await make_user(db_session)
    await authenticate(client, user)
    return user


class TestCreate:
    @BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY
    async def test_returns_202_with_ids(self, client, db_session, owner, dispatched):
        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        assert response.status_code == 202
        body = response.json()
        assert uuid.UUID(body["repo_id"])
        assert isinstance(body["repo_num"], int)

    @BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY
    async def test_persists_the_repository(self, client, db_session, owner, dispatched):
        from sqlalchemy import select

        from app.models.repository import Repository

        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        repo_id = uuid.UUID(response.json()["repo_id"])
        result = await db_session.execute(select(Repository).where(Repository.id == repo_id))
        assert result.scalar_one_or_none() is not None

    @BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY
    async def test_derives_the_name_from_the_url(self, client, db_session, owner, dispatched):
        from sqlalchemy import select

        from app.models.repository import Repository

        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        repo_id = uuid.UUID(response.json()["repo_id"])
        result = await db_session.execute(select(Repository).where(Repository.id == repo_id))
        assert result.scalar_one().name == "cool-project"

    @BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY
    async def test_queues_ingestion(self, client, db_session, owner, dispatched):
        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        assert len(dispatched) == 1
        assert dispatched[0][0] == response.json()["repo_id"]

    @BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY
    async def test_forwards_the_branch(self, client, db_session, owner, dispatched):
        await client.post(COLLECTION, json={"github_url": GITHUB_URL, "branch": "develop"})

        assert dispatched[0][2]["branch"] == "develop"

    @BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY
    async def test_starts_in_a_non_ready_state(self, client, db_session, owner, dispatched):
        """A fresh repository must not report itself as ready before ingestion runs."""
        from sqlalchemy import select

        from app.models.repository import Repository

        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        repo_id = uuid.UUID(response.json()["repo_id"])
        result = await db_session.execute(select(Repository).where(Repository.id == repo_id))
        assert result.scalar_one().status != "ready"

    async def test_requires_authentication(self, client, dispatched):
        """Rejected by the middleware, so it never reaches the insert."""
        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        assert response.status_code == 401
        assert dispatched == []

    async def test_rejects_a_missing_url(self, client, owner, dispatched):
        """Rejected by request validation, so it never reaches the insert."""
        response = await client.post(COLLECTION, json={})

        assert response.status_code == 422


class TestList:
    async def test_lists_only_the_callers_repositories(self, client, db_session):
        from tests.factories import make_user

        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        await make_repo(db_session, mine, name="mine")
        await make_repo(db_session, theirs, name="theirs")
        await authenticate(client, mine)

        response = await client.get(COLLECTION)

        assert response.status_code == 200
        assert [r["name"] for r in response.json()] == ["mine"]

    async def test_is_empty_for_a_new_user(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        response = await client.get(COLLECTION)

        assert response.json() == []

    async def test_truncates_long_summaries(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        repo.architecture_summary = "x" * 500
        await db_session.flush()
        await authenticate(client, user)

        response = await client.get(COLLECTION)

        summary = response.json()[0]["architecture_summary"]
        assert len(summary) == 203  # 200 chars plus the ellipsis
        assert summary.endswith("...")

    async def test_requires_authentication(self, client):
        assert (await client.get(COLLECTION)).status_code == 401


class TestGetByRepoNumber:
    async def test_returns_the_repository(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, name="findme")
        await authenticate(client, user)

        response = await client.get(f"{COLLECTION}/{repo.repo_number}")

        assert response.status_code == 200
        assert response.json()["name"] == "findme"

    async def test_another_users_number_is_not_found(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo = await make_repo(db_session, theirs)
        await authenticate(client, mine)

        response = await client.get(f"{COLLECTION}/{their_repo.repo_number}")

        assert response.status_code == 404

    async def test_a_non_integer_number_is_a_validation_error(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(f"{COLLECTION}/not-a-number")).status_code == 422

    async def test_an_unknown_number_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.get(f"{COLLECTION}/999999")).status_code == 404


class TestDelete:
    async def test_deletes_the_callers_repository(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.delete(f"{COLLECTION}/{repo.id}")

        assert response.status_code == 204
        assert (await client.get(f"{COLLECTION}/{repo.repo_number}")).status_code == 404

    async def test_cannot_delete_another_users_repository(self, client, db_session):
        from sqlalchemy import select

        from app.models.repository import Repository

        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo = await make_repo(db_session, theirs)
        await authenticate(client, mine)

        response = await client.delete(f"{COLLECTION}/{their_repo.id}")

        assert response.status_code == 404
        # Still there.
        result = await db_session.execute(select(Repository).where(Repository.id == their_repo.id))
        assert result.scalar_one_or_none() is not None

    async def test_an_unknown_id_is_not_found(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        response = await client.delete(f"{COLLECTION}/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_a_malformed_id_is_a_validation_error(self, client, db_session):
        await authenticate(client, await make_user(db_session))

        assert (await client.delete(f"{COLLECTION}/not-a-uuid")).status_code == 422


class TestReingest:
    async def test_resets_a_ready_repository(self, client, db_session, dispatched):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status="ready")
        await authenticate(client, user)

        response = await client.put(f"{COLLECTION}/{repo.id}/reingest")

        assert response.status_code == 202
        assert response.json()["repo_id"] == str(repo.id)
        assert len(dispatched) == 1

    async def test_keeps_the_same_id_and_number(self, client, db_session, dispatched):
        from sqlalchemy import select

        from app.models.repository import Repository

        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status="failed")
        original_number = repo.repo_number
        await authenticate(client, user)

        await client.put(f"{COLLECTION}/{repo.id}/reingest")

        result = await db_session.execute(select(Repository).where(Repository.id == repo.id))
        replacement = result.scalar_one_or_none()
        assert replacement is not None
        assert replacement.repo_number == original_number

    async def test_replaces_the_row_so_children_are_cascaded_away(
        self, client, db_session, dispatched
    ):
        """
        Re-ingestion is a delete-and-recreate, so any child row from the previous run
        must be gone rather than merged with the new run's data.
        """
        from sqlalchemy import select

        from app.models.file import File

        user = await make_user(db_session)
        repo, files = await make_ingested_repo(db_session, user)
        await authenticate(client, user)

        await client.put(f"{COLLECTION}/{repo.id}/reingest")

        result = await db_session.execute(select(File).where(File.repository_id == repo.id))
        assert result.scalars().all() == []

    async def test_refuses_while_ingestion_is_in_progress(self, client, db_session, dispatched):
        user = await make_user(db_session)
        # Any status other than ready/failed must be refused. `cloning` is a real value of
        # the repo_status enum, though the enum in the model and the one in the database
        # do not agree on every label.
        repo = await make_repo(db_session, user, status="cloning")
        await authenticate(client, user)

        response = await client.put(f"{COLLECTION}/{repo.id}/reingest")

        assert response.status_code == 400
        assert "cannot be re-ingested" in response.json()["detail"].lower()
        assert dispatched == []

    async def test_cannot_reingest_another_users_repository(self, client, db_session, dispatched):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo = await make_repo(db_session, theirs, status="ready")
        await authenticate(client, mine)

        response = await client.put(f"{COLLECTION}/{their_repo.id}/reingest")

        assert response.status_code == 404
        assert dispatched == []


class TestExport:
    async def test_exports_a_ready_repository_as_text(self, client, db_session):
        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        await authenticate(client, user)

        response = await client.get(f"{COLLECTION}/{repo.id}/export/illume")

        assert response.status_code == 200
        assert response.text

    async def test_the_export_matches_its_golden_file(self, client, db_session, update_golden):
        """
        The export's exact text, frozen.

        Before this the only assertion on the export was the one above -- that it returned
        *something*. Nothing pinned the section names, their order, or the header keys, so
        an additive change (a new section, a reordered header) passed unnoticed. The export
        is a file a user downloads and reads, so its shape is the feature.

        `generated=` is replaced with a placeholder before comparing; see
        `tests/fixtures/golden/__init__.py`. Regenerate with `pytest --update-golden` and
        read the diff before committing it.
        """
        user = await make_user(db_session)
        repo, files = await make_ingested_repo(db_session, user)

        # `@@HOTSPOTS` lists files whose criticality is set and not "safe", and the factory
        # leaves it unset -- so without this the section renders empty and the golden file
        # would pin nothing about how a hotspot line is formatted, `cc=` clause included.
        files[-1].criticality = "critical"

        # Distinct fan-in values so the exporter's `sorted(..., reverse=True)` has no ties
        # to break. The factory gives every file after the first `fan_in=1`, and `sorted` is
        # stable -- so tied files inherit the *database's* return order, which the two
        # unfiltered queries behind it do not pin with an `ORDER BY`. Left tied, this golden
        # would shift on any change of plan that reordered three rows, and the diff would be
        # indistinguishable from a real regression.
        for index, file in enumerate(files):
            file.fan_in = index

        await db_session.commit()

        await authenticate(client, user)

        response = await client.get(f"{COLLECTION}/{repo.id}/export/illume")
        assert response.status_code == 200

        assert_matches_golden("illume_export.txt", response.text, update_golden)

    async def test_cannot_export_another_users_repository(self, client, db_session):
        mine = await make_user(db_session)
        theirs = await make_user(db_session)
        their_repo, _ = await make_ingested_repo(db_session, theirs)
        await authenticate(client, mine)

        response = await client.get(f"{COLLECTION}/{their_repo.id}/export/illume")

        assert response.status_code == 404
