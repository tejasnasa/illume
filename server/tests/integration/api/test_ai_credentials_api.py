"""The per-user AI credential store: GET, PUT (probed), and DELETE.

Pins the five things the save flow can do wrong:

* An unknown provider is a 422, not a 500 -- the form should report it as a
  validation error rather than crashing.
* A successful probe stores provider/model and stamps ``validated_at``.
* **A failed probe stores nothing** -- the case that matters, because a
  half-saved credential is worse than none: the next ingestion would 401
  mid-pipeline and leave the user with neither the new key nor their free
  allowance.
* Each SDK error class maps to its specific 400 message, so the form can
  tell "wrong key" from "model not on this provider" from "can't reach the
  provider".
* ``GET /auth/me`` reports ``has_ai_key`` and never echoes the key.
* The probe actually constructs the AsyncOpenAI client with the submitted
  provider's base URL and the submitted model -- asserted through
  ``init_kwargs``, the same property the rest of the byok suite pins.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError
from sqlalchemy import select

from app.models.user import User
from app.services.entitlements import FREE_CHAT_MESSAGES, FREE_INGESTIONS
from app.services.llm_providers import PROVIDERS
from app.services.tool_support import NEGATIVE_VERDICT_TTL, PROBE_REVISED_AT
from tests.factories import make_user
from tests.helpers import authenticate

pytestmark = pytest.mark.integration

GET_URL = "/api/v1/auth/me/ai-credentials"
PUT_URL = "/api/v1/auth/me/ai-credentials"
DELETE_URL = "/api/v1/auth/me/ai-credentials"
ME_URL = "/api/v1/auth/me"

# The OpenAI preset's base URL plus the Responses path. respx intercepts the
# SDK's transport, so the probe runs its real request-shaping code without a
# socket.
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


# --- shared probe stubs ----------------------------------------------------


def _stub_response():
    """A minimal ``httpx.Response`` that the OpenAI SDK's exception classes accept."""
    request = httpx.Request("POST", "https://api.example.com/v1/responses")
    return httpx.Response(200, request=request)


def _stub_request():
    """An ``httpx.Request`` that ``APIConnectionError`` / ``APITimeoutError`` can carry."""
    return httpx.Request("POST", "https://api.example.com/v1/responses")


@pytest.fixture
def successful_probe(monkeypatch):
    """Patch ``AsyncOpenAI`` so the probe returns success.

    Captures the ``__init__`` kwargs so a test can ask "did the probe
    construct the client with the submitted provider's base URL and model?"
    -- the load-bearing property, because a wrong base URL is the failure
    mode the Phase 1 transport probe exists to retire.
    """
    calls: list[dict] = []

    class _FakeResponses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return _StubResponse()

    class _FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            calls.append({"init": dict(kwargs)})
            self.responses = _FakeResponses()

    monkeypatch.setattr(
        "app.api.v1.auth.AsyncOpenAI",
        _FakeAsyncOpenAI,
    )
    return calls


@pytest.fixture
def probe_auth_error(monkeypatch):
    """A probe that raises ``AuthenticationError`` from the SDK."""

    class _FakeResponses:
        async def create(self, **kwargs):
            raise AuthenticationError("invalid api key", response=_stub_response(), body=None)

    class _FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = _FakeResponses()

    monkeypatch.setattr("app.api.v1.auth.AsyncOpenAI", _FakeAsyncOpenAI)


@pytest.fixture
def probe_status_error(monkeypatch):
    """A probe that raises ``APIStatusError`` -- the 'model not on provider' case."""

    class _FakeResponses:
        async def create(self, **kwargs):
            raise APIStatusError("model not found", response=_stub_response(), body=None)

    class _FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = _FakeResponses()

    monkeypatch.setattr("app.api.v1.auth.AsyncOpenAI", _FakeAsyncOpenAI)


@pytest.fixture
def probe_connection_error(monkeypatch):
    """A probe that raises ``APIConnectionError`` -- 'can't reach the provider'."""

    class _FakeResponses:
        async def create(self, **kwargs):
            raise APIConnectionError(request=_stub_request())

    class _FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = _FakeResponses()

    monkeypatch.setattr("app.api.v1.auth.AsyncOpenAI", _FakeAsyncOpenAI)


