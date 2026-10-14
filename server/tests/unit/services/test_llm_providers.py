"""Provider-preset inference used for the "wrong provider selected" hint.

A rejected probe is the usual way a user finds out the Provider field was left
on a different preset than the key and model they pasted. The failure detail
names only the provider that refused them, so :func:`suggest_provider` reads
the two values the user did supply and names the preset they point at.

These are pure-function tests -- no settings, no database, no HTTP. The
route-level behaviour they feed is pinned separately in
``tests/integration/api/test_ai_credentials_api.py``.
"""

import pytest

from app.services.llm_providers import PROVIDERS, suggest_provider

pytestmark = pytest.mark.unit

# The submitted values that would have caught the mix-up this hint exists for:
# a DeepSeek key and DeepSeek's default model, sent while OpenAI was selected.
DEEPSEEK_MODEL = PROVIDERS["deepseek"].default_model
GROQ_MODEL = PROVIDERS["groq"].default_model
GROQ_KEY = "gsk_a_groq_key_12345"
OPENROUTER_KEY = "sk-or-v1-an-openrouter-key"


class TestModelSignal:
    """A model id is provider-specific, so an exact match is the stronger signal."""

    def test_another_presets_default_model_names_that_preset(self):
        assert suggest_provider("openai", model=DEEPSEEK_MODEL, api_key="sk-any") == (
            PROVIDERS["deepseek"],
            "model",
        )

    def test_surrounding_whitespace_is_ignored(self):
        assert suggest_provider(
            "openai", model=f"  {DEEPSEEK_MODEL}  ", api_key="sk-any"
        ) == (PROVIDERS["deepseek"], "model")

    def test_a_custom_model_id_matches_nothing(self):
        assert (
            suggest_provider("openai", model="my-finetune-v3", api_key="sk-any")
            is None
        )

    def test_a_blank_model_does_not_crash_or_match(self):
        assert suggest_provider("openai", model="", api_key="sk-any") is None


class TestKeyPrefixSignal:
    """The fallback for when the model id is custom but the key is recognisable."""

    def test_a_groq_prefixed_key_names_groq(self):
        assert suggest_provider(
            "openai", model="my-finetune-v3", api_key=GROQ_KEY
        ) == (PROVIDERS["groq"], "key_prefix")

    def test_an_openrouter_prefixed_key_names_openrouter(self):
        assert suggest_provider(
            "openai", model="my-finetune-v3", api_key=OPENROUTER_KEY
        ) == (PROVIDERS["openrouter"], "key_prefix")

    def test_model_match_wins_over_key_prefix(self):
        # Model and key point at different presets; the model id says more
        # about what the user meant than the key's prefix does.
        assert suggest_provider(
            "deepseek", model=GROQ_MODEL, api_key=OPENROUTER_KEY
        ) == (PROVIDERS["groq"], "model")

    def test_openai_and_deepseek_are_never_inferred_from_a_prefix(self):
        # Both issue ``sk-`` keys, so neither declares a prefix. Inferring one
        # from the other would mean telling a user with a wrong DeepSeek key
        # that they meant OpenAI.
        assert (
            suggest_provider("groq", model="custom", api_key="sk-abcdef1234567890")
            is None
        )


class TestNoSuggestion:
    """Silence is the right answer when the evidence is consistent."""

    def test_the_selected_provider_is_never_suggested(self):
        assert (
            suggest_provider("deepseek", model=DEEPSEEK_MODEL, api_key="sk-any")
            is None
        )

    def test_a_simply_wrong_key_suggests_nothing(self):
        assert (
            suggest_provider("openai", model="gpt-4o-mini", api_key="nonsense")
            is None
        )

    def test_empty_inputs_suggest_nothing(self):
        assert suggest_provider("openai", model="", api_key="") is None
