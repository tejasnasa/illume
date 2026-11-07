"""The settings a request may change on a preset.

The advanced drawer sends a partial configuration. Only the fields below are
accepted: every other field of :class:`~app.services.retrieval.config.PipelineConfig`
is a 422, because the models reject unknown fields.

What a request may change depends on who pays for the extra calls:

* On the free tier the operator pays, so a request may only make a run cheaper:
  a budget may not exceed the preset's own, a check or the seed may be switched
  off but not on, the channels may only be narrowed, and the reranker and query
  rewriting may only be turned off.
* With the caller's own key, the drawer's switches are open: checks and the seed
  may be switched on, channels added, and the reranker and query rewriting
  chosen. Budgets may be raised only as far as the most generous preset allows,
  never to the bounds the configuration models accept.

The context window stays inside the range a user may set in their account.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.retrieval.config import (
    MAX_CONTEXT_WINDOW,
    MIN_CONTEXT_WINDOW,
    PRESETS,
    PipelineConfig,
)

ChannelKind = Literal["dense", "lexical", "symbol", "grep", "graph", "cochange", "history"]
RerankKind = Literal["none", "cohere", "llm", "jev"]
QueryTransform = Literal["identity", "multi_query", "hyde"]


class OverrideError(ValueError):
    """The requested overrides cannot be applied to the preset."""


class _Strict(BaseModel):
    """Rejects fields outside the allowlist."""

    model_config = ConfigDict(extra="forbid")


class AgentOverrides(_Strict):
    """Limits and switches of the tool-calling loop."""

    max_iterations: int | None = Field(default=None, ge=1, le=50)
    max_tool_calls: int | None = Field(default=None, ge=1, le=300)
    max_seconds: int | None = Field(default=None, ge=10, le=600)
    hard_cancel_seconds: int | None = Field(default=None, ge=10, le=900)
    max_input_tokens: int | None = Field(default=None, ge=1_000, le=10_000_000)
    max_repair_rounds: int | None = Field(default=None, ge=0, le=3)
    max_gate_rejections: int | None = Field(default=None, ge=0, le=5)
    context_window: int | None = Field(default=None, ge=MIN_CONTEXT_WINDOW, le=MAX_CONTEXT_WINDOW)
    effort: Literal["minimal", "low", "medium", "high"] | None = None
    seed: bool | None = None


class PlannerOverrides(_Strict):
    """How a question is split across workers."""

    max_workers: int | None = Field(default=None, ge=2, le=6)
    worker_iterations: int | None = Field(default=None, ge=1, le=50)


class ChecksOverrides(_Strict):
    """Which checks run."""

    gate: bool | None = None
    verify: bool | None = None
    guard: bool | None = None


class QueryOverrides(_Strict):
    """How the question is prepared, and how much conversation is replayed."""

    history_messages: int | None = Field(default=None, ge=0, le=20)
    transform: QueryTransform | None = None


class RerankOverrides(_Strict):
    """Which reranker orders the results."""

    kind: RerankKind | None = None


class DiversifyOverrides(_Strict):
    """How many results survive."""

    total: int | None = Field(default=None, ge=1, le=100)


class Overrides(_Strict):
    """A validated partial configuration."""

    agent: AgentOverrides | None = None
    planner: PlannerOverrides | None = None
    checks: ChecksOverrides | None = None
    query: QueryOverrides | None = None
    rerank: RerankOverrides | None = None
    diversify: DiversifyOverrides | None = None
    channels: list[ChannelKind] | None = Field(default=None, min_length=1)


# Fields where the preset's value is the ceiling.
_AGENT_CEILINGS = (
    "max_iterations",
    "max_tool_calls",
    "max_seconds",
    "hard_cancel_seconds",
    "max_input_tokens",
    "max_repair_rounds",
    "max_gate_rejections",
)
_PLANNER_CEILINGS = ("max_workers", "worker_iterations")
_CHECK_FLAGS = ("gate", "verify", "guard")


def _most_generous(section: str, fields: tuple[str, ...]) -> dict[str, Any]:
    """The highest value of each field across the presets that have ``section``."""
    ceilings: dict[str, Any] = {}
    for preset in PRESETS.values():
        settings = getattr(preset, section)
        if settings is None:
            continue
        for name in fields:
            value = getattr(settings, name)
            if name not in ceilings or value > ceilings[name]:
                ceilings[name] = value
    return ceilings


def _channel_catalogue() -> dict[str, Any]:
    """One configured channel per kind, taken from the first preset that runs it."""
    catalogue: dict[str, Any] = {}
    for preset in PRESETS.values():
        for channel in preset.channels:
            catalogue.setdefault(channel.kind, channel)
    return catalogue


SERVER_AGENT_CEILINGS = _most_generous("agent", _AGENT_CEILINGS)
"""The most a caller's own key may raise each agent budget to."""

SERVER_PLANNER_CEILINGS = _most_generous("planner", _PLANNER_CEILINGS)
"""The most a caller's own key may raise each worker budget to."""

