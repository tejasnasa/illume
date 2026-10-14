"""Registry of preset LLM providers the free tier and BYOK presets talk to.

This module exists separately from :mod:`app/services/llm_config.py` for one
reason: the Phase 1 transport probe (:mod:`server/scripts/probe_ai_provider.py`)
must learn the real base URL without importing :mod:`app.core.config`, because
that module instantiates ``Settings()`` at import time and requires a full
environment (the documented CI-breaking gotcha -- a fresh ``Settings()`` will
raise ``ValidationError`` before the probe reaches its first check). The
registry imports zero settings so the probe can share it.

The four presets cover the providers we have verified speak the Responses API
the four generation services already use (``client.responses.create`` with
``reasoning.effort`` and ``max_output_tokens``):

  - **OpenAI** -- the SDK's default base URL; we set it explicitly so future
    SDK changes don't silently redirect us elsewhere.
  - **Groq** -- the one preset with ``supports_reasoning=False``. Groq accepts
    ``reasoning`` as a Responses-API extra, but a non-reasoning model can 400
    on it, and ``onboarding._request`` swallows per-batch failures -- so an
    incompatible combination would silently yield zero annotations rather than
    an error.
  - **OpenRouter** -- its ``/api/v1`` is OpenAI-compatible.
  - **DeepSeek** -- note ``https://api.deepseek.com`` with **no** ``/v1``
    suffix. OpenAI's is ``https://api.openai.com/v1``; DeepSeek's Responses
    endpoint lives at ``https://api.deepseek.com/responses`` and a trailing
    ``/v1`` makes it 404 at request time, not at import. The Phase 1 probe is
    the gate that catches a wrong base URL here.

There is deliberately no "custom base URL" preset. A user-supplied URL would
need SSRF guardrails (the cookie carries the credential to whatever host is
named), and the ``provider`` enum gives the API contract a fixed surface
instead.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AIProvider:
    """A preset LLM provider: its label, base URL, default model, and reasoning support.

    Attributes:
        key: The short identifier persisted on ``User.ai_provider`` and used
            as the key into :data:`PROVIDERS`. Stable across deploys; never
            the display label.
        label: Human-readable name shown in the settings UI.
        base_url: The OpenAI-compatible base URL the SDK reads. None of these
            providers require ``/v1`` (OpenAI is the one the SDK defaults to,
            but we set it explicitly anyway).
        default_model: The model used when the user hasn't picked one and
            when the server's free tier has no ``$AI_MODEL`` override.
        supports_reasoning: True if the provider's ``responses.create``
            accepts the ``reasoning={"effort": ...}`` parameter. Groq is the
            one False; see module docstring.
        key_prefixes: Prefixes that identify this provider's keys, used only
            to build a "did you mean" hint when a probe is rejected -- never
            to validate. Deliberately empty for OpenAI and DeepSeek: both
            issue ``sk-`` keys, so listing the prefix for either would make
            every DeepSeek key look like an OpenAI one. Any prefix named here
            must be exclusive to its provider, because the failure mode of a
            wrong entry is a confidently wrong suggestion.
    """

    key: str
    label: str
    base_url: str
    default_model: str
    supports_reasoning: bool
    key_prefixes: tuple[str, ...] = ()


PROVIDERS: dict[str, AIProvider] = {
    "openai": AIProvider(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        supports_reasoning=True,
    ),
    "groq": AIProvider(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        supports_reasoning=False,
        key_prefixes=("gsk_",),
    ),
    "openrouter": AIProvider(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        supports_reasoning=True,
        key_prefixes=("sk-or-",),
    ),
    "deepseek": AIProvider(
        key="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-flash",
        supports_reasoning=True,
    ),
}


def get_provider(key: str) -> AIProvider:
    """Resolve a stored provider key to its registry entry.

    Args:
        key: The ``User.ai_provider`` value, one of ``PROVIDERS``.

    Returns:
        The matching :class:`AIProvider`.

    Raises:
        KeyError: When ``key`` is not a known preset. Callers should map this
            to a 422 -- an unknown provider means the stored row is stale
            relative to a deploy that removed a preset, and silently falling
            through to a default would mask that.
    """
    return PROVIDERS[key]


SuggestionReason = Literal["model", "key_prefix"]


def suggest_provider(
    provider_key: str, *, model: str, api_key: str
) -> tuple[AIProvider, SuggestionReason] | None:
    """Guess a preset the caller probably meant instead of ``provider_key``.

    Exists for one failure: a user pastes their provider's key while a
    different provider is selected, the probe is rejected, and the bare
    message ("Incorrect API key for OpenAI.") names only the provider they
    already know about. This supplies the missing half -- which preset the
    submitted evidence actually points at.

    Two local signals, checked in order of how strongly they imply intent:

      1. ``model`` equals another preset's ``default_model``. A model id is
         provider-specific by construction, so an exact match is the better
         signal -- and it is the one that catches a ``sk-`` key, where the
         prefix is shared between OpenAI and DeepSeek.
      2. ``api_key`` starts with another preset's :attr:`AIProvider.key_prefixes`.

    The API key is only ever compared to a handful of literals. It is
    emphatically **not** sent to the other providers to see which one accepts
    it: that would hand the user's secret to a company they did not choose and
    would read as credential stuffing to the one being probed.

    Args:
        provider_key: The preset the caller selected. Never returned.
        model: The model id submitted alongside the key.
        api_key: The submitted credential, compared by prefix only.

    Returns:
        The suggested preset and which signal produced it, or None when
        nothing matches -- the common case for a key that is simply wrong.
    """
    stripped_model = model.strip()

    for preset in PROVIDERS.values():
        if preset.key != provider_key and stripped_model == preset.default_model:
            return preset, "model"

    for preset in PROVIDERS.values():
        if preset.key == provider_key:
            continue
        if any(api_key.startswith(prefix) for prefix in preset.key_prefixes):
            return preset, "key_prefix"

    return None
