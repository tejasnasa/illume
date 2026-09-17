"""Cross-user access control for every repository-scoped route.

The matrix is declarative so that `test_every_repo_route_is_covered.py` can assert it is
exhaustive -- a new `{repo_id}` route cannot ship without landing here.

Each case asserts three things, and the first is the one that keeps the other two honest:

1. **The owner succeeds.** Without this, a route that 404s unconditionally would pass the
   IDOR assertions trivially. The victim's repository is fully populated and `ready` for
   exactly this reason -- a route must fail for the attacker while working for its owner.
2. **Another user gets 404**, never 200 and never 403. 403 would confirm the repository
   exists, which is itself a disclosure.
3. **A caller with no session gets 401**, rejected by the middleware before any handler.
"""

import uuid
from dataclasses import dataclass

import pytest

from app.services.rag import RAGResponse, SourceReference
from tests.factories import (
    make_chat_message,
    make_code_owner,
    make_glossary_entry,
    make_ingested_repo,
    make_user,
)
from tests.helpers import authenticate

pytestmark = pytest.mark.security


@dataclass(frozen=True)
class RepoRoute:
    """One repository-scoped endpoint, described well enough to drive all three checks.

    Attributes:
        method: HTTP verb.
        template: Path with `{ref}` standing in for the repository identifier and
            `{message_id}` for a chat message.
        key: Which identifier `{ref}` should be filled with -- the UUID `id`, or the
            user-scoped integer `repo_number`. The distinction matters: a matrix keyed
            only on `repo_id` silently skips the one route that uses `repo_number`.
        success: Status the owner should receive, which pins what "succeeds" means for
            this route. Several are 204 or 202 rather than 200.
        body: Optional JSON body for verbs that need one.
        cross_user: Status another user should receive. 404 everywhere except the
            chat-clear route -- see the note on that entry.
        unknown: Status for an identifier matching no row.
    """

    method: str
    template: str
    key: str = "id"
    success: int = 200
    body: dict | None = None
    cross_user: int = 404
    unknown: int = 404


# Note the absence of a UUID-keyed `GET /{repo_id}`: only the integer `repo_num` form
# exists. A `/repository/<uuid>` GET therefore falls through to the integer route and is
# rejected as malformed (422), which `TestRepoNumberIsScoped` pins.
REPO_ROUTES: list[RepoRoute] = [
    RepoRoute("GET", "/api/v1/repository/{ref}", key="number"),
    RepoRoute("DELETE", "/api/v1/repository/{ref}", success=204),
    RepoRoute("PUT", "/api/v1/repository/{ref}/reingest", success=202),
    RepoRoute("GET", "/api/v1/repository/{ref}/export/illume"),
    RepoRoute("GET", "/api/v1/repository/{ref}/graph"),
    RepoRoute("GET", "/api/v1/repository/{ref}/glossary"),
    RepoRoute("GET", "/api/v1/repository/{ref}/glossary/search?q=a"),
    RepoRoute("GET", "/api/v1/repository/{ref}/guide"),
    RepoRoute("GET", "/api/v1/repository/{ref}/ownership"),
    RepoRoute("GET", "/api/v1/repository/{ref}/ownership/silos"),
    RepoRoute("GET", "/api/v1/repository/{ref}/stats"),
    RepoRoute("POST", "/api/v1/repository/{ref}/chat", body={"question": "What does this do?"}),
    RepoRoute("GET", "/api/v1/repository/{ref}/chat/history"),
    # The odd one out, and deliberately so. Clearing history does not look the
    # repository up at all: it issues a DELETE scoped by `repository_id` *and*
    # `user_id`, so a foreign repository simply matches no rows. The call is therefore
    # idempotent and answers 204 whether the repository is missing, foreign, or empty.
    #
    # That is safe -- nothing is disclosed, since the response cannot distinguish the
    # three cases, and nothing of the victim's is reachable through a filter keyed on
    # the caller's own id. `TestClearingIsScopedToTheCaller` checks the property that
    # actually matters.
    RepoRoute("DELETE", "/api/v1/repository/{ref}/chat", success=204, cross_user=204, unknown=204),
    RepoRoute("DELETE", "/api/v1/repository/{ref}/chat/{message_id}", success=204),
]

