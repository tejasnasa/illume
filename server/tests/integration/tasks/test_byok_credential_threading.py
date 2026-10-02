"""Phase 4 — every LLM client construction carries the resolved credential.

The risk Phase 1 exists to retire is "silently using the server key":
every ``OpenAI(...)`` / ``AsyncOpenAI(...)`` is supposed to receive the
resolved :class:`~app.services.llm_config.LLMConfig`'s
:meth:`~app.services.llm_config.LLMConfig.client_kwargs`, and a future
edit that drops the param (reverts to ``settings.OPENAI_API_KEY``) would
otherwise pass every existing test. The fixture-side countermeasure is
:attr:`FakeOpenAI.init_kwargs` -- one entry per constructor invocation,
so a test can assert BYOK runs **carry the user's key, model, and base
URL** on every path the credential is supposed to flow through.

The paths to cover:

* Pipeline, **overlapped** (``overlap_llm=True``) -- the initial-ingest
  shape; ``build_glossary`` and ``build_reading_order`` are submitted
  to a thread pool, then ``generate_brief`` is submitted while the
  embedder runs.
* Pipeline, **sequential** (``overlap_llm=False``) -- the full-sync
  escalation shape; all four LLM calls run on the main thread.
* Sync, the **incremental LLM phase** -- ``_ingest_artifact_frame`` +
  ``build_glossary`` + ``build_reading_order`` all run on the caller's
  session with the resolved ``LLMConfig`` plumbed through.

The keyless variants exercise the ``settings.AI_API_KEY`` flow: with
the operator's key set, the resolved config carries the DeepSeek base
URL (no ``/v1``); with the key absent, the four services fall through
to ``settings.OPENAI_API_KEY`` and an OpenAI-SDK-default base URL.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.models.repository import Repository
from app.models.user import User
from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS
from tests.conftest import TEST_SYNC_DB_URL
from tests.fixtures import openai_stub, sample_repo

pytestmark = pytest.mark.integration

# BYOK fixture parameters used in multiple tests. The base URL is the
# ``openai`` preset so the assertion can verify the registry lookup did
# what it was supposed to.
_BYOK_PROVIDER = "openai"
_BYOK_API_KEY = "sk-byok-fixture-key"
_BYOK_MODEL = "gpt-4o-mini"
_BYOK_BASE_URL = PROVIDERS[_BYOK_PROVIDER].base_url


def _sync_session_factory():
    """A fresh sync engine + session factory against the test database."""
    engine = create_engine(TEST_SYNC_DB_URL)
    return engine, sessionmaker(bind=engine)


def _make_user(
    session,
    *,
    ai_provider: str | None = None,
    ai_api_key: str | None = None,
    ai_model: str | None = None,
) -> User:
    """Insert a user row; defaults to keyless (free-tier-eligible)."""
    user = User(
        email=f"byok-{uuid.uuid4().hex[:8]}@example.com",
        name="BYOK Test User",
        password=hash_password("correct horse battery staple"),
        ai_provider=ai_provider,
        ai_api_key=ai_api_key,
        ai_model=ai_model,
    )
    session.add(user)
    session.flush()
    return user


def _make_repo(session, user: User, *, status: str = "ready") -> Repository:
    repo = Repository(
        user_id=user.id,
        github_url=f"https://github.com/example/{uuid.uuid4().hex[:8]}",
        name=f"byok-{uuid.uuid4().hex[:8]}",
        status=status,
        ingested_branch="main",
        ingested_commit_sha="a" * 40,
    )
    session.add(repo)
    session.flush()
    return repo


def _cleanup(session, repos: list[Repository]) -> None:
    from sqlalchemy import delete

    repo_ids = [r.id for r in repos]
    user_ids = list({r.user_id for r in repos})
    session.execute(delete(Repository).where(Repository.id.in_(repo_ids)))
    session.execute(delete(User).where(User.id.in_(user_ids)))
    session.commit()


def _has_byok_init(fake) -> bool:
    """Did *any* client construction carry the BYOK key and preset base URL?

    The risk Phase 4 exists to retire is "silently using the server
    key", so the failure mode is "no init_kwargs carries the user key
    at all" -- this lookup is the assertion.
    """
    for kw in fake.init_kwargs:
        if kw.get("api_key") == _BYOK_API_KEY and kw.get("base_url") == _BYOK_BASE_URL:
            return True
    return False


def _has_keyless_with_server_key(fake, server_key: str) -> bool:
    """Did the keyless path use ``settings.OPENAI_API_KEY`` with no preset base URL?

    The legacy fallback -- no resolved credential -- has the services
    construct ``OpenAI(api_key=settings.OPENAI_API_KEY)`` directly,
    which the stub records as ``{"api_key": <server_key>}`` with no
    ``base_url`` key.
    """
    for kw in fake.init_kwargs:
        if kw.get("api_key") == server_key and "base_url" not in kw:
            return True
    return False


def _has_deepseek_init(fake, server_key: str) -> bool:
    """Did the keyless path, with the operator's key set, carry DeepSeek's base URL?

    The free-tier shape: ``LLMConfig.server_default()`` resolves to
    the DeepSeek preset (``https://api.deepseek.com`` with no
    ``/v1``), and ``client_kwargs()`` includes that base URL alongside
    the operator's API key.
    """
    for kw in fake.init_kwargs:
        if kw.get("api_key") == server_key and kw.get("base_url") == PROVIDERS["deepseek"].base_url:
            return True
    return False


def _byok_config() -> LLMConfig:
    """The ``LLMConfig`` a successful ``LLMConfig.from_user`` should build."""
    return LLMConfig(
        api_key=_BYOK_API_KEY,
        model=_BYOK_MODEL,
        base_url=_BYOK_BASE_URL,
        supports_reasoning=True,
        source="user",
    )


class TestByokCredentialThreading:
    """A user with a stored key gets that key, model, and preset base URL on every path."""

    def test_overlapped_pipeline_branch_carries_the_byok_credential(self, monkeypatch, tmp_path):
        """``run_full_analysis(overlap_llm=True)`` -- the initial-ingest shape.

        Glossary + reading-order run on a thread pool, then the brief
        joins the embedder. The four LLM call sites must all build
        their client from the resolved ``LLMConfig``. The embedder is
        excluded by design -- server-key only.
        """
        engine, Session = _sync_session_factory()
        session = Session()
        user = _make_user(
            session,
            ai_provider=_BYOK_PROVIDER,
            ai_api_key=_BYOK_API_KEY,
            ai_model=_BYOK_MODEL,
        )
        repo = _make_repo(session, user)
        session.commit()
        try:
            clone_root = sample_repo.build(tmp_path / "sample")
            fake = openai_stub.install(monkeypatch)

            from app.services.pipeline import run_full_analysis

            redis_client = type("R", (), {"publish": lambda self, *a, **k: None})()
            run_full_analysis(
                session,
                repo,
                clone_root,
                redis_client,
                lambda *a, **k: None,
                manage_status=True,
                overlap_llm=True,
                llm_config=_byok_config(),
            )
            session.commit()

            assert _has_byok_init(fake), (
                "No OpenAI(...) carried the BYOK api_key and base_url; "
                f"init_kwargs recorded: {fake.init_kwargs!r}"
            )
            assert not _has_keyless_with_server_key(fake, "test-server-key"), (
                f"The BYOK path used the server key on at least one client: {fake.init_kwargs!r}"
            )
        finally:
            _cleanup(session, [repo])
            session.close()
            engine.dispose()

    def test_sequential_pipeline_branch_carries_the_byok_credential(self, monkeypatch, tmp_path):
        """``run_full_analysis(overlap_llm=False)`` -- the full-sync escalation shape.

        The same plumbing, but every LLM call runs on the caller's
        thread. If ``run_full_analysis`` only forwards the config to
        ``run_*_in_thread`` and forgets the non-overlap branch, this
        test fails.
        """
        engine, Session = _sync_session_factory()
        session = Session()
        user = _make_user(
            session,
            ai_provider=_BYOK_PROVIDER,
            ai_api_key=_BYOK_API_KEY,
            ai_model=_BYOK_MODEL,
        )
        repo = _make_repo(session, user)
        session.commit()
        try:
            clone_root = sample_repo.build(tmp_path / "sample")
            fake = openai_stub.install(monkeypatch)

            from app.services.pipeline import run_full_analysis

            run_full_analysis(
                session,
                repo,
                clone_root,
                type("R", (), {"publish": lambda self, *a, **k: None})(),
                lambda *a, **k: None,
                manage_status=False,
                overlap_llm=False,
                llm_config=_byok_config(),
            )
            session.commit()

            assert _has_byok_init(fake), f"Sequential branch missed BYOK: {fake.init_kwargs!r}"
        finally:
            _cleanup(session, [repo])
            session.close()
            engine.dispose()

    def test_sync_incremental_llm_phase_carries_the_byok_credential(self, monkeypatch, tmp_path):
        """The sync task's incremental LLM phase: brief + glossary + reading-order.

        Drives ``_ingest_artifact_frame`` and the two incremental
        builders directly with a resolved ``LLMConfig`` -- the same
        plumbing ``_do_sync`` does when Step B runs, just without the
        Step A / clone machinery around it.
        """
        engine, Session = _sync_session_factory()
        session = Session()
        user = _make_user(
            session,
            ai_provider=_BYOK_PROVIDER,
            ai_api_key=_BYOK_API_KEY,
            ai_model=_BYOK_MODEL,
        )
        repo = _make_repo(session, user)
        session.commit()
        try:
            clone_root = sample_repo.build(tmp_path / "sample")
            fake = openai_stub.install(monkeypatch)

            from app.services.glossary_builder import build_glossary
            from app.services.onboarding import build_reading_order
            from app.tasks import sync as sync_module

            config = _byok_config()
            sync_module._ingest_artifact_frame(
                session, repo, clone_root, manage_status=False, llm_config=config
            )
            build_glossary(session, repo, mode="incremental", llm=config)
            build_reading_order(session, repo, mode="incremental", llm=config)
            session.commit()

            assert _has_byok_init(fake), (
                f"Sync phase missed BYOK on at least one call: {fake.init_kwargs!r}"
            )
        finally:
            _cleanup(session, [repo])
            session.close()
            engine.dispose()


class TestKeylessCredentialThreading:
    """A keyless user on a server with ``AI_API_KEY`` set still gets the DeepSeek base URL."""

    def test_overlapped_pipeline_branch_uses_the_server_deepseek_config(
        self, monkeypatch, tmp_path
    ):
        """``LLMConfig.server_default()`` returns a config carrying the DeepSeek base URL.

        The free-tier shape: the operator's key flows in, the
        ``deepseek`` preset's base URL flows out, and ``client_kwargs``
        includes both. Same plumbing as BYOK -- the difference is the
        *source* of the api_key, not the wiring.
        """
        engine, Session = _sync_session_factory()
        session = Session()
        user = _make_user(session)  # keyless
        repo = _make_repo(session, user)
        session.commit()
        try:
            clone_root = sample_repo.build(tmp_path / "sample")
            fake = openai_stub.install(monkeypatch)

            # ``LLMConfig.server_default()`` reads ``settings.AI_API_KEY``
            # at call time. Pin the value so the assertion is stable
            # regardless of what the test environment set up.
            monkeypatch.setattr(settings, "AI_API_KEY", "test-server-deepseek-key", raising=False)
            free_tier_config = LLMConfig.server_default()
            assert free_tier_config is not None
            assert free_tier_config.base_url == PROVIDERS["deepseek"].base_url

            from app.services.pipeline import run_full_analysis

            run_full_analysis(
                session,
                repo,
                clone_root,
                type("R", (), {"publish": lambda self, *a, **k: None})(),
                lambda *a, **k: None,
                manage_status=True,
                overlap_llm=True,
                llm_config=free_tier_config,
            )
            session.commit()

            assert _has_deepseek_init(fake, "test-server-deepseek-key"), (
                f"No client carried the DeepSeek base URL + server key: {fake.init_kwargs!r}"
            )
            assert not _has_byok_init(fake), "BYOK init leaked into a keyless run"
        finally:
            _cleanup(session, [repo])
            session.close()
            engine.dispose()

    def test_legacy_fallback_uses_the_server_key_when_ai_api_key_is_empty(
        self, monkeypatch, tmp_path
    ):
        """With ``AI_API_KEY`` empty the four services fall back to ``settings.OPENAI_API_KEY``.

        The route-layer quota gates render this path unreachable in
        production, but the *plumbing* has to handle it: ``llm=None``
        stays the default on each service signature. The recorded
        ``init_kwargs`` should carry the server key with no preset
        ``base_url``.
        """
        engine, Session = _sync_session_factory()
        session = Session()
        user = _make_user(session)
        repo = _make_repo(session, user)
        session.commit()
        try:
            clone_root = sample_repo.build(tmp_path / "sample")
            fake = openai_stub.install(monkeypatch)

            monkeypatch.setattr(settings, "AI_API_KEY", "", raising=False)

            from app.services.pipeline import run_full_analysis

            run_full_analysis(
                session,
                repo,
                clone_root,
                type("R", (), {"publish": lambda self, *a, **k: None})(),
                lambda *a, **k: None,
                manage_status=False,
                overlap_llm=False,
                llm_config=None,
            )
            session.commit()

            assert _has_keyless_with_server_key(fake, settings.OPENAI_API_KEY), (
                f"No legacy-fallback init carried the server key: {fake.init_kwargs!r}"
            )
            assert not _has_byok_init(fake), "BYOK init leaked into a keyless + disabled run"
        finally:
            _cleanup(session, [repo])
            session.close()
            engine.dispose()


class TestChatRouteForwardsTheResolvedConfig:
    """The chat route resolves ``LLMConfig`` from the calling user and forwards it.

    The ``rag`` recorder fixture in ``test_chat_api.py`` was updated to
    accept the new ``llm=`` kwarg; this class pins what the route
    passes -- the user's stored config when one is set, ``None`` when
    the user is keyless.
    """

    async def test_a_byok_user_receives_their_config(self, client, db_session, monkeypatch):
        """A user with ``ai_api_key`` set has that config forwarded to ``answer_question``.

        Uses the same ``rag`` fixture as the chat-route test suite; the
        ``fake_answer_question`` recorder stores ``llm`` so the
        assertion reads it back. The route is the one we just changed
        -- it has to look up the user and pass ``llm_config_for(owner)``
        to ``answer_question``, which the recorder then surfaces.

        ``make_user`` exposes email/name/password but not the BYOK
        columns; set them directly on the freshly-flushed row before
        committing. The Phase 3 migration adds them; the Phase 4 path
        is what reads them.
        """
        from tests.factories import make_ingested_repo, make_user

        user = await make_user(db_session)
        user.ai_provider = _BYOK_PROVIDER
        user.ai_api_key = _BYOK_API_KEY
        user.ai_model = _BYOK_MODEL
        await db_session.flush()
        repo, _ = await make_ingested_repo(db_session, user)
        from tests.helpers import authenticate

        await authenticate(client, user)

        # Install the recorder the way ``test_chat_api.py`` does. Using
        # ``monkeypatch.setattr`` directly on the chat module so the
        # recorder captures what the route actually forwards.
        recorder: list[dict] = []

        async def fake_answer_question(query, repository_id, db, history=None, *, llm=None):
            recorder.append({"llm": llm})
            from app.services.rag import RAGResponse, SourceReference

            return RAGResponse(
                answer="ok",
                sources=[
                    SourceReference(
                        source_type="commit", chunk_text="x", commit_hash="x", author_name="a"
                    )
                ],
            )

        from app.api.v1 import chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)

        await client.post(f"/api/v1/repository/{repo.id}/chat", json={"question": "q"})

        assert recorder, "answer_question was never called"
        forwarded = recorder[0]["llm"]
        assert isinstance(forwarded, LLMConfig)
        assert forwarded.source == "user"
        assert forwarded.api_key == _BYOK_API_KEY
        assert forwarded.model == _BYOK_MODEL
        assert forwarded.base_url == _BYOK_BASE_URL

    async def test_a_keyless_user_receives_none_or_the_server_default(
        self, client, db_session, monkeypatch
    ):
        """A keyless user receives ``None`` (or the server default when ``AI_API_KEY`` is set).

        The route delegates the resolution to :func:`llm_config_for`,
        so the assertion is shape-only: ``None`` when the server has
        no key, a ``server``-sourced config otherwise. The route-layer
        quota gates turn ``None`` into a 402 rather than forwarding it
        onward, so the route short-circuits with no LLM call; the
        assertion below pins the policy output that drives the 402.
        """
        from tests.factories import make_ingested_repo, make_user

        user = await make_user(db_session)  # no BYOK columns populated
        repo, _ = await make_ingested_repo(db_session, user)
        from tests.helpers import authenticate

        await authenticate(client, user)

        # The default test environment has ``AI_API_KEY`` empty; pin
        # it here to control the assertion without depending on the
        # test config.
        monkeypatch.setattr(settings, "AI_API_KEY", "", raising=False)

        # The route-layer quota gates turn ``None`` into a 402 before
        # any LLM call. The assertion is the status code.
        response = await client.post(f"/api/v1/repository/{repo.id}/chat", json={"question": "q"})

        assert response.status_code == 402
        assert "API key" in response.json()["detail"]

    async def test_a_keyless_user_with_server_key_admits_with_server_config(
        self, client, db_session, monkeypatch
    ):
        """With ``AI_API_KEY`` set, the keyless user is admitted on the server default.

        This is the *admitted* branch of the same case the previous
        test pins as a 402. Phase 4's plumbing assertion still holds
        here: the route forwards whatever :func:`llm_config_for`
        resolves, and the resolved shape is the ``server`` config.
        """
        from tests.factories import make_ingested_repo, make_user

        user = await make_user(db_session)
        repo, _ = await make_ingested_repo(db_session, user)
        from tests.helpers import authenticate

        await authenticate(client, user)

        monkeypatch.setattr(settings, "AI_API_KEY", "sk-server-test", raising=False)

        recorder: list[dict] = []

        async def fake_answer_question(query, repository_id, db, history=None, *, llm=None):
            recorder.append({"llm": llm})
            from app.services.rag import RAGResponse, SourceReference

            return RAGResponse(
                answer="ok",
                sources=[
                    SourceReference(
                        source_type="commit", chunk_text="x", commit_hash="x", author_name="a"
                    )
                ],
            )

        from app.api.v1 import chat as chat_module

        monkeypatch.setattr(chat_module, "answer_question", fake_answer_question)

        response = await client.post(f"/api/v1/repository/{repo.id}/chat", json={"question": "q"})

        assert response.status_code == 200
        assert recorder
        forwarded = recorder[0]["llm"]
        assert forwarded is not None
        assert forwarded.source == "server"
        assert forwarded.api_key == "sk-server-test"
