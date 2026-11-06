"""One structured model call whose answer is JSON, shared by query rewriting and reranking.

Both callers want the same thing: ask the Responses API for a JSON value matching
a schema, and get back parsed data or a clear failure. Providers differ in how
well they honour ``json_schema``, so the call asks for it, retries without it
when the provider rejects it outright, and parses leniently either way.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, cast

from openai import AsyncOpenAI, BadRequestError
from openai.types.responses import ResponseInputParam

from app.services.llm_config import LLMConfig

# A provider that has not answered in this long is treated as failed rather than
# holding up the whole search.
CALL_TIMEOUT_SECONDS = 30.0

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)


class ModelFailure(Exception):
    """A model call that could not produce a usable result, with the reason."""


def text_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """The Responses ``text`` parameter that asks for JSON matching ``schema``."""
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": schema,
            "strict": True,
        }
    }


def parse_json(output: str) -> Any:
    """Parses model output as JSON, tolerating a code fence or surrounding prose.

    Raises:
        ModelFailure: When no JSON object or array can be found in the output.
    """
    text = (output or "").strip()
    if not text:
        raise ModelFailure("the model returned no text")
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # A provider that ignores json_schema may wrap the value in a sentence.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ModelFailure("the model's output was not valid JSON")


async def call_json(
    client: AsyncOpenAI,
    llm: LLMConfig,
    *,
    system: str,
    user: str,
    format_name: str,
    schema: dict[str, Any],
) -> Any:
    """One structured Responses call, returned as parsed JSON.

    Args:
        client: The client built from ``llm``.
        llm: The credential, model and reasoning support for the call.
        system: The system message.
        user: The user message.
        format_name: The name given to the ``json_schema`` format.
        schema: The JSON schema the answer should match.

    Raises:
        ModelFailure: On unusable output. Provider errors and timeouts propagate
            as the exceptions they are.
    """
    parsed, _ = await call_json_response(
        client, llm, system=system, user=user, format_name=format_name, schema=schema
    )
    return parsed


async def call_json_response(
    client: AsyncOpenAI,
    llm: LLMConfig,
    *,
    system: str,
    user: str,
    format_name: str,
    schema: dict[str, Any],
) -> tuple[Any, Any]:
    """:func:`call_json`, plus the provider's response for usage accounting.

    Returns:
        The parsed value and the raw response, so a caller that records tokens
        can read ``response.usage``.

    Raises:
        ModelFailure: On unusable output. Provider errors and timeouts propagate
            as the exceptions they are.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            response = await client.responses.create(
                model=llm.model,
                **llm.response_kwargs("minimal"),
                input=cast(ResponseInputParam, messages),
                text=cast(Any, text_format(format_name, schema)),
            )
    except BadRequestError:
        # Some providers reject ``json_schema`` outright rather than ignoring
        # it. Asking for the same JSON in the instructions, and parsing it
        # leniently, keeps the call working on them.
        plain = [
            {
                "role": "system",
                "content": (
                    f"{system}\n\nReply with only a JSON value matching this JSON "
                    f"schema, with no other text:\n{json.dumps(schema)}"
                ),
            },
            {"role": "user", "content": user},
        ]
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            response = await client.responses.create(
                model=llm.model,
                **llm.response_kwargs("minimal"),
                input=cast(ResponseInputParam, plain),
            )
    return parse_json(response.output_text), response