CHANNEL_CATALOGUE = _channel_catalogue()
"""The channel a request gets when it asks for a kind its preset does not run."""


def _set_fields(target: dict[str, Any], overrides: BaseModel) -> dict[str, Any]:
    """Writes the fields the request set into ``target`` and returns them."""
    given = overrides.model_dump(exclude_none=True)
    target.update(given)
    return given


def _check_ceilings(
    section: str,
    given: dict[str, Any],
    names: tuple[str, ...],
    preset_settings: Any,
    server: dict[str, Any],
    *,
    own_key: bool,
    preset: str,
) -> None:
    """Refuses a budget above what this caller may ask for.

    With the caller's own key the ceiling is the most generous preset's value;
    on the free tier it is the chosen preset's own.
    """
    for name in names:
        if name not in given:
            continue
        own = getattr(preset_settings, name)
        ceiling = max(server.get(name, own), own) if own_key else own
        if given[name] > ceiling:
            whose = "the server's maximum" if own_key else f"preset {preset!r}"
            raise OverrideError(f"{section}.{name} cannot exceed {ceiling}, {whose}")


def _channels(base: PipelineConfig, kinds: list[str], *, own_key: bool) -> list[dict[str, Any]]:
    """The requested channels, keeping the preset's own settings where it has them."""
    own = {channel.kind: channel for channel in base.channels}
    chosen: list[dict[str, Any]] = []
    for kind in dict.fromkeys(kinds):
        if kind in own:
            chosen.append(own[kind].model_dump(mode="json"))
            continue
        if not own_key:
            raise OverrideError(
                f"channel {kind!r} cannot be added to preset {base.name!r} on the free tier"
            )
        if kind not in CHANNEL_CATALOGUE:
            raise OverrideError(f"channel {kind!r} is not available")
        chosen.append(CHANNEL_CATALOGUE[kind].model_dump(mode="json"))
    return chosen


def apply_overrides(
    base: PipelineConfig, overrides: Overrides | None, *, own_key: bool = False
) -> PipelineConfig:
    """The preset with the request's overrides applied.

    Args:
        base: The preset.
        overrides: The validated overrides, if the request sent any.
        own_key: Whether the run is on the caller's own key. Without one, a
            request may only make the run cheaper.

    Returns:
        A new, fully validated configuration; ``base`` when nothing was sent.

    Raises:
        OverrideError: When an override asks for more than this caller may,
            targets settings the preset does not have, or produces a
            configuration that does not validate.
    """
    if overrides is None:
        return base
    data = base.model_dump(mode="json")

    if overrides.agent is not None:
        if base.agent is None:
            raise OverrideError(f"preset {base.name!r} has no agent settings to override")
        given = _set_fields(data["agent"], overrides.agent)
        _check_ceilings(
            "agent",
            given,
            _AGENT_CEILINGS,
            base.agent,
            SERVER_AGENT_CEILINGS,
            own_key=own_key,
            preset=base.name,
        )
        if given.get("seed") and not base.agent.seed and not own_key:
            raise OverrideError(f"agent.seed cannot be switched on for preset {base.name!r}")

    if overrides.planner is not None:
        if base.planner is None:
            raise OverrideError(f"preset {base.name!r} has no planner settings to override")
        given = _set_fields(data["planner"], overrides.planner)
        _check_ceilings(
            "planner",
            given,
            _PLANNER_CEILINGS,
            base.planner,
            SERVER_PLANNER_CEILINGS,
            own_key=own_key,
            preset=base.name,
        )

    if overrides.checks is not None:
        given = _set_fields(data["checks"], overrides.checks)
        if not own_key:
            for name in _CHECK_FLAGS:
                if given.get(name) and not getattr(base.checks, name):
                    raise OverrideError(
                        f"checks.{name} cannot be switched on for preset {base.name!r} "
                        "on the free tier"
                    )

    if overrides.query is not None:
        given = _set_fields(data["query"], overrides.query)
        transform = given.get("transform")
        if transform not in (None, "identity", base.query.transform) and not own_key:
            raise OverrideError(f"query.transform {transform!r} is not available on the free tier")

    if overrides.rerank is not None:
        given = _set_fields(data["rerank"], overrides.rerank)
        kind = given.get("kind")
        if kind not in (None, "none", base.rerank.kind) and not own_key:
            raise OverrideError(f"rerank.kind {kind!r} is not available on the free tier")

    if overrides.channels is not None:
        data["channels"] = _channels(base, list(overrides.channels), own_key=own_key)
        if len(data["channels"]) > 1:
            data["fusion"] = "rrf"

    if overrides.diversify is not None:
        _set_fields(data["diversify"], overrides.diversify)

    try:
        return PipelineConfig.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(map(str, first["loc"]))
        message = first["msg"].removeprefix("Value error, ")
        raise OverrideError(f"{location}: {message}" if location else message) from error
