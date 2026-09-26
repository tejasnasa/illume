"""Resolved LLM credentials handed to every generation call.

Why a value object rather than reading ``settings.OPENAI_API_KEY`` directly at
each call site: by Phase 5, the credential to use depends on whose key paid
for it -- the user's stored key if they have one, otherwise the server's
deepseek key for the free tier, otherwise ``None`` and the call is refused.
Threading that decision through every service as three separate globals is
what got us into the one-key-pays-for-everyone state in the first place.

``LLMConfig`` is a frozen value object of strings and booleans -- safe to
hand to the thread helpers in :mod:`app/tasks/_parallel.py`, whose docstring
rule is "scalars only, so no ORM instance bound to the main thread's identity
map leaks into a worker". Build it from the owner ``User`` row **before**
submitting to any ``ThreadPoolExecutor``, and never carry a ``Session``.

Two contracts the call sites rely on, both stated as test assertions:

1. :meth:`client_kwargs` **omits** ``base_url`` when it is ``None``, never
   passes ``base_url=None`` literally. The embedding path depends on the
   OpenAI SDK reading ``$OPENAI_BASE_URL`` from the environment, which is
   how the E2E suite reaches its stub (``client/e2e/env.ts:52``). Today's
   literal ``None`` is equivalent to omitting it, but a future reader will
   "fix" it into a real URL and break E2E. ``client_kwargs`` is the guard.
2. :meth:`response_kwargs` is ``{}`` when the provider has no reasoning
   support. Groq is the one preset with ``supports_reasoning=False``; a
   non-reasoning model 400s on ``reasoning.effort``, and
   ``onboarding._request`` swallows per-batch failures -- so the absence of
   reasoning is what keeps ``build_reading_order`` from silently yielding
   zero annotations.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import settings
from app.models.user import User
from app.services.llm_providers import PROVIDERS, get_provider

Source = Literal["user", "server"]


@dataclass(frozen=True)
class LLMConfig:
    """The resolved credential, model, and base URL for one LLM call.

    Attributes:
        api_key: The key the SDK will authenticate with.
        model: The model id passed to ``responses.create``.
        base_url: The base URL the SDK will hit. ``None`` means "let the SDK
            use its default" -- and :meth:`client_kwargs` is what enforces
            that, by literally omitting the keyword.
        supports_reasoning: Whether ``response_kwargs()`` should include
            ``reasoning={"effort": ...}``. Mirrors the provider registry
            entry; carried on the object so callers don't need a second
            registry lookup.
        source: ``"user"`` when built from a stored key, ``"server"`` for the
            free tier. Surfaces in logs and in the ``init_kwargs`` test
            assertion that distinguishes a BYOK run from a keyless one.
    """

    api_key: str
    model: str
    base_url: str | None = None
    supports_reasoning: bool = True
    source: Source = "server"

    @classmethod
    def server_default(cls) -> LLMConfig | None:
        """Build the server-side config for the free tier.

        Returns ``None`` when ``settings.AI_API_KEY`` is empty -- the droplet's
        deploy may not have a free-tier key, and a missing key must surface as
        "free tier disabled" rather than as a runtime 401 from DeepSeek.

        The free tier is DeepSeek: the model's base URL and default model come
        from the registry, but ``settings.AI_MODEL`` and ``settings.AI_BASE_URL``
        override the defaults when set. If only one of them is overridden, the
        other still comes from the registry, so model and base URL cannot
        drift apart into a mismatched pair -- a wrong combo would otherwise
        404 at request time, not at import.
        """
        api_key = settings.AI_API_KEY
        if not api_key:
            return None

        deepseek = PROVIDERS["deepseek"]
        model = settings.AI_MODEL or deepseek.default_model
        base_url = settings.AI_BASE_URL or deepseek.base_url

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            supports_reasoning=deepseek.supports_reasoning,
            source="server",
        )

    @classmethod
    def from_user(cls, user: User) -> LLMConfig | None:
        """Build the config from a stored user row.

        Returns ``None`` when the user has no key -- the route layer is the
        one that decides what to do (402, fall back to the server default,
        etc.). Keeping the ``None`` here means the four generation services
        stay free of policy and stay focused on "given a config, call the
        LLM".

        Args:
            user: The owner of the resource being processed. Must have
                ``ai_provider``, ``ai_api_key``, and ``ai_model`` populated;
                a partially-populated row (e.g. provider set but key empty)
                also returns ``None`` because the keyless form is the
                policy-resolved case, not this method's.
        """
        provider_key = getattr(user, "ai_provider", None)
        api_key = getattr(user, "ai_api_key", None)
        model = getattr(user, "ai_model", None)

        if not provider_key or not api_key or not model:
            return None

        try:
            provider = get_provider(provider_key)
        except KeyError:
            # An unknown provider is a 422 case in the route; raise so the
            # caller doesn't silently fall through to the server default
            # and mask the bad row.
            raise

        return cls(
            api_key=api_key,
            model=model,
            base_url=provider.base_url,
            supports_reasoning=provider.supports_reasoning,
            source="user",
        )

    def client_kwargs(self) -> dict[str, Any]:
        """The keyword arguments to ``OpenAI(...)`` / ``AsyncOpenAI(...)``.

        Omits ``base_url`` when it is ``None`` -- the SDK's default base URL
        applies, which for OpenAI is the right thing, and is also how the
        embedding path inherits ``$OPENAI_BASE_URL`` for the E2E stub.
        Passing ``base_url=None`` literally would behave identically today
        but is the shape a future reader will "fix" into a real URL and
        break the stub.

        Returns:
            A dict suitable for ``**`` into the OpenAI client constructor.
        """
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
        return kwargs

    def response_kwargs(self, effort: str = "minimal") -> dict[str, Any]:
        """The keyword arguments for ``responses.create`` beyond ``model``/``input``.

        Returns ``{}`` when the provider has no reasoning support. Otherwise
        returns ``{"reasoning": {"effort": effort}}``. The four call sites
        do not agree on effort -- ``glossary_builder``, ``onboarding`` and
        ``rag`` pass ``"minimal"``; ``architecture_brief`` passes ``"low"``,
        which is why ``effort`` is a parameter rather than a constant.
        """
        if not self.supports_reasoning:
            return {}
        return {"reasoning": {"effort": effort}}
