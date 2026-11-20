"""Where the judge is called: a model on an endpoint, with a transport and a key.

The generator is fixed, but the judge is swappable so a free model on another provider's
OpenAI-compatible endpoint can grade the same answers and be compared with the pinned judge.
The key is held only so a client can be built; it is kept out of ``repr`` and equality and is
never written to a record, a manifest, a file name or a log.

Library code here takes nothing from ``evals.settings``; the entry point passes in the values
read from the eval env file.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from evals.models import JUDGE_MODEL

ApiStyle = Literal["responses", "chat"]
API_STYLES: tuple[str, ...] = ("responses", "chat")
DEFAULT_HOST = "openai"
"""The host recorded when no base URL is set and the SDK's default endpoint is used."""


class JudgeConfigError(ValueError):
    """The judge is not configured in a way that can be used."""


@dataclass(frozen=True)
class JudgeEndpoint:
    """A judge model, the endpoint it is reached on and the transport used.

    Attributes:
        model: The model id asked for.
        base_url: The endpoint's base URL, or ``None`` for the SDK's default (OpenAI).
        api_key: The key; never shown, compared or stored.
        api_style: ``responses`` for the Responses API with a strict JSON schema, or ``chat``
            for chat completions asked for JSON.
    """

    model: str
    base_url: str | None = None
    api_key: str = field(default="", repr=False, compare=False)
    api_style: ApiStyle = "responses"

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise JudgeConfigError("the judge model is empty")
        if self.api_style not in API_STYLES:
            raise JudgeConfigError(
                f"unknown judge API style {self.api_style!r}; use one of {', '.join(API_STYLES)}"
            )
        if self.base_url is not None and not urlparse(self.base_url).hostname:
            raise JudgeConfigError("the judge base URL has no host")

    @property
    def host(self) -> str:
        """The base URL's host, with no path, port or credentials; ``openai`` by default."""
        if self.base_url is None:
            return DEFAULT_HOST
        return str(urlparse(self.base_url).hostname)

    @property
    def slug(self) -> str:
        """A file-name-safe identity of the model and host, used to keep judges' files apart."""
        raw = f"{self.model}@{self.host}"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{self.model}--{self.host}").strip("-")
        return f"{safe}--{hashlib.sha256(raw.encode()).hexdigest()[:6]}"

    def client_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``AsyncOpenAI``; ``base_url`` is left out when unset."""
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
        return kwargs

    def require_key(self) -> str:
        """The key, failing clearly when it is empty.

        Raises:
            JudgeConfigError: If no key is configured for this endpoint.
        """
        if not self.api_key:
            name = "JUDGE_API_KEY" if self.base_url else "OPENAI_API_KEY (or JUDGE_API_KEY)"
            raise JudgeConfigError(f"{name} is not set in server/evals/.env.eval")
        return self.api_key


def resolve_judge_endpoint(
    keys: Mapping[str, str],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_style: str | None = None,
) -> JudgeEndpoint:
    """The judge for a run: command-line values over the env file's, over the defaults.

    Defaults when empty are the pinned judge model, OpenAI's own endpoint, the Responses API
    and ``OPENAI_API_KEY``. The OpenAI key is used only for OpenAI's endpoint: a judge on
    another base URL needs its own ``JUDGE_API_KEY`` so the OpenAI key is never sent elsewhere.

    Args:
        keys: The values read from the eval env file.
        model: ``--judge-model``.
        base_url: ``--judge-base-url``.
        api_style: ``--judge-api-style``.

    Returns:
        The endpoint. An empty key is not an error here; see :meth:`JudgeEndpoint.require_key`.

    Raises:
        JudgeConfigError: On an unknown API style or a base URL with no host.
    """
    chosen_url = base_url or keys.get("JUDGE_BASE_URL") or None
    key = keys.get("JUDGE_API_KEY") or ("" if chosen_url else keys.get("OPENAI_API_KEY", ""))
    return JudgeEndpoint(
        model=model or keys.get("JUDGE_MODEL") or JUDGE_MODEL,
        base_url=chosen_url,
        api_key=key,
        api_style=(api_style or keys.get("JUDGE_API_STYLE") or "responses"),  # type: ignore[arg-type]
    )


__all__ = [
    "API_STYLES",
    "DEFAULT_HOST",
    "ApiStyle",
    "JudgeConfigError",
    "JudgeEndpoint",
    "resolve_judge_endpoint",
]