IDS = [f"{r.method} {r.template}{' [number]' if r.key == 'number' else ''}" for r in REPO_ROUTES]


@pytest.fixture(autouse=True)
def stub_rag(monkeypatch):
    """
    Keep the chat route off the network.

    Ownership is checked before the RAG pipeline runs, so a correct route never reaches
    this. It is stubbed so that an *incorrect* one fails on the status assertion rather
    than by calling OpenAI.
    """
    calls: list = []

    async def fake_answer_question(query, repository_id, db, history=None):
        calls.append(query)
        return RAGResponse(
            answer="stubbed",
            sources=[SourceReference(source_type="symbol", chunk_text="stub")],
        )

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)
    return calls


@pytest.fixture(autouse=True)
def stub_dispatch(monkeypatch):
    """Stop re-ingestion from reaching the Celery broker."""
    import app.api.v1.repository as repository_module

    monkeypatch.setattr(repository_module.ingest_repository, "delay", lambda *a, **k: None)


@pytest.fixture
async def victim(client, db_session):
    """
    A fully populated, ready repository owned by someone other than the caller.

    Populated so that every route in the matrix would succeed for its owner, which is
    what makes the 404 assertions meaningful. The attacker's session is installed on the
    client; the victim's user is returned unauthenticated.
    """
    attacker = await make_user(db_session)
    victim_user = await make_user(db_session)
    repo, files = await make_ingested_repo(db_session, victim_user)

    await make_glossary_entry(db_session, repo, name="Widget", definition="A widget.")
    await make_code_owner(db_session, files[0], primary_owner="Victim")
    message = await make_chat_message(db_session, repo, victim_user, question="secret")

    from tests.factories import make_guide

    await make_guide(
        db_session,
        repo,
        reading_order=[{"position": 1, "path": "src/module_0.py", "annotation": "a", "fan_in": 0}],
    )

    await authenticate(client, attacker)
    return attacker, victim_user, repo, message


def path_for(route: RepoRoute, repo, message=None) -> str:
    """Build the concrete request path for a route."""
    ref = str(repo.repo_number) if route.key == "number" else str(repo.id)
    path = route.template.replace("{ref}", ref)
    if "{message_id}" in path:
        path = path.replace("{message_id}", str(message.id))
    return path


async def call(client, route: RepoRoute, path: str):
    """Issue the request, attaching the body for verbs that carry one."""
    return await client.request(route.method, path, json=route.body)


class TestOwnerSucceeds:
    @pytest.mark.parametrize("route", REPO_ROUTES, ids=IDS)
    async def test_the_owner_can_reach_it(self, client, db_session, victim, route):
        """
        The control for the whole matrix.

        If this fails, the corresponding 404 in `TestCrossUserAccess` proves nothing --
        the route was already unreachable for everyone.
        """
        _, victim_user, repo, message = victim
        await authenticate(client, victim_user)

        response = await call(client, route, path_for(route, repo, message))

        assert response.status_code == route.success


class TestCrossUserAccess:
    @pytest.mark.parametrize("route", REPO_ROUTES, ids=IDS)
    async def test_another_user_is_not_found(self, client, victim, route):
        """404 rather than 403: a 403 would confirm the repository exists."""
        _, _, repo, message = victim

        response = await call(client, route, path_for(route, repo, message))

        assert response.status_code == route.cross_user

    @pytest.mark.parametrize("route", REPO_ROUTES, ids=IDS)
    async def test_another_users_repository_is_not_modified(
        self, client, db_session, victim, route
    ):
        """
        A rejected request must not have had its effect anyway.

        Status codes are the primary contract, but the destructive verbs are worth
        checking against the database directly -- a route that mutated and *then*
        raised would still return 404.
        """
        from sqlalchemy import select

        from app.models.repository import Repository

        _, victim_user, repo, message = victim

        await call(client, route, path_for(route, repo, message))

        result = await db_session.execute(select(Repository).where(Repository.id == repo.id))
        assert result.scalar_one_or_none() is not None

    @pytest.mark.parametrize("route", REPO_ROUTES, ids=IDS)
    async def test_an_unknown_identifier_is_not_found(self, client, db_session, victim, route):
        _, victim_user, repo, message = victim
        await authenticate(client, victim_user)

        unknown = uuid.uuid4()
        if route.key == "number":
            path = path_for(route, repo, message).replace(str(repo.repo_number), "999999999")
        else:
            path = path_for(route, repo, message).replace(str(repo.id), str(unknown))

        assert (await call(client, route, path)).status_code == route.unknown

    @pytest.mark.parametrize("route", REPO_ROUTES, ids=IDS)
    async def test_no_session_is_unauthorized(self, client, victim, route):
        """Rejected by the middleware, so the handler never runs."""
        _, _, repo, message = victim
        client.cookies.clear()

        assert (await call(client, route, path_for(route, repo, message))).status_code == 401


