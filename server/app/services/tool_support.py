"""Record whether a credential can call function tools.

Generation only needs text output, and a key that produces text is valid. The
agent additionally needs function calling, and providers differ: some accept
``tool_choice: "required"`` and return a ``function_call`` item, others ignore
the field or reject it outright. A credential that fails the tool probe must
not be rejected at save time -- it is still a working key -- so the answer is
recorded on the user row and the agent presets read it instead of discovering
the limitation mid-run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

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
_PROBE_MAX_OUTPUT_TOKENS = 16


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
            tool_choice="required",
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
    if user.ai_supports_tools is not None:
        return user.ai_supports_tools

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