@pytest.fixture
def probe_timeout(monkeypatch):
    """A probe that raises ``APITimeoutError`` -- also 'can't reach the provider'."""

    class _FakeResponses:
        async def create(self, **kwargs):
            raise APITimeoutError(request=_stub_request())

    class _FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.responses = _FakeResponses()

    monkeypatch.setattr("app.api.v1.auth.AsyncOpenAI", _FakeAsyncOpenAI)


class _StubResponse:
    """A response shape that exercises the success branch."""

    output_text = "pong"


def _responses_payload(*, function_call: bool) -> dict:
    """A wire-shaped Responses payload with or without a function call.

    Mirrors ``scripts/openai_stub_server.py``: the SDK parses these fields
    directly, so a payload missing one surfaces as a client-side validation
    error rather than a test assertion.
    """
    output: list[dict[str, Any]]
    if function_call:
        output = [
            {
                "type": "function_call",
                "id": "fc_stub",
                "call_id": "call_stub",
                "name": "ping",
                "arguments": "{}",
                "status": "completed",
            }
        ]
        tool_choice = "required"
    else:
        output = [
            {
                "type": "message",
                "id": "msg_stub",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "pong", "annotations": []}],
            }
        ]
        tool_choice = "none"

    return {
        "id": "resp_stub",
        "object": "response",
        "created_at": 0,
        "model": "stub",
        "status": "completed",
        "output": output,
        "parallel_tool_calls": False,
        "tool_choice": tool_choice,
        "tools": [],
    }


# --- GET ------------------------------------------------------------------


