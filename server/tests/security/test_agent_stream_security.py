"""Access control and secrecy for the streaming and replay routes.

The cross-user matrix in ``test_idor.py`` covers the three routes' status codes
for the owner, a stranger, an unknown id and no session. These tests cover what
the matrix cannot: that a stranger's request has no effect, that a run cannot be
reached through the wrong repository, and that no token or key appears in a URL,
an event or a stored step.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AgentRun, AgentStep
from tests.fixtures.agent_run import ScriptedModel, SufficiencyDecider, call, finish, turn
from tests.fixtures.agent_stream import (
    QUESTION,
    AnyModel,
    install,
    make_stranger_repo,
    make_world,
    only_run,
    runs_of,
    runs_url,
    step_rows,
    stream,
    stream_url,
)
from tests.helpers import authenticate

pytestmark = pytest.mark.security

# Fixed rather than random: parametrised ids must be the same in every xdist worker.
ABSENT_RUN = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def no_model_backed_stages(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")


@pytest.fixture
async def world(client, db_session):
    return await make_world(client, db_session)


class TestAnotherUsersRepository:
    async def test_streaming_against_it_is_not_found_and_does_nothing(
        self, app, client, db_session, world
    ):
        stranger, theirs = await make_stranger_repo(db_session)
        model = ScriptedModel([turn(finish("never"))])
        install(app, db_session, model, decider=SufficiencyDecider(1.0))

        response = await client.post(
            stream_url(theirs.repo), json={"question": QUESTION, "preset": "deep_agent"}
        )

        assert response.status_code == 404
        assert model.requests == []
        assert await runs_of(db_session, theirs.repo) == []

    async def test_listing_its_runs_is_not_found(self, client, db_session, world):
        _, theirs = await make_stranger_repo(db_session)

        assert (await client.get(runs_url(theirs.repo))).status_code == 404

    async def test_replaying_its_run_is_not_found(self, client, db_session, world):
        stranger, theirs = await make_stranger_repo(db_session)
        run = AgentRun(
            user_id=stranger.id,
            repository_id=theirs.repo.id,
            question="theirs",
            preset="classic",
            config={},
            config_hash="0" * 64,
            status="done",
            answer="secret answer",
        )
        db_session.add(run)
        await db_session.flush()

        response = await client.get(f"{runs_url(theirs.repo)}/{run.id}")

        assert response.status_code == 404
        assert "secret answer" not in response.text


class TestRunsAreScopedToTheirOwner:
    async def test_a_run_cannot_be_read_through_another_repository_of_the_callers(
        self, app, client, db_session, world
    ):
        from tests.factories import make_repo

        install(app, db_session, AnyModel())
        await stream(client, world.repo, preset="hybrid")
        run = await only_run(db_session, world.repo)
        elsewhere = await make_repo(db_session, world.user, name="elsewhere")

        response = await client.get(f"{runs_url(elsewhere)}/{run.id}")

        assert response.status_code == 404

    async def test_a_run_cannot_be_read_by_another_user_of_the_same_repository_path(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel())
        await stream(client, world.repo, preset="hybrid")
        run = await only_run(db_session, world.repo)
        stranger, _ = await make_stranger_repo(db_session)
        await authenticate(client, stranger)

        response = await client.get(f"{runs_url(world.repo)}/{run.id}")

        assert response.status_code == 404

    async def test_a_strangers_listing_of_my_repository_is_refused(
        self, app, client, db_session, world
    ):
        install(app, db_session, AnyModel())
        await stream(client, world.repo, preset="hybrid")
        stranger, _ = await make_stranger_repo(db_session)
        await authenticate(client, stranger)

        assert (await client.get(runs_url(world.repo))).status_code == 404

    async def test_an_unknown_run_id_is_not_found(self, client, world):
        assert (await client.get(f"{runs_url(world.repo)}/{uuid.uuid4()}")).status_code == 404

    async def test_a_malformed_run_id_is_a_validation_error_not_a_crash(self, client, world):
        assert (await client.get(f"{runs_url(world.repo)}/not-a-uuid")).status_code == 422


class TestNoSession:
    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("POST", "/chat/stream"),
            ("GET", "/agent-runs"),
            ("GET", f"/agent-runs/{ABSENT_RUN}"),
        ],
    )
    async def test_the_middleware_rejects_the_request_before_the_handler(
        self, client, world, method, suffix
    ):
        client.cookies.clear()

        response = await client.request(
            method,
            f"/api/v1/repository/{world.repo.id}{suffix}",
            json={"question": QUESTION} if method == "POST" else None,
        )

        assert response.status_code == 401

    async def test_a_forged_token_is_rejected(self, client, world):
        client.cookies.set("access_token", "not.a.token")

        assert (await client.get(runs_url(world.repo))).status_code == 401


class TestNoSecretsInTheOpen:
    async def test_the_stream_takes_no_token_in_its_url(self, app):
        schema = app.openapi()["paths"]
        for path in (
            "/api/v1/repository/{repo_id}/chat/stream",
            "/api/v1/repository/{repo_id}/agent-runs",
            "/api/v1/repository/{repo_id}/agent-runs/{run_id}",
        ):
            for operation in schema[path].values():
                names = [p["name"].lower() for p in operation.get("parameters", [])]
                assert not [n for n in names if "token" in n or "key" in n or "secret" in n]
                assert all(
                    p["in"] == "path" or p["name"] == "limit"
                    for p in operation.get("parameters", [])
                )

    async def test_a_token_in_the_query_string_is_not_accepted_as_authentication(
        self, client, world
    ):
        token = client.cookies.get("access_token")
        client.cookies.clear()

        response = await client.post(
            f"{stream_url(world.repo)}?token={token}", json={"question": QUESTION}
        )

        assert response.status_code == 401

    async def test_no_event_step_or_row_carries_a_credential(self, app, client, db_session, world):
        model = ScriptedModel(
            [
                turn(call("search_symbols", {"name": "create_user"})),
                turn(finish(f"Done [{world.symbol_key}].")),
            ]
        )
        install(app, db_session, model, decider=SufficiencyDecider(1.0))

        response, events = await stream(client, world.repo, preset="deep_agent")

        run = await only_run(db_session, world.repo)
        token = client.cookies.get("access_token")
        stored = "".join(
            str(row.payload) + str(row.name) + str(row.worker_id)
            for row in await step_rows(db_session, run.id)
        )
        everything = response.text + stored + str(run.config) + str(run.usage) + str(run.error)
        for secret in (token, "sk-user-secret", "sk-stranger-secret"):
            assert secret not in everything
        # The client is shown nothing it did not need: the key is only ever a header upstream.
        assert all("api_key" not in str(event["data"]) for event in events)

    async def test_the_step_tables_hold_only_this_users_rows(self, app, client, db_session, world):
        install(app, db_session, AnyModel())
        await stream(client, world.repo, preset="hybrid")
        run = await only_run(db_session, world.repo)

        owners = (
            (await db_session.execute(select(AgentRun.user_id).where(AgentRun.id == run.id)))
            .scalars()
            .all()
        )
        steps = (
            (await db_session.execute(select(AgentStep.run_id).where(AgentStep.run_id == run.id)))
            .scalars()
            .all()
        )

        assert owners == [world.user.id]
        assert set(steps) == {run.id}
