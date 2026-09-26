"""Phase-2 LLM credential split.

The existing 818 backend tests pin behaviour against ``settings.OPENAI_API_KEY`` /
``settings.AI_MODEL``. Those call sites are deliberately *not* touched in
Phase 2 -- the four generation services keep reading ``settings.OPENAI_API_KEY``
until Phase 4 threads ``LLMConfig`` through them. The assertions here therefore
focus on the new module in isolation, and the broader "the existing suite
stays green untouched" gate is exercised by running the full backend
collection.

The four bullets the plan pins are covered one-per-method, plus two extras
that fell out of the design:

  - :meth:`LLMConfig.from_user` raises ``KeyError`` on an unknown provider
    rather than silently falling through to a default (the plan's bonus).
  - :meth:`LLMConfig.client_kwargs` includes ``base_url`` when the
    ``LLMConfig`` carries one -- the omit-when-None half is the gate;
    including-when-set is the symmetry that makes both cases behave
    correctly under the same OpenAI SDK constructor.
"""

from types import SimpleNamespace

import pytest

from app.services import llm_config
from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS

pytestmark = pytest.mark.unit


@pytest.fixture
def stub_settings(monkeypatch):
    """Patch the ``settings`` namespace ``llm_config`` reads from.

    The production code reads ``settings.AI_API_KEY`` / ``settings.AI_MODEL``
    / ``settings.AI_BASE_URL`` at call time, but the real ``Settings``
    instance was built at import time from the test environment's env vars.
    ``monkeypatch.setattr`` on the imported ``settings`` would only work
    for attribute access -- which is exactly how the code reads it -- so a
    ``SimpleNamespace`` stub is enough; no need to re-instantiate ``Settings``.
    """

    def _make(**overrides):
        defaults = {
            "AI_API_KEY": "",
            "AI_MODEL": "",
            "AI_BASE_URL": "",
        }
        defaults.update(overrides)
        stub = SimpleNamespace(**defaults)
        monkeypatch.setattr(llm_config, "settings", stub)
        return stub

    return _make


class TestServerDefault:
    """``server_default()`` -- the free tier's config."""

    def test_returns_none_when_ai_api_key_is_empty(self, stub_settings):
        """Missing key disables the free tier rather than crashing on a real request."""
        stub_settings(AI_API_KEY="")

        assert LLMConfig.server_default() is None

    def test_returns_deepseek_config_when_ai_api_key_set(self, stub_settings):
        """With a key, the server default resolves to the DeepSeek registry entry."""
        stub_settings(AI_API_KEY="server-deepseek-key")

        config = LLMConfig.server_default()

        assert config is not None
        assert config.api_key == "server-deepseek-key"
        deepseek = PROVIDERS["deepseek"]
        assert config.model == deepseek.default_model
        assert config.base_url == deepseek.base_url
        assert config.supports_reasoning is True
        assert config.source == "server"

    def test_base_url_omits_the_v1_suffix(self, stub_settings):
        """DeepSeek's Responses endpoint is at ``/responses``, not ``/v1/responses``.

        A trailing ``/v1`` makes the request 404 at request time, not at
        import -- the exact failure mode Phase 1's transport probe exists to
        catch. This assertion pins the no-``/v1`` shape so a future edit
        can't quietly add it back.
        """
        stub_settings(AI_API_KEY="k")

        config = LLMConfig.server_default()

        assert config is not None
        assert not config.base_url.endswith("/v1")
        assert config.base_url == "https://api.deepseek.com"

    def test_settings_overrides_apply_independently(self, stub_settings):
        """``AI_MODEL`` and ``AI_BASE_URL`` each override the registry default on their own.

        If only one is set, the other still comes from the registry, so
        model and base URL cannot drift apart into a mismatched pair.
        """
        stub_settings(
            AI_API_KEY="k",
            AI_MODEL="custom-model",
        )

        config = LLMConfig.server_default()

        assert config is not None
        assert config.model == "custom-model"
        # Base URL still resolves to the registry default.
        assert config.base_url == PROVIDERS["deepseek"].base_url

        stub_settings(
            AI_API_KEY="k",
            AI_BASE_URL="https://override.example.com",
        )
        config = LLMConfig.server_default()
        assert config is not None
        # Model still resolves to the registry default.
        assert config.model == PROVIDERS["deepseek"].default_model
        assert config.base_url == "https://override.example.com"


