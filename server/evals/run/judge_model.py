"""The judge as DeepEval sees it: one model that every call goes through a metered client.

DeepEval's metrics make several model calls each (claims, verdicts, a score), sometimes at the
same time. :class:`MeteredJudgeModel` answers every one of them from the harness's own judge
endpoint, over the Responses API with a strict JSON schema or over chat completions asked for a
JSON object, and keeps the usage of each call so the caller can charge the budget and the meter.
One instance serves one metric measurement, so the usage it holds belongs to that measurement
alone.

The model is async only: the harness calls each metric's ``a_measure``, and the synchronous
``generate`` fails loudly rather than running a coroutine on a loop it does not own. It has no
``a_generate_raw_response``, so G-Eval takes its structured-output path instead of asking for log
probabilities.

Library code here takes nothing from ``evals.settings``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from openai import BadRequestError
from pydantic import BaseModel, ValidationError

from app.services.retrieval.llm_json import ModelFailure, parse_json, text_format
from evals.run.endpoint import JudgeEndpoint
from evals.run.metering import usage_from_response
from evals.run.records import Usage

CALL_TIMEOUT_SECONDS = 180.0
"""The longest one model call may take."""

_JSON_SUFFIX = (
    "\n\nReply with only one JSON object and no other text. It must match this JSON schema:\n"
)


class JudgeOutputError(ValueError):
    """The judge's output is not usable for the schema that was asked for."""


class JudgeModelError(RuntimeError):
    """The judge model was used in a way it does not support."""


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A pydantic JSON schema made acceptable to a strict structured-output endpoint.

    Every object closes to its declared properties, lists all of them as required and drops
    ``default``, which strict mode does not accept.

    Args:
        schema: A schema from ``model_json_schema()``.

    Returns:
        A new schema; the argument is left unchanged.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(child) for child in node]
        if not isinstance(node, dict):
            return node
        out = {key: walk(value) for key, value in node.items() if key != "default"}
        properties = out.get("properties")
        if out.get("type") == "object" or isinstance(properties, dict):
            out["additionalProperties"] = False
            out["required"] = list(properties or {})
        return out

    result: dict[str, Any] = walk(copy.deepcopy(schema))
    return result


def _number(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _chat_usage(response: Any, *, endpoint: JudgeEndpoint, latency_ms: float) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    cost = getattr(usage, "cost", None)
    return Usage(
        provider=endpoint.host,
        model=endpoint.model,
        kind="judge",
        input_tokens=_number(getattr(usage, "prompt_tokens", None)),
        cached_input_tokens=_number(getattr(details, "cached_tokens", None)),
        output_tokens=_number(getattr(usage, "completion_tokens", None)),
        reported_cost_usd=float(cost)
        if isinstance(cost, int | float) and not isinstance(cost, bool)
        else None,
        latency_ms=round(latency_ms, 2),
    )


class MeteredJudgeModel(DeepEvalBaseLLM):
    """A DeepEval judge model backed by the harness's metered client.

    Attributes:
        usages: One entry per call that reported usage, in call order.
        reported_models: The model names the provider reported answering.
        calls: How many calls were made, including ones that reported no usage.
        unmetered: How many calls came back without usage.
    """

    def __init__(self, client: Any, endpoint: JudgeEndpoint) -> None:
        """Builds the model over an already constructed client.

        Args:
            client: An ``AsyncOpenAI``-style client.
            endpoint: The judge endpoint; its model, host and API style are used.
        """
        self._client = client
        self.endpoint = endpoint
        self.usages: list[Usage] = []
        self.reported_models: set[str] = set()
        self.calls = 0
        self.unmetered = 0
        super().__init__(model=endpoint.model)

    def load_model(self, *args: Any, **kwargs: Any) -> Any:
        """The client DeepEval holds as ``self.model``."""
        return self._client

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        """The judge model id asked for."""
        return self.endpoint.model

    def generate(self, *args: Any, **kwargs: Any) -> str:
        """Not supported: the harness only runs metrics through ``a_measure``.

        Raises:
            JudgeModelError: Always.
        """
        raise JudgeModelError("the judge model is async only; call the metric's a_measure")

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any):
        """Answers one DeepEval prompt, as a validated ``schema`` instance when one is given.

        Args:
            prompt: The prompt DeepEval built.
            schema: The pydantic class DeepEval wants back, or ``None`` for plain text.
            **kwargs: Ignored options DeepEval may pass.

        Returns:
            An instance of ``schema``, or the reply text when no schema is given.

        Raises:
            JudgeOutputError: When the reply is not JSON that fits the schema.
        """
        self.calls += 1
        json_schema = strict_schema(schema.model_json_schema()) if schema is not None else None
        name = schema.__name__ if schema is not None else "reply"
        if self.endpoint.api_style == "chat":
            text = await self._chat(prompt, json_schema)
        else:
            text = await self._responses(prompt, name, json_schema)
        if schema is None:
            return text
        try:
            return schema.model_validate(parse_json(text))
        except (ModelFailure, ValidationError) as problem:
            raise JudgeOutputError(f"judge output unusable for {name}: {problem}"[:500]) from None

    def _record(self, usage: Usage | None, reported: Any) -> None:
        if isinstance(reported, str) and reported:
            self.reported_models.add(reported)
        if usage is None:
            self.unmetered += 1
        else:
            self.usages.append(usage)

    async def _responses(self, prompt: str, name: str, json_schema: dict[str, Any] | None) -> str:
        started = time.perf_counter()
        messages = [{"role": "user", "content": prompt}]
        extra: dict[str, Any] = (
            {} if json_schema is None else {"text": text_format(name, json_schema)}
        )
        try:
            async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                response = await self._client.responses.create(
                    model=self.endpoint.model, input=messages, **extra
                )
        except BadRequestError:
            if json_schema is None:
                raise
            plain = [{"role": "user", "content": prompt + _JSON_SUFFIX + json.dumps(json_schema)}]
            async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                response = await self._client.responses.create(
                    model=self.endpoint.model, input=plain
                )
        usage = usage_from_response(
            response,
            kind="judge",
            provider=self.endpoint.host,
            requested_model=self.endpoint.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        reported = usage.model if usage is not None else None
        if usage is not None:
            usage = usage.model_copy(update={"model": self.endpoint.model})
        self._record(usage, reported)
        return str(response.output_text or "")

    async def _chat(self, prompt: str, json_schema: dict[str, Any] | None) -> str:
        started = time.perf_counter()
        content = prompt if json_schema is None else prompt + _JSON_SUFFIX + json.dumps(json_schema)
        messages = [{"role": "user", "content": content}]
        extra: dict[str, Any] = (
            {} if json_schema is None else {"response_format": {"type": "json_object"}}
        )
        try:
            async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                response = await self._client.chat.completions.create(
                    model=self.endpoint.model, messages=messages, **extra
                )
        except BadRequestError:
            if not extra:
                raise
            async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                response = await self._client.chat.completions.create(
                    model=self.endpoint.model, messages=messages
                )
        choices = getattr(response, "choices", None) or []
        text = choices[0].message.content if choices else ""
        self._record(
            _chat_usage(
                response, endpoint=self.endpoint, latency_ms=(time.perf_counter() - started) * 1000
            ),
            getattr(response, "model", None),
        )
        return str(text or "")


__all__ = [
    "CALL_TIMEOUT_SECONDS",
    "JudgeModelError",
    "JudgeOutputError",
    "MeteredJudgeModel",
    "strict_schema",
]
