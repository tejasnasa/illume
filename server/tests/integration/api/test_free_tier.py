"""Quota gates that lock down the free tier at the five entry points.

Eight behaviours pin the difference between a byok user and a keyless one:
the create, reingest, auto-update, and sync-now routes admit byok users
and refuse keyless ones; a keyless ``sync_repository.apply`` returns
without writing; chat charges the free tier once per real answer and not
for the no-context fallback; chat returns 402 on the sixth question; chat
maps provider errors to 502 without consuming a unit; and with
``AI_API_KEY`` empty the first chat call already 402s.

The byok path is exercised here rather than in the route's own test module
because the gate is **additive**: it changes nothing for users with a key,
and the existing suite pins that no-op. What this module pins is the
*difference* between keyless and byok behaviour, which is precisely the
property a regression would silently flip.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.repository import Repository
from app.models.user import User
from app.services.entitlements import FREE_CHAT_MESSAGES, claim_free_ingestion
from app.services.rag import RAGResponse, SourceReference
from app.tasks.sync import sync_repository
from tests.conftest import TEST_SYNC_DB_URL
from tests.factories import make_repo, make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

COLLECTION = "/api/v1/repository"
GITHUB_URL = "https://github.com/example/cool-project"


def chat_url(repo) -> str:
    return f"/api/v1/repository/{repo.id}/chat"


def symbol_source() -> SourceReference:
    return SourceReference(
        source_type="symbol",
        chunk_text="def f(): pass",
        file_path="src/module_0.py",
        symbol_name="func_0",
        start_line=1,
        end_line=10,
    )


@pytest.fixture
def dispatched(monkeypatch):
    """Replace ``ingest_repository.delay`` with a recorder.

    Matches the fixture shape in :mod:`test_repository_api` so the test
    remains a route-level contract check, not a Celery integration.
    """
    calls: list[tuple] = []

    def fake_delay(repo_id, token, **kwargs):
        calls.append((repo_id, token, kwargs))

    import app.api.v1.repository as repository_module

    monkeypatch.setattr(repository_module.ingest_repository, "delay", fake_delay)
    return calls


@pytest.fixture
def free_tier_settings(monkeypatch):
    """Pin ``settings.AI_API_KEY = ''`` so the free tier is unavailable.

    Other test modules use ``monkeypatch.setattr(settings, "AI_API_KEY", ...)``
    to control the server's free-tier key on a per-test basis. That
    monkeypatch *should* revert at teardown, but in practice the
    mutation leaks into later tests when collection order shifts --
    running this test file alone is fine, but alongside the byok
    threading module the leaked value would silently re-enable the
    free tier for the assertions below. Pinning here makes the
    invariant explicit and independent of run order.
    """
    from app.services import llm_config

    stub = SimpleNamespace(AI_API_KEY="", AI_MODEL="", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)
    return stub


@pytest.fixture
def server_free_tier_enabled(monkeypatch):
    """Pin ``settings.AI_API_KEY = 'sk-server'`` so the free tier is reachable.

    The matching "free tier unavailable" fixture sets the same value to
    empty; this fixture's complement is what lets a keyless user be
    admitted to the chat route at all. The gate's behaviour on the
    *admitted* branch (charge-after, 402-on-cap, 502-mapping) can only
    be observed when the gate admits the call.
    """
    from app.services import llm_config

    stub = SimpleNamespace(AI_API_KEY="sk-server", AI_MODEL="deepseek-flash", AI_BASE_URL="")
    monkeypatch.setattr(llm_config, "settings", stub)
    return stub


@pytest.fixture
def rag(monkeypatch):
    """Replace ``answer_question`` with a recorder that returns ``generated=True``.

    The route's free-tier charge reads ``RAGResponse.generated`` -- the
    recorder yields the ``generated=True`` shape so the assertion can pin
    "an LLM call really did happen" without going through the real
    embedding + retrieval pipeline.
    """
    calls: list[dict] = []

    async def fake_answer_question(query, repository_id, db, history=None, *, llm=None):
        calls.append(
            {"query": query, "repository_id": repository_id, "history": history, "llm": llm}
        )
        return RAGResponse(answer=f"Answer to: {query}", sources=[symbol_source()], generated=True)

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)
    return calls


@pytest.fixture
def rag_no_context(monkeypatch):
    """Replace ``answer_question`` to return the no-context fallback.

    The ``generated=False`` flag is what makes the free-tier charge
    *not* increment the counter; this fixture lets the test pin that
    behaviour without exercising the embedding path.
    """
    calls: list[dict] = []

    async def fake_answer_question(query, repository_id, db, history=None, *, llm=None):
        calls.append(
            {"query": query, "repository_id": repository_id, "history": history, "llm": llm}
        )
        return RAGResponse(
            answer="No relevant code was found in this repository for your question.",
            sources=[],
            generated=False,
        )

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)
    return calls


def _auth_error_response():
    """A minimal ``httpx.Response`` that the OpenAI SDK's exception classes accept.

    The SDK's error classes all require a ``response`` (and ``request``)
    attribute. ``httpx.Client`` does not let us build one without a real
    network round-trip, but ``Response`` itself is a public constructor
    when given a ``Request`` and a status code.
    """
    import httpx

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return httpx.Response(401, request=request)


def _connection_error_request():
    """An ``httpx.Request`` that ``APIConnectionError`` can carry.

    Connection errors attach to a ``Request`` rather than a ``Response``;
    ``APIConnectionError(message, request=req)`` is the supported shape.
    """
    import httpx

    return httpx.Request("POST", "https://api.openai.com/v1/responses")


@pytest.fixture
def rag_provider_error(monkeypatch):
    """Replace ``answer_question`` to raise ``AuthenticationError``.

    The chat route catches the SDK's auth error class and surfaces it as a
    502; the test pins both the status code and "the failed call did not
    charge a free-tier message".
    """
    calls: list[dict] = []

    async def fake_answer_question(query, repository_id, db, history=None, *, llm=None):
        calls.append({"query": query, "repository_id": repository_id})
        raise AuthenticationError("invalid api key", response=_auth_error_response(), body=None)

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)
    return calls


async def _make_byok_user(db_session) -> User:
    """A user with the minimal BYOK fields populated.

    Sets ``ai_provider='openai'`` and ``ai_api_key='sk-byok-test'`` via
    the factory. The routes only check ``LLMConfig.from_user`` -- which
    short-circuits on an empty provider string -- so populating the key
    is enough to flip the gate to the admitted branch.
    """
    return await make_user(db_session, ai_api_key="sk-byok-test")


async def _ingested_ready_repo(client, db_session, *, with_key: bool = False) -> tuple:
    """Create a user with a ready repository, signed in.

    ``with_key=True`` toggles the BYOK shape (sets
    ``ai_provider/api_key/model``); ``False`` produces the keyless free
    tier case. The same fixture drives both since the only differentiator
    is whether the user holds a credential.
    """
    if with_key:
        user = await _make_byok_user(db_session)
    else:
        user = await make_user(db_session)
    repo = await make_repo(db_session, user)
    await authenticate(client, user)
    return user, repo


async def _user_counter(db_session, user_id: uuid.UUID) -> int:
    """Read the user's chat counter from a fresh statement.

    Uses ``populate_existing=True`` so the session's identity map does
    not return a stale cached User -- with ``expire_on_commit=False``
    on the test session, the cached user would otherwise keep the
    pre-charge counter and the assertion would see ``0`` after a
    successful charge.
    """
    stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    stored = (await db_session.execute(stmt)).scalar_one()
    return stored.free_chat_messages_used


class TestCreateRepository:
    """``POST /api/v1/repository`` -- the one route that admits keyless users."""

    async def test_byok_user_admitted(self, client, db_session, dispatched):
        """A user with a stored key is admitted immediately; no allowance consumed."""
        user = await _make_byok_user(db_session)
        await authenticate(client, user)

        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        assert response.status_code == 202

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.free_ingest_used is False

    async def test_keyless_user_admitted_when_allowance_remains(
        self, client, db_session, dispatched
    ):
        """A keyless user with ``free_ingest_used=False`` succeeds and burns the allowance."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        assert response.status_code == 202

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.free_ingest_used is True

    async def test_keyless_user_402_when_allowance_is_gone(self, client, db_session, dispatched):
        """A keyless user whose allowance has already been used gets 402.

        The conftest's ``db_session`` wraps an outer transaction that
        never commits, so a sync ``claim_free_ingestion`` invoked from
        another engine cannot see a user inserted through ``make_user``
        -- the rows are uncommitted to the database. The test mirrors
        :mod:`tests.integration.services.test_entitlements` and inserts
        the user through a **sync** engine session so the claim is
        operating on a row that has been committed.
        """
        import uuid as _uuid

        from app.core.security import hash_password
        from app.models.user import User as UserModel

        engine = create_engine(TEST_SYNC_DB_URL)
        Session = sessionmaker(bind=engine)
        sync = Session()
        try:
            user = UserModel(
                id=_uuid.uuid4(),
                email=f"allowance-gone-{_uuid.uuid4().hex[:8]}@example.test",
                name="Allowance Gone Test User",
                password=hash_password("correct horse battery staple"),
            )
            sync.add(user)
            sync.commit()
            user_id = user.id

            assert claim_free_ingestion(sync, user_id) is True
            sync.commit()

            # Authenticate the same user via the async test client.
            from app.core.security import create_access_token

            client.cookies.set("access_token", create_access_token(subject=str(user_id)))
        finally:
            sync.close()
            engine.dispose()

        response = await client.post(COLLECTION, json={"github_url": GITHUB_URL})

        assert response.status_code == 402
        assert "API key" in response.json()["detail"]
        # No dispatch: the gate refuses before the route reaches it.
        assert dispatched == []