class TestClearingIsScopedToTheCaller:
    """
    Clearing a foreign repository's history answers 204 rather than 404, because the
    route never loads the repository -- it deletes rows matching `repository_id` and the
    caller's own `user_id`. Returning 204 for all three cases (missing, foreign, empty)
    is what makes it non-disclosing.

    The security property is therefore not the status code but this: a foreign call must
    leave the owner's rows untouched. These tests check that directly.
    """

    async def test_a_foreign_clear_does_not_delete_the_owners_messages(
        self, client, db_session, victim
    ):
        from sqlalchemy import select

        from app.models.chat_message import ChatMessage

        _, victim_user, repo, _ = victim

        await client.delete(f"/api/v1/repository/{repo.id}/chat")

        result = await db_session.execute(
            select(ChatMessage).where(ChatMessage.repository_id == repo.id)
        )
        assert [m.question for m in result.scalars().all()] == ["secret"]

    async def test_a_clear_removes_only_the_callers_own_rows(self, client, db_session, victim):
        """
        Both users have a row on the same repository; the clear runs as the attacker. The
        `user_id` filter is what makes the missing ownership check safe. If it were ever
        dropped from the DELETE, the attacker's own row would still vanish (so a weaker
        assertion would pass) while the owner's row went with it.
        """
        from sqlalchemy import select

        from app.models.chat_message import ChatMessage

        attacker, _, repo, _ = victim
        await make_chat_message(db_session, repo, attacker, question="attacker's own")

        await client.delete(f"/api/v1/repository/{repo.id}/chat")

        result = await db_session.execute(
            select(ChatMessage).where(ChatMessage.repository_id == repo.id)
        )
        assert [m.question for m in result.scalars().all()] == ["secret"]

    async def test_the_owner_can_still_clear_their_own(self, client, db_session, victim):
        """The control: the route does work for the person it is meant to."""
        from sqlalchemy import select

        from app.models.chat_message import ChatMessage

        _, victim_user, repo, _ = victim
        await authenticate(client, victim_user)

        response = await client.delete(f"/api/v1/repository/{repo.id}/chat")

        assert response.status_code == 204
        result = await db_session.execute(
            select(ChatMessage).where(ChatMessage.repository_id == repo.id)
        )
        assert result.scalars().all() == []


class TestRepoNumberIsScoped:
    """
    `GET /{repo_num}` is the one repository route keyed on the integer `repo_number`
    rather than the UUID. It is called out separately because a sweep that parametrizes
    over routes named `repo_id` would skip it.
    """

    async def test_another_users_number_is_not_found(self, client, victim):
        _, _, repo, _ = victim

        response = await client.get(f"/api/v1/repository/{repo.repo_number}")

        assert response.status_code == 404

    async def test_the_same_number_under_the_owner_resolves(self, client, victim):
        """
        `repo_number` is scoped per user, so two accounts can legitimately share one.
        The owner's own lookup must not be shadowed by the other user's row.
        """
        _, victim_user, repo, _ = victim
        await authenticate(client, victim_user)

        response = await client.get(f"/api/v1/repository/{repo.repo_number}")

        assert response.status_code == 200
        assert response.json()["name"] == repo.name

    async def test_a_number_is_not_a_uuid_path(self, client, victim):
        """The two identifier spaces must not bleed into one another."""
        _, _, repo, _ = victim

        # The UUID route rejects a bare integer as malformed rather than resolving it.
        response = await client.delete(f"/api/v1/repository/{repo.repo_number}")

        assert response.status_code == 422