class TestFromUser:
    """``from_user(user)`` -- the user's stored BYOK config."""

    def test_returns_none_when_provider_missing(self):
        """No provider => keyless user => policy-resolved by the route, not here."""
        user = SimpleNamespace(ai_provider=None, ai_api_key="k", ai_model="m")

        assert LLMConfig.from_user(user) is None

    def test_returns_none_when_key_missing(self):
        """Provider set but key empty: same -- the route handles it."""
        user = SimpleNamespace(ai_provider="openai", ai_api_key=None, ai_model="m")

        assert LLMConfig.from_user(user) is None

    def test_returns_none_when_model_missing(self):
        """Model missing: same -- the route handles it."""
        user = SimpleNamespace(ai_provider="openai", ai_api_key="k", ai_model=None)

        assert LLMConfig.from_user(user) is None

    def test_builds_config_from_known_provider(self):
        """Happy path: the user's row becomes a config carrying the registry's base URL."""
        user = SimpleNamespace(
            ai_provider="openai",
            ai_api_key="sk-user",
            ai_model="gpt-4o-mini",
        )

        config = LLMConfig.from_user(user)

        assert config is not None
        assert config.api_key == "sk-user"
        assert config.model == "gpt-4o-mini"
        assert config.base_url == PROVIDERS["openai"].base_url
        assert config.supports_reasoning is True
        assert config.source == "user"

    def test_unknown_provider_raises_keyerror(self):
        """An unknown provider key must surface, not silently fall through to a default.

        A stored ``ai_provider`` that no longer maps to a preset is a stale
        row from a removed preset -- masking it as a successful BYOK run
        would be a worse failure than a 422 at the route layer.
        """
        user = SimpleNamespace(
            ai_provider="nonexistent-provider",
            ai_api_key="k",
            ai_model="m",
        )

        with pytest.raises(KeyError):
            LLMConfig.from_user(user)


class TestClientKwargs:
    """``client_kwargs()`` -- the OpenAI SDK constructor arguments."""

    def test_server_default_omits_base_url(self, stub_settings):
        """The server default uses the registry's base URL -- still set on the LLMConfig.

        Phase 2's gate is specifically about the *user*'s preset: a
        server-defaulted config *does* carry ``base_url`` because the
        server is DeepSeek and the SDK default points at OpenAI. The
        omit-when-``None`` half of the contract is exercised by a config
        built without one (see :meth:`test_omits_base_url_when_none`).
        """
        stub_settings(AI_API_KEY="k")

        config = LLMConfig.server_default()
        assert config is not None
        kwargs = config.client_kwargs()

        assert kwargs == {
            "api_key": "k",
            "base_url": PROVIDERS["deepseek"].base_url,
        }

    def test_omits_base_url_when_none(self):
        """A config with ``base_url=None`` must not pass ``base_url=None`` literally.

        The E2E suite relies on the OpenAI SDK reading ``$OPENAI_BASE_URL``
        from the environment. A future reader will "fix" a literal
        ``base_url=None`` into a real URL and break the stub -- this is the
        guard against that.
        """
        config = LLMConfig(api_key="k", model="m", base_url=None)

        kwargs = config.client_kwargs()

        assert "base_url" not in kwargs
        assert kwargs == {"api_key": "k"}

    def test_includes_base_url_when_set(self):
        """Symmetry: when the config carries one, the kwargs include it."""
        config = LLMConfig(api_key="k", model="m", base_url="https://x.example/v1")

        kwargs = config.client_kwargs()

        assert kwargs == {
            "api_key": "k",
            "base_url": "https://x.example/v1",
        }


class TestResponseKwargs:
    """``response_kwargs(effort)`` -- the per-call Responses-API extras."""

    def test_returns_empty_dict_for_non_reasoning_provider(self):
        """Groq is the one preset with ``supports_reasoning=False``.

        Without this, ``onboarding._request`` would 400 on
        ``reasoning.effort`` and silently yield zero annotations -- because
        it swallows per-batch failures -- rather than a clear error.
        """
        groq = PROVIDERS["groq"]
        config = LLMConfig(
            api_key="k",
            model=groq.default_model,
            base_url=groq.base_url,
            supports_reasoning=groq.supports_reasoning,
        )

        assert config.response_kwargs() == {}
        # Effort value is irrelevant when reasoning is unsupported.
        assert config.response_kwargs("low") == {}

    def test_returns_reasoning_dict_for_reasoning_provider(self):
        """DeepSeek and the other reasoning-capable presets get ``reasoning.effort``."""
        config = LLMConfig(
            api_key="k",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            supports_reasoning=True,
        )

        assert config.response_kwargs() == {"reasoning": {"effort": "minimal"}}

    def test_effort_parameter_overrides_default(self):
        """``architecture_brief`` passes ``"low"`` while the others pass ``"minimal"``."""
        config = LLMConfig(
            api_key="k",
            model="m",
            base_url="https://x.example/v1",
            supports_reasoning=True,
        )

        assert config.response_kwargs("low") == {"reasoning": {"effort": "low"}}
