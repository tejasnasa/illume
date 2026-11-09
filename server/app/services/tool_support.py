"""Record whether a credential can call function tools.

Generation only needs text output, and a key that produces text is valid. The
agent additionally needs function calling, which it asks for with
``tool_choice: "auto"``. The probe asks the same way: some providers reject
``"required"`` outright (DeepSeek in thinking mode does) while calling tools
normally under ``"auto"``, so probing with ``"required"`` would report a working
model as unable to call tools. A credential that fails the tool probe must
not be rejected at save time -- it is still a working key -- so the answer is
recorded on the user row and the agent presets read it instead of discovering
the limitation mid-run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from openai import APIConnectionError, AsyncOpenAI, InternalServerError, RateLimitError
from openai.types.responses import FunctionToolParam
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.llm_config import LLMConfig

logger = logging.getLogger(__name__)

# The smallest function definition that forces a decision: no parameters, so a
# provider cannot fail the call on schema shape.
PING_TOOL: FunctionToolParam = {
    "type": "function",
    "name": "ping",
    "description": "Return pong. Used only to check that tools work.",
    "parameters": {"type": "object", "properties": {}},
    # The probe is about whether the provider accepts a tool at all, not about
    # schema strictness, so this does not opt into strict mode.
    "strict": False,
}

_PROBE_INPUT = "Call the ping tool."
# Reasoning models spend output tokens thinking before they call the tool; too
# small a cap ends the response before the call and reads as "no tools".
_PROBE_MAX_OUTPUT_TOKENS = 512

# A "no tools" verdict is measured again after this long, and any recorded
# before the probe last changed is not trusted at all: an earlier probe could
# answer "no" for models that call tools fine.
NEGATIVE_VERDICT_TTL = timedelta(days=1)
PROBE_REVISED_AT = datetime(2026, 11, 7, tzinfo=UTC)


async def check_tool_support(client: AsyncOpenAI, config: LLMConfig) -> bool | None:
    """Whether ``client`` can return a function call for ``config``'s model.

    Never raises: a provider that rejects ``tool_choice`` is answering the
    question (it does not support the feature), not failing the request that
    called this.

    Args:
        client: The already-configured client, sharing the save-time timeout and
            retry settings of the text probe.
        config: The credential whose model and reasoning extras are used.

    Returns:
        ``True`` only when the response contains a ``function_call`` item,
        ``False`` when the provider answered without one or refused the request,
        and ``None`` when no answer arrived (timeout, connection failure, rate
        limit, server error). ``None`` keeps the row unmeasured, so the lazy
        check retries it; a cached ``False`` would never be re-probed.
    """
    try:
        response = await client.responses.create(
            model=config.model,
            **config.response_kwargs("minimal"),
            input=_PROBE_INPUT,
            tools=[PING_TOOL],
            tool_choice="auto",
            max_output_tokens=_PROBE_MAX_OUTPUT_TOKENS,
        )
    except (APIConnectionError, RateLimitError, InternalServerError) as exc:
        # ``APITimeoutError`` subclasses ``APIConnectionError``. None of these
        # says anything about tools, so the verdict stays unmeasured.
        logger.info(
            "tool_support: probe got no answer from %s (%s): %s",
            config.model,
            type(exc).__name__,
            exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001 - the answer is "no", not a crash
        logger.info(
            "tool_support: probe rejected by %s (%s): %s",
            config.model,
            type(exc).__name__,
            exc,
        )
        return False

    return any(
        getattr(item, "type", None) == "function_call"
        for item in (getattr(response, "output", None) or [])
    )


def cached_tool_support(user: User, *, now: datetime | None = None) -> bool | None:
    """The recorded verdict, or ``None`` when it should be measured again.

    A ``True`` is kept. A ``False`` expires after :data:`NEGATIVE_VERDICT_TTL`
    and is discarded outright when it predates :data:`PROBE_REVISED_AT` or has
    no timestamp, so a model that gains tool calling, or one an older probe
    misjudged, is not locked out for good.

    Args:
        user: The owner of the credential.
        now: The current time, for tests.

    Returns:
        The trusted verdict, or ``None`` when there is none.
    """
    verdict = user.ai_supports_tools
    if verdict is not False:
        return verdict
    checked_at = user.ai_tools_checked_at
    if checked_at is None:
        return None
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    if checked_at < PROBE_REVISED_AT or now - checked_at > NEGATIVE_VERDICT_TTL:
        return None
    return False


async def ensure_tool_support(db: AsyncSession, user: User) -> bool | None:
    """Checks and caches tool support for a stored credential, at most once.

    Called on the first agent request for a user whose row predates the
    columns. Returns ``None`` when the user has no stored credential -- there is
    nothing to probe, and the free tier does not use agent presets.

    Args:
        db: Async session used to persist the result.
        user: The owner of the credential.

    Returns:
        The cached or newly measured support, or ``None`` for a keyless user
        or when the provider gave no answer this time.
    """
    cached = cached_tool_support(user)
    if cached is not None:
        return cached

    try:
        config = LLMConfig.from_user(user)
    except KeyError:
        # A stored provider that no longer maps to a preset is a stale row.
        # The agent path cannot use it either, but returning a measured answer
        # here would misreport the cause.
        logger.warning("tool_support: user %s has an unknown provider", user.id)
        return None
    if config is None:
        return None

    client = AsyncOpenAI(timeout=15, max_retries=0, **config.client_kwargs())
    supported = await check_tool_support(client, config)
    if supported is None:
        # No answer: leave the row unmeasured so the next request tries again.
        return None

    user.ai_supports_tools = supported
    user.ai_tools_checked_at = datetime.now(UTC)
    await db.commit()
    return supported