class TestReingestRequiresKey:
    """``PUT /{repo_id}/reingest`` -- never free."""

    async def test_byok_user_admitted(self, client, db_session, dispatched):
        user = await _make_byok_user(db_session)
        repo = await make_repo(db_session, user, status="ready")
        await authenticate(client, user)

        response = await client.put(f"{COLLECTION}/{repo.id}/reingest")

        assert response.status_code == 202

    async def test_keyless_user_402(self, client, db_session, dispatched):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user, status="ready")
        await authenticate(client, user)

        response = await client.put(f"{COLLECTION}/{repo.id}/reingest")

        assert response.status_code == 402
        assert "API key" in response.json()["detail"]
        assert dispatched == []


class TestAutoUpdatePatchRequiresKey:
    """``PATCH /{repo_id}/auto-update`` -- never free."""

    async def test_byok_user_admitted(self, client, db_session):
        user = await _make_byok_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.patch(f"{COLLECTION}/{repo.id}/auto-update", json={"enabled": True})

        assert response.status_code == 200

    async def test_keyless_user_402(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.patch(f"{COLLECTION}/{repo.id}/auto-update", json={"enabled": True})

        assert response.status_code == 402


class TestSyncNowRequiresKey:
    """``POST /{repo_id}/sync`` -- never free."""

    async def test_byok_user_admitted(self, client, db_session):
        user = await _make_byok_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.post(f"{COLLECTION}/{repo.id}/sync")

        assert response.status_code == 202

    async def test_keyless_user_402(self, client, db_session):
        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.post(f"{COLLECTION}/{repo.id}/sync")

        assert response.status_code == 402


class TestSyncRepositoryBackstop:
    """``sync_repository`` -- the task-level gate that closes the swept-sync door."""

    async def test_keyless_owner_skips_without_writing(self):
        """A swept sync against a keyless owner returns ``None`` and leaves the row alone.

        The route layer already refuses manual sync-now, but the sweep
        has no route to claim anything. The task backstop is what
        closes that door. We stamp ``ingested_commit_sha`` to head the
        short-circuit that fires *before* the backstop; if the backstop
        is wired correctly it returns ``None`` without touching the row.

        The task reads through a sync session, so we write through a
        sync engine directly rather than the ``db_session`` async
        fixture -- otherwise the worker would not see the row.
        """
        import uuid as _uuid

        from app.core.security import hash_password
        from app.models.user import User as UserModel

        engine = create_engine(TEST_SYNC_DB_URL)
        Session = sessionmaker(bind=engine)
        sync = Session()
        try:
            user = UserModel(
                id=_uuid.uuid4(),
                email=f"sync-backstop-{_uuid.uuid4().hex[:8]}@example.test",
                name="Sync Backstop Test User",
                password=hash_password("correct horse battery staple"),
            )
            sync.add(user)
            sync.commit()

            repo = Repository(
                id=_uuid.uuid4(),
                user_id=user.id,
                github_url="https://github.com/example/sync-backstop",
                name="sync-backstop",
                status="ready",
                auto_update_enabled=False,
                auto_update_interval_hours=6,
                ingested_branch="main",
                ingested_commit_sha="a" * 40,
            )
            sync.add(repo)
            sync.commit()

            try:
                result = sync_repository.apply(args=[str(repo.id), None])
                _ = result

                # Refresh the row through a fresh session and confirm the
                # watermark survived intact -- the backstop's defining
                # property. The ``sync_status`` stays at whatever the
                # fixture left it (the backstop fires before ``_take_lease``).
                sync.commit()  # release any side-effect savepoints from the task
                row = sync.query(Repository).filter(Repository.id == repo.id).one()
                assert row.ingested_commit_sha == "a" * 40
            finally:
                # Teardown
                sync.query(Repository).filter(Repository.id == repo.id).delete()
                sync.query(UserModel).filter(UserModel.id == user.id).delete()
                sync.commit()
        finally:
            sync.close()
            engine.dispose()


class TestChatQuotas:
    """``POST /{repo_id}/chat`` -- quota + 502 mapping + charge-after.

    Each test forces the server-side free-tier key to empty so a
    keyless user lands on the no-credential branch. Without that pin,
    a separate test module that monkey-patches ``settings.AI_API_KEY``
    could leak a value into this module's run and silently re-enable
    the server fallback (a keyless user would then be admitted on the
    server key and the 402 gate would never fire).
    """

    async def test_byok_user_bypasses_the_counter(
        self, client, db_session, rag, free_tier_settings
    ):
        """A byok user is admitted without consulting ``free_chat_messages_used``."""
        user, repo = await _ingested_ready_repo(client, db_session, with_key=True)

        # The counter starts at zero; if the gate accidentally consulted
        # it for a byok user the test would either 402 (count at zero)
        # or charge indefinitely (count-driven increment). One answered
        # question, counter still at zero, is the exact invariant.
        response = await client.post(chat_url(repo), json={"question": "What is this?"})

        assert response.status_code == 200
        assert await _user_counter(db_session, user.id) == 0

    async def test_keyless_user_is_charged_once_per_answered_question(
        self, client, db_session, rag, server_free_tier_enabled
    ):
        """Each generated answer increments the counter by exactly one."""
        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)

        for expected in range(1, FREE_CHAT_MESSAGES + 1):
            response = await client.post(chat_url(repo), json={"question": f"q{expected}"})
            assert response.status_code == 200
            assert await _user_counter(db_session, user.id) == expected

    async def test_keyless_user_is_not_charged_for_no_context_fallback(
        self, client, db_session, rag_no_context, server_free_tier_enabled
    ):
        """The ``generated=False`` no-context response does not consume a unit."""
        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)

        response = await client.post(chat_url(repo), json={"question": "anything"})

        assert response.status_code == 200
        assert "No relevant code" in response.json()["answer"]
        assert await _user_counter(db_session, user.id) == 0

    async def test_keyless_user_gets_402_on_the_sixth_question(
        self, client, db_session, rag, server_free_tier_enabled
    ):
        """The first ``FREE_CHAT_MESSAGES`` calls succeed; the (N+1)th returns 402."""
        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)

        for _ in range(FREE_CHAT_MESSAGES):
            response = await client.post(chat_url(repo), json={"question": "q"})
            assert response.status_code == 200

        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 402
        assert "free chat" in response.json()["detail"].lower()
        assert await _user_counter(db_session, user.id) == FREE_CHAT_MESSAGES

    async def test_provider_auth_error_maps_to_502_without_charging(
        self, client, db_session, rag_provider_error, server_free_tier_enabled
    ):
        """An OpenAI AuthenticationError becomes a 502; the failed call does not consume a unit."""
        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)

        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 502
        assert "Provider rejected" in response.json()["detail"]
        assert await _user_counter(db_session, user.id) == 0

    async def test_provider_connection_error_maps_to_502(
        self, client, db_session, monkeypatch, server_free_tier_enabled
    ):
        """An ``APIConnectionError`` from the provider also surfaces as 502."""

        class _BoomRag:
            async def __call__(self, *args, **kwargs):
                raise APIConnectionError(request=_connection_error_request())

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", _BoomRag())

        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)
        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 502
        assert "reach" in response.json()["detail"].lower()

    async def test_provider_timeout_maps_to_502(
        self, client, db_session, monkeypatch, server_free_tier_enabled
    ):
        """An ``APITimeoutError`` from the provider becomes a 502."""

        class _BoomRag:
            async def __call__(self, *args, **kwargs):
                raise APITimeoutError(request=_connection_error_request())

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", _BoomRag())

        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)
        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 502
        assert "reach" in response.json()["detail"].lower()

    async def test_provider_status_error_maps_to_502(
        self, client, db_session, monkeypatch, server_free_tier_enabled
    ):
        """Any other SDK status error becomes a 502 carrying the provider's message."""

        class _BoomRag:
            async def __call__(self, *args, **kwargs):
                err = APIStatusError("rate limited", response=_auth_error_response(), body=None)
                raise err

        import app.api.v1.chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", _BoomRag())

        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)
        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 502
        assert "returned an error" in response.json()["detail"].lower()

    async def test_with_server_key_empty_free_tier_is_unavailable(
        self, client, db_session, free_tier_settings
    ):
        """
        The conftest does **not** set ``AI_API_KEY``, so ``server_default``
        is ``None`` and a keyless user with no allowance gets 402 on the
        very first request. This is the most pessimistic end of the free
        tier -- the operator's deployment never configured it.

        The :func:`free_tier_settings` fixture is what enforces the
        empty ``AI_API_KEY``: another test module runs
        ``monkeypatch.setattr(settings, "AI_API_KEY", ...)``, and that
        patch can leak across the loop boundary in the same xdist
        worker, silently making the fallback route available.
        """
        user, repo = await _ingested_ready_repo(client, db_session, with_key=False)

        # Counter at zero means a server-keyed free user would have been
        # admitted; only the absence of a server key turns it into 402.
        user.free_chat_messages_used = 0
        await db_session.flush()

        response = await client.post(chat_url(repo), json={"question": "q"})

        assert response.status_code == 402