class TestGet:
    async def test_returns_empty_when_no_credential_is_saved(self, client, db_session):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.get(GET_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["provider"] is None
        assert body["model"] is None
        assert body["has_key"] is False
        assert body["validated_at"] is None

    async def test_returns_the_saved_credential(self, client, db_session):
        from datetime import UTC, datetime

        user = await make_user(
            db_session,
            ai_api_key="sk-test",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        user.ai_key_validated_at = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        await db_session.flush()
        await authenticate(client, user)

        response = await client.get(GET_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "openai"
        assert body["model"] == "gpt-4o-mini"
        assert body["has_key"] is True
        assert body["validated_at"] is not None

    async def test_never_returns_the_key(self, client, db_session):
        """The raw key is not in the response under any field name."""
        user = await make_user(
            db_session,
            ai_api_key="sk-secret-leak-test",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        await db_session.flush()
        await authenticate(client, user)

        response = await client.get(GET_URL)

        body = response.json()
        assert "sk-secret-leak-test" not in str(body)

    async def test_requires_authentication(self, client):
        response = await client.get(GET_URL)

        assert response.status_code == 401


# --- PUT ------------------------------------------------------------------


class TestPut:
    async def test_unknown_provider_is_422(self, client, db_session, successful_probe):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "anthropic",  # not a registered preset
                "api_key": "sk-test-key-12345",
                "model": "claude-3-5-sonnet",
            },
        )

        assert response.status_code == 422
        # The probe was never reached -- the provider check happens first.
        assert successful_probe == []

    async def test_short_api_key_is_422(self, client, db_session, successful_probe):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "short",  # min_length=8
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 422
        assert successful_probe == []

    async def test_long_api_key_is_422(self, client, db_session, successful_probe):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "x" * 513,  # max_length=512
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 422
        assert successful_probe == []

    async def test_control_characters_in_model_are_rejected(
        self, client, db_session, successful_probe
    ):
        """``FreeText`` on ``model`` rejects NUL and other C0 control characters."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "bad\x00model",
            },
        )

        assert response.status_code == 422
        assert successful_probe == []

    async def test_successful_probe_stores_provider_and_model(
        self, client, db_session, successful_probe
    ):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "openai"
        assert body["model"] == "gpt-4o-mini"
        assert body["has_key"] is True
        assert body["validated_at"] is not None

        # Persisted on the row.
        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_provider == "openai"
        assert stored.ai_api_key == "sk-test-key-12345"
        assert stored.ai_model == "gpt-4o-mini"
        assert stored.ai_key_validated_at is not None

    async def test_probe_uses_the_provider_base_url_and_submitted_model(
        self, client, db_session, successful_probe
    ):
        """The probe constructs ``AsyncOpenAI`` with the registry's base URL
        and passes the user's model id to ``responses.create``.

        The provider base URL is the load-bearing property -- a wrong one
        here would 404 at request time, which is exactly the failure mode
        the Phase 1 transport probe exists to catch.
        """
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "deepseek",
                "api_key": "sk-test-key-12345",
                "model": "deepseek-flash",
            },
        )

        assert response.status_code == 200

        # Two captures: one for ``AsyncOpenAI.__init__``, one for ``responses.create``.
        assert len(successful_probe) >= 2
        init_kwargs = successful_probe[0]["init"]
        # DeepSeek's base URL has no ``/v1`` -- a regression that adds it would
        # break the wire format and pass the assert below as a literal string.
        assert init_kwargs["base_url"] == PROVIDERS["deepseek"].base_url
        assert init_kwargs["api_key"] == "sk-test-key-12345"

        create_kwargs = successful_probe[1]
        assert create_kwargs["model"] == "deepseek-flash"
        assert create_kwargs["input"] == "ping"
        assert create_kwargs["max_output_tokens"] == 16

    async def test_failed_probe_stores_nothing(self, client, db_session, probe_auth_error):
        """The case that matters -- a half-saved credential is worse than none."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-wrong-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 400
        assert "Incorrect API key" in response.json()["detail"]

        # The user's row is untouched -- no provider, no key, no model.
        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_provider is None
        assert stored.ai_api_key is None
        assert stored.ai_model is None
        assert stored.ai_key_validated_at is None

    async def test_auth_error_maps_to_400(self, client, db_session, probe_auth_error):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-wrong-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 400
        assert "Incorrect API key" in response.json()["detail"]
        assert "OpenAI" in response.json()["detail"]

    async def test_status_error_maps_to_400(self, client, db_session, probe_status_error):
        """A non-auth 4xx/5xx from the provider -- typically 'model not on provider'."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "groq",
                "api_key": "gsk-test-key-12345",
                "model": "model-not-on-groq",
            },
        )

        assert response.status_code == 400
        assert "isn't available" in response.json()["detail"]
        assert "Groq" in response.json()["detail"]

    async def test_auth_error_names_the_provider_the_model_belongs_to(
        self, client, db_session, probe_auth_error
    ):
        """The mix-up this hint exists for: another provider's key and model.

        A user with a DeepSeek key pasted it while the picker was still on
        OpenAI. "Incorrect API key for OpenAI." names the provider they already
        know is wrong about them, so the detail also names DeepSeek.
        """
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-deepseek-key-12345",
                "model": "deepseek-flash",
            },
        )

        detail = response.json()["detail"]
        assert response.status_code == 400
        assert "Incorrect API key for OpenAI" in detail
        assert "DeepSeek" in detail
        assert "change the Provider field" in detail

    async def test_auth_error_names_the_provider_the_key_prefix_belongs_to(
        self, client, db_session, probe_auth_error
    ):
        """With a custom model id, a recognisable key prefix carries the signal."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "gsk_a_groq_key_12345",
                "model": "some-custom-model",
            },
        )

        detail = response.json()["detail"]
        assert response.status_code == 400
        assert "Incorrect API key for OpenAI" in detail
        assert "Groq" in detail

    async def test_auth_error_has_no_hint_for_a_simply_wrong_key(
        self, client, db_session, probe_auth_error
    ):
        """Nothing points elsewhere, so the detail must not invent a provider."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-simply-wrong-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Incorrect API key for OpenAI."

    async def test_status_error_names_the_provider_the_model_belongs_to(
        self, client, db_session, probe_status_error
    ):
        """A valid key with another provider's model 404s the same way."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-a-valid-openai-key",
                "model": "llama-3.3-70b-versatile",
            },
        )

        detail = response.json()["detail"]
        assert response.status_code == 400
        assert "isn't available on OpenAI" in detail
        assert "Groq" in detail

    async def test_connection_error_maps_to_400(self, client, db_session, probe_connection_error):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 400
        assert "Could not reach" in response.json()["detail"]
        assert "OpenAI" in response.json()["detail"]

    async def test_timeout_maps_to_400(self, client, db_session, probe_timeout):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 400
        assert "Could not reach" in response.json()["detail"]

    async def test_failed_probe_does_not_count_against_allowance(
        self, client, db_session, probe_auth_error
    ):
        """A failed probe must not consume the free chat counter.

        The save flow runs before the chat route ever sees a request, so
        in practice the counters do not move -- but a regression here
        would show up as a user whose first attempt to add a key costs
        them a free question.
        """
        user = await make_user(db_session)
        await authenticate(client, user)

        await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-wrong-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.free_chat_messages_used == 0
        assert stored.free_ingestions_used == 0

    async def test_replaces_an_existing_credential(self, client, db_session, successful_probe):
        """A second PUT overwrites -- the user is updating, not appending."""
        user = await make_user(
            db_session,
            ai_api_key="sk-old-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        await db_session.flush()
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "groq",
                "api_key": "gsk-new-key-12345",
                "model": "llama-3.3-70b-versatile",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "groq"
        assert body["model"] == "llama-3.3-70b-versatile"
        assert body["has_key"] is True

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_provider == "groq"
        assert stored.ai_api_key == "gsk-new-key-12345"
        assert stored.ai_model == "llama-3.3-70b-versatile"

    async def test_requires_authentication(self, client, successful_probe):
        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 401
        assert successful_probe == []


# --- DELETE ---------------------------------------------------------------


class TestDelete:
    async def test_clears_the_saved_credential(self, client, db_session):
        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        await db_session.flush()
        await authenticate(client, user)

        response = await client.delete(DELETE_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["provider"] is None
        assert body["model"] is None
        assert body["has_key"] is False
        assert body["validated_at"] is None

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_provider is None
        assert stored.ai_api_key is None
        assert stored.ai_model is None
        assert stored.ai_key_validated_at is None

    async def test_preserves_the_free_tier_counters(self, client, db_session):
        """Deleting the key does not bring the allowance back.

        The counters are untouched -- a user who deleted their key still
        cannot re-ingest or ask another ten questions.
        """
        from datetime import UTC, datetime

        user = await make_user(db_session)
        user.ai_api_key = "sk-test-key-12345"
        user.ai_provider = "openai"
        user.ai_model = "gpt-4o-mini"
        user.ai_key_validated_at = datetime(2026, 1, 1, tzinfo=UTC)
        user.free_ingestions_used = 1
        user.free_chat_messages_used = 3
        await db_session.flush()
        await authenticate(client, user)

        await client.delete(DELETE_URL)

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.free_ingestions_used == 1
        assert stored.free_chat_messages_used == 3

    async def test_delete_with_no_credential_is_idempotent(self, client, db_session):
        """Deleting a non-existent credential is still 200 -- the endpoint
        is symmetric with PUT and the UI's 'remove' button is enabled in
        any state where ``has_ai_key`` was once True."""
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.delete(DELETE_URL)

        assert response.status_code == 200
        assert response.json()["has_key"] is False

    async def test_requires_authentication(self, client):
        response = await client.delete(DELETE_URL)

        assert response.status_code == 401


# --- /me extended envelope ------------------------------------------------


class TestMeEnvelope:
    async def test_includes_ai_provider_and_model_and_has_key(self, client, db_session):
        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        await db_session.flush()
        await authenticate(client, user)

        response = await client.get(ME_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["ai_provider"] == "openai"
        assert body["ai_model"] == "gpt-4o-mini"
        assert body["has_ai_key"] is True
        assert body["free_ingestions_used"] == 0
        assert body["free_chat_messages_used"] == 0
        assert body["free_ingestions_limit"] == FREE_INGESTIONS
        assert body["free_chat_messages_limit"] == FREE_CHAT_MESSAGES

    async def test_reports_has_ai_key_false_for_a_keyless_user(self, client, db_session):
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.get(ME_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["ai_provider"] is None
        assert body["ai_model"] is None
        assert body["has_ai_key"] is False

    async def test_me_never_echoes_the_raw_key(self, client, db_session):
        """The /me envelope must not leak the raw key under any field name."""
        user = await make_user(
            db_session,
            ai_api_key="sk-do-not-leak-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        await db_session.flush()
        await authenticate(client, user)

        response = await client.get(ME_URL)

        body = response.json()
        assert "sk-do-not-leak-12345" not in str(body)
        assert "api_key" not in body
        assert "ai_api_key" not in body

    async def test_reports_free_tier_counters(self, client, db_session):
        user = await make_user(db_session)
        user.free_ingestions_used = 1
        user.free_chat_messages_used = 2
        await db_session.flush()
        await authenticate(client, user)

        response = await client.get(ME_URL)

        body = response.json()
        assert body["free_ingestions_used"] == 1
        assert body["free_chat_messages_used"] == 2
        # The caps ride along so the client never mirrors the policy numbers.
        assert body["free_ingestions_limit"] == FREE_INGESTIONS
        assert body["free_chat_messages_limit"] == FREE_CHAT_MESSAGES


# --- Function-calling support ---------------------------------------------


class TestToolSupportProbe:
    """The second probe records function-calling support; it never rejects a key.

    The shape of the request is asserted from the wire body, which also pins
    the tool definition and ``tool_choice: "auto"`` -- the way the agent asks
    for tools, since some providers refuse ``"required"`` but call tools under
    ``"auto"``.
    """

    @respx.mock
    async def test_a_function_call_is_recorded_as_supported(self, client, db_session):
        route = respx.post(OPENAI_RESPONSES_URL).mock(
            side_effect=[
                httpx.Response(200, json=_responses_payload(function_call=False)),
                httpx.Response(200, json=_responses_payload(function_call=True)),
            ]
        )
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supports_tools"] is True
        assert body["tools_checked_at"] is not None

        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_supports_tools is True
        assert stored.ai_tools_checked_at is not None

        # The second request is the tool probe: one ping function, asked as the agent asks.
        requests = [json.loads(call.request.content) for call in route.calls]
        assert len(requests) == 2
        tool_request = requests[1]
        assert tool_request["tool_choice"] == "auto"
        assert tool_request["tools"][0]["type"] == "function"
        assert tool_request["tools"][0]["name"] == "ping"

    @respx.mock
    async def test_text_only_provider_is_recorded_but_still_saves(self, client, db_session):
        route = respx.post(OPENAI_RESPONSES_URL).mock(
            return_value=httpx.Response(200, json=_responses_payload(function_call=False))
        )
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 200
        assert response.json()["supports_tools"] is False
        # Both probes ran: the text check and the tool check.
        assert route.call_count == 2
        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_api_key == "sk-test-key-12345"
        assert stored.ai_supports_tools is False

    @respx.mock
    async def test_a_rejected_tool_choice_is_recorded_but_still_saves(self, client, db_session):
        """A provider that 400s on tools answered the question; it did not reject the key."""
        respx.post(OPENAI_RESPONSES_URL).mock(
            side_effect=[
                httpx.Response(200, json=_responses_payload(function_call=False)),
                httpx.Response(
                    400,
                    json={
                        "error": {
                            "message": "tool_choice is not supported",
                            "type": "invalid_request_error",
                            "param": "tool_choice",
                            "code": None,
                        }
                    },
                ),
            ]
        )
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 200
        assert response.json()["supports_tools"] is False

    @respx.mock
    async def test_no_answer_from_the_tool_probe_leaves_it_unmeasured(self, client, db_session):
        """A timeout says nothing about tools; recording ``False`` would never be re-probed."""
        respx.post(OPENAI_RESPONSES_URL).mock(
            side_effect=[
                httpx.Response(200, json=_responses_payload(function_call=False)),
                httpx.ConnectTimeout("timed out"),
            ]
        )
        user = await make_user(db_session)
        await authenticate(client, user)

        response = await client.put(
            PUT_URL,
            json={
                "provider": "openai",
                "api_key": "sk-test-key-12345",
                "model": "gpt-4o-mini",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supports_tools"] is None
        assert body["tools_checked_at"] is None
        stored = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert stored.ai_api_key == "sk-test-key-12345"
        assert stored.ai_supports_tools is None


class TestLazyToolSupport:
    """``ensure_tool_support`` fills the NULL case once and caches a measured one."""

    @respx.mock
    async def test_checks_once_for_a_user_saved_before_the_columns(self, db_session):
        from app.services.tool_support import ensure_tool_support

        route = respx.post(OPENAI_RESPONSES_URL).mock(
            return_value=httpx.Response(200, json=_responses_payload(function_call=True))
        )
        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        assert user.ai_supports_tools is None

        assert await ensure_tool_support(db_session, user) is True
        assert route.call_count == 1
        assert user.ai_supports_tools is True
        assert user.ai_tools_checked_at is not None

        # A cached verdict is reused with no second request.
        assert await ensure_tool_support(db_session, user) is True
        assert route.call_count == 1

    @respx.mock
    async def test_a_recent_false_is_not_reprobed(self, db_session):
        from app.services.tool_support import ensure_tool_support

        route = respx.post(OPENAI_RESPONSES_URL).mock(
            return_value=httpx.Response(200, json=_responses_payload(function_call=True))
        )
        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        user.ai_supports_tools = False
        user.ai_tools_checked_at = datetime.now(UTC)
        await db_session.flush()

        assert await ensure_tool_support(db_session, user) is False
        assert route.call_count == 0

    @respx.mock
    @pytest.mark.parametrize(
        "checked_at",
        [None, PROBE_REVISED_AT - timedelta(days=1), "expired"],
        ids=["no-timestamp", "before-the-probe-changed", "expired"],
    )
    async def test_a_stale_false_is_measured_again(self, db_session, checked_at):
        from app.services.tool_support import ensure_tool_support

        route = respx.post(OPENAI_RESPONSES_URL).mock(
            return_value=httpx.Response(200, json=_responses_payload(function_call=True))
        )
        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        if checked_at == "expired":
            checked_at = datetime.now(UTC) - NEGATIVE_VERDICT_TTL - timedelta(hours=1)
        user.ai_supports_tools = False
        user.ai_tools_checked_at = checked_at
        await db_session.flush()

        assert await ensure_tool_support(db_session, user) is True
        assert route.call_count == 1
        assert user.ai_supports_tools is True

    @respx.mock
    async def test_a_server_error_is_retried_on_the_next_request(self, db_session):
        from app.services.tool_support import ensure_tool_support

        route = respx.post(OPENAI_RESPONSES_URL).mock(
            side_effect=[
                httpx.Response(503, json={"error": {"message": "overloaded"}}),
                httpx.Response(200, json=_responses_payload(function_call=True)),
            ]
        )
        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )

        assert await ensure_tool_support(db_session, user) is None
        assert user.ai_supports_tools is None

        assert await ensure_tool_support(db_session, user) is True
        assert route.call_count == 2

    async def test_a_keyless_user_has_nothing_to_check(self, db_session):
        from app.services.tool_support import ensure_tool_support

        user = await make_user(db_session)

        assert await ensure_tool_support(db_session, user) is None


# --- Repository sync_available --------------------------------------------


class TestRepositorySyncAvailable:
    """The repository DTO carries ``sync_available``: derived user-level state
    that drives the AutoUpdateSection's disabled state.

    A keyless user has ``sync_available=False`` (free tier cannot pay for
    syncs); a user with a stored key has ``sync_available=True``.
    """

    async def test_keyless_user_sees_sync_available_false(self, client, db_session):
        from tests.factories import make_repo

        user = await make_user(db_session)
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.get(f"/api/v1/repository/{repo.repo_number}")

        assert response.status_code == 200
        assert response.json()["sync_available"] is False

    async def test_byok_user_sees_sync_available_true(self, client, db_session):
        from tests.factories import make_repo

        user = await make_user(
            db_session,
            ai_api_key="sk-test-key-12345",
            ai_provider="openai",
            ai_model="gpt-4o-mini",
        )
        repo = await make_repo(db_session, user)
        await authenticate(client, user)

        response = await client.get(f"/api/v1/repository/{repo.repo_number}")

        assert response.status_code == 200
        assert response.json()["sync_available"] is True

    async def test_list_reflects_user_state_for_every_repo(self, client, db_session):
        from tests.factories import make_repo

        user = await make_user(db_session)
        await make_repo(db_session, user, name="one")
        await make_repo(db_session, user, name="two")
        await authenticate(client, user)

        response = await client.get("/api/v1/repository")

        assert response.status_code == 200
        bodies = response.json()
        assert len(bodies) == 2
        assert all(body["sync_available"] is False for body in bodies)

        # Save a key -- both should flip to True on the next list call.
        user.ai_api_key = "sk-test-key-12345"
        user.ai_provider = "openai"
        user.ai_model = "gpt-4o-mini"
        await db_session.flush()

        response = await client.get("/api/v1/repository")

        bodies = response.json()
        assert all(body["sync_available"] is True for body in bodies)
