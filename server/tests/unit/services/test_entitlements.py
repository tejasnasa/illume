"""Unit tests for the per-user quota policy.

The policy in :mod:`app.services.entitlements` is exercised here against a
fake settings namespace, the same pattern :mod:`tests.unit.services.
test_llm_config` uses: the real ``Settings`` was bound at import time from
the test environment's env vars, so a ``SimpleNamespace`` stub is the
supported way to vary what ``LLMConfig.server_default()`` reads.

The headline matrix for :func:`llm_config_for` mirrors the precedence:

* user's stored key wins -- even when ``AI_API_KEY`` is empty;
* server key wins when the user has no key and ``AI_API_KEY`` is set;
* ``None`` when neither is present (the route layer maps this to 402).

The two claim helpers are tested separately, in
:mod:`tests.integration.services.test_entitlements`, because their contract
is "two concurrent callers cannot both succeed" and that needs a real
transactional database -- exactly what the existing
``test_sweep_task.py::TestClaimPredicate`` matrix is for.
"""

from types import SimpleNamespace

import pytest

from app.services import entitlements

pytestmark = pytest.mark.unit


@pytest.fixture
def stub_settings(monkeypatch):
    """Patch the ``settings`` namespace ``LLMConfig.server_default`` reads from.

    ``LLMConfig`` reads ``settings.AI_API_KEY`` / ``settings.AI_MODEL`` /
    ``settings.AI_BASE_URL`` directly at module import time on
    :mod:`app.services.llm_config`. The entitlements module does not
    re-export ``settings`` -- patching there would silently bypass the real
    lookup. Patch the namespace ``llm_config`` actually reads.
    """

    def _make(**overrides):
        defaults = {
            "AI_API_KEY": "",
            "AI_MODEL": "",
            "AI_BASE_URL": "",
        }
        defaults.update(overrides)
        stub = SimpleNamespace(**defaults)
        monkeypatch.setattr("app.services.llm_config.settings", stub)
        return stub

    return _make


class TestConstants:
    """The numeric policy is module-level so a deploy controls it."""

    def test_free_ingestions_is_three(self):
        """Three ingestions -- enough to evaluate the artefact set, not enough to sustain use."""
        assert entitlements.FREE_INGESTIONS == 3

    def test_free_chat_messages_is_five(self):
        """Five chat questions; enough to confirm retrieval matches the on-screen citations."""
        assert entitlements.FREE_CHAT_MESSAGES == 5


class TestLLMConfigFor:
    """``llm_config_for(user)`` -- the precedence the route layer relies on."""

    def test_returns_user_config_when_user_has_a_key(self, stub_settings):
        """A user with their own key gets their key, even when ``AI_API_KEY`` is empty."""
        stub_settings(AI_API_KEY="")
        user = SimpleNamespace(
            ai_provider="openai",
            ai_api_key="sk-user",
            ai_model="gpt-4o-mini",
        )

        config = entitlements.llm_config_for(user)

        assert config is not None
        assert config.api_key == "sk-user"
        assert config.source == "user"

    def test_falls_back_to_server_default_when_user_has_no_key(self, stub_settings):
        """A keyless user gets the server default when ``AI_API_KEY`` is set."""
        stub_settings(AI_API_KEY="server-key")
        user = SimpleNamespace(ai_provider=None, ai_api_key=None, ai_model=None)

        config = entitlements.llm_config_for(user)

        assert config is not None
        assert config.api_key == "server-key"
        assert config.source == "server"

    def test_returns_none_when_neither_user_nor_server_has_a_key(self, stub_settings):
        """``None`` propagates up -- the route layer turns it into a 402."""
        stub_settings(AI_API_KEY="")
        user = SimpleNamespace(ai_provider=None, ai_api_key=None, ai_model=None)

        assert entitlements.llm_config_for(user) is None

    def test_user_config_wins_over_server_key(self, stub_settings):
        """Stored key beats server key. Once a user has paid once, the operator stops paying."""
        stub_settings(AI_API_KEY="server-key")
        user = SimpleNamespace(
            ai_provider="openai",
            ai_api_key="sk-user",
            ai_model="gpt-4o-mini",
        )

        config = entitlements.llm_config_for(user)

        assert config is not None
        assert config.api_key == "sk-user"
        assert config.source == "user"
