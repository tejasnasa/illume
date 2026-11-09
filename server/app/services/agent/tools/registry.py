"""The tool registry: typed tools, their model-facing schemas, and a safe way to call them.

A tool is a Pydantic input model, a handler and a Pydantic output model. The
registry renders the set of tools as Responses API function tools, validates a
call's arguments before the handler sees them, and runs the handler under a
timeout. Nothing a tool can do wrong is raised to the caller: a bad argument, a
timeout and a crash all come back as a :class:`ToolResult` the model can read.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.services.agent.tools.context import NodeEvent, ToolContext
from app.services.agent.tools.output import ToolOutput, cap_text

logger = logging.getLogger(__name__)

Cost = Literal["none", "free", "cheap", "network", "model"]

ResultStatus = Literal["ok", "invalid_arguments", "timeout", "error", "unknown_tool"]


def _allows_none(annotation: Any) -> bool:
    return annotation is type(None) or type(None) in get_args(annotation)


class ToolInput(BaseModel):
    """Base of every tool's arguments.

    Unknown arguments are rejected. A ``null`` for an argument that has a default
    and does not accept ``None`` counts as omitted, because strict schemas make
    the model write ``null`` for every optional argument it leaves out.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _null_means_omitted(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {
            name: value
            for name, value in data.items()
            if value is not None
            or (info := cls.model_fields.get(name)) is None
            or _allows_none(info.annotation)
        }


class ToolResult(BaseModel):
    """What came back from one call, in the shapes both readers need.

    Attributes:
        tool: The tool name.
        status: ``ok``, or why the call produced no output.
        text: What the model is shown, capped at the result limit.
        data: The output as JSON for the step log; ``None`` unless ``ok``.
        truncated: Whether ``text`` was cut to the limit.
        elapsed_ms: Wall time of the call.
        nodes: Files to highlight in the graph, when the tool names any.
        error_type: The exception class, when the handler raised one.
    """

    tool: str
    status: ResultStatus
    text: str
    data: dict[str, Any] | None = None
    truncated: bool = False
    elapsed_ms: float = 0.0
    nodes: NodeEvent | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class Tool[In: ToolInput, Out: ToolOutput]:
    """One capability the agent can use.

    Attributes:
        name: The function name the model calls.
        description: Written for the model: what the tool does, when to use it,
            and what it cannot do.
        input_model: The arguments.
        output_model: The result.
        handler: Does the work. Opens its own session from the context.
        cost: What a call spends: ``free`` is a database read, ``network`` a
            GitHub request, ``model`` an embedding or generation call.
        timeout_s: Wall-clock limit for the handler.
        expose_to_agent: Whether the model is offered the tool.
        emits_nodes: Names the files a result touched, for the graph.
    """

    name: str
    description: str
    input_model: type[In]
    output_model: type[Out]
    handler: Callable[[ToolContext, In], Awaitable[Out]]
    cost: Cost
    timeout_s: float
    expose_to_agent: bool = True
    emits_nodes: Callable[[Out], NodeEvent | None] | None = None


# --- schemas ------------------------------------------------------------------

# Keywords that strict mode rejects or that only describe a default.
_DROPPED_KEYWORDS = frozenset({"default", "title"})
_NAMED_SCHEMAS = frozenset({"properties", "$defs"})


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """The same schema, also accepting ``null``."""
    if "anyOf" in schema:
        if any(branch.get("type") == "null" for branch in schema["anyOf"]):
            return schema
        return {**schema, "anyOf": [*schema["anyOf"], {"type": "null"}]}
    if "type" in schema and "$ref" not in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        widened = {**schema, "type": [*kinds, "null"] if "null" not in kinds else kinds}
        if "enum" in widened and None not in widened["enum"]:
            widened["enum"] = [*widened["enum"], None]
        return widened
    return {"anyOf": [schema, {"type": "null"}]}


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED_KEYWORDS:
            continue
        if key in _NAMED_SCHEMAS and isinstance(value, dict):
            # The keys here are names chosen by the tool, not schema keywords.
            out[key] = {name: _strict(sub) for name, sub in value.items()}
        else:
            out[key] = _strict(value)

    properties = out.get("properties")
    if isinstance(properties, dict):
        required = set(node.get("required", ()))
        for name, sub in properties.items():
            if name not in required:
                properties[name] = _nullable(sub)
        out["required"] = list(properties)
        out["additionalProperties"] = False
    return out


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrites a JSON schema into the shape OpenAI strict mode accepts.

    Every object lists all its properties as required and forbids extras; a
    property that was optional becomes one that may be ``null`` instead, so the
    model states "not given" rather than leaving the key out. ``default`` and
    ``title`` keywords are dropped.
    """
    return _strict(copy.deepcopy(schema))


# --- argument errors ------------------------------------------------------------


def _describe_error(error: Mapping[str, Any]) -> str:
    name = ".".join(str(part) for part in error["loc"]) or "arguments"
    kind = error["type"]
    context = error.get("ctx") or {}
    got = ""
    if "input" in error and kind != "missing":
        shown = repr(error["input"])
        got = f" (got {shown if len(shown) <= 60 else shown[:57] + '...'})"

    if kind == "missing":
        return f"argument `{name}` is required"
    if kind == "extra_forbidden":
        return f"`{name}` is not an argument of this tool"
    if kind == "greater_than_equal":
        return f"argument `{name}` must be at least {context.get('ge')}{got}"
    if kind == "less_than_equal":
        return f"argument `{name}` must be at most {context.get('le')}{got}"
    if kind == "string_too_short":
        return f"argument `{name}` must be at least {context.get('min_length')} characters{got}"
    if kind == "string_too_long":
        return f"argument `{name}` must be at most {context.get('max_length')} characters{got}"
    return f"argument `{name}`: {error['msg']}{got}"


def describe_validation_error(error: ValidationError) -> str:
    """A readable account of why arguments were refused."""
    problems = [_describe_error(e) for e in error.errors(include_url=False)]
    return "The arguments were not valid: " + "; ".join(problems) + ". Fix them and call again."


# --- the registry -----------------------------------------------------------------


class ToolRegistry:
    """The set of tools, in registration order."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any, Any]] = {}

    def register(self, tool: Tool[Any, Any]) -> None:
        """Adds a tool.

        Raises:
            ValueError: When a tool with the same name is already registered.
        """
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any, Any]:
        """The tool called ``name``.

        Raises:
            KeyError: When there is none.
        """
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(
                f"no tool named {name!r}; registered: {', '.join(self._tools)}"
            ) from None

    def names(self) -> list[str]:
        """Every registered name, in registration order."""
        return list(self._tools)

    def __iter__(self) -> Iterator[Tool[Any, Any]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def function_tools(
        self, allowlist: Iterable[str] | None = None, *, strict: bool = False
    ) -> list[dict[str, Any]]:
        """The tools as Responses API function tool definitions.

        Args:
            allowlist: Names to offer; ``None`` offers every tool marked for the agent.
            strict: Send strict schemas. Only for a provider that enforces them,
                see ``LLMConfig.supports_strict_tools``; others get the plain schema.

        Raises:
            KeyError: When the allowlist names a tool that does not exist.
        """
        if allowlist is None:
            chosen: Sequence[Tool[Any, Any]] = [t for t in self if t.expose_to_agent]
        else:
            chosen = [self.get(name) for name in dict.fromkeys(allowlist)]
        definitions = []
        for tool in chosen:
            schema = tool.input_model.model_json_schema()
            definitions.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": strict_schema(schema) if strict else schema,
                    "strict": strict,
                }
            )
        return definitions

    async def call(
        self, name: str, arguments: str | dict[str, Any] | None, ctx: ToolContext
    ) -> ToolResult:
        """Runs one tool call and always returns a result.

        The arguments are validated first; the handler then runs under
        ``tool.timeout_s``. A bad argument, a timeout and an unexpected failure
        each become a result with an explanatory ``text`` for the model.

        Args:
            name: The tool the model asked for.
            arguments: The model's arguments, as the JSON text it wrote or a dict.
            ctx: The call's context.
        """
        started = time.perf_counter()

        def result(status: ResultStatus, text: str, **extra: Any) -> ToolResult:
            elapsed = (time.perf_counter() - started) * 1000
            return ToolResult(
                tool=name, status=status, text=text, elapsed_ms=round(elapsed, 2), **extra
            )

        if name not in self._tools:
            return result(
                "unknown_tool",
                f"There is no tool named `{name}`. Available tools: {', '.join(self._tools)}.",
            )
        tool = self._tools[name]

        raw: Any = arguments
        if isinstance(arguments, str):
            try:
                raw = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as error:
                return result(
                    "invalid_arguments", f"The arguments were not valid JSON ({error.msg})."
                )
        elif arguments is None:
            raw = {}
        if not isinstance(raw, dict):
            return result("invalid_arguments", "The arguments must be a JSON object.")

        try:
            parsed = tool.input_model.model_validate(raw)
        except ValidationError as error:
            return result("invalid_arguments", describe_validation_error(error))

        try:
            timeout = asyncio.timeout(tool.timeout_s)
            try:
                async with timeout:
                    output = await tool.handler(ctx, parsed)
            except TimeoutError:
                if not timeout.expired():
                    raise
                return result(
                    "timeout",
                    f"`{name}` did not finish within {tool.timeout_s:g} seconds. "
                    "Try narrower arguments, or a different tool.",
                )
        except Exception as error:
            logger.exception("tool %s failed", name)
            return result(
                "error",
                f"`{name}` failed with an internal error ({type(error).__name__}). "
                "Try different arguments, or a different tool.",
                error_type=type(error).__name__,
            )

        text, truncated = cap_text(output.render())
        nodes = None
        if tool.emits_nodes is not None:
            try:
                nodes = tool.emits_nodes(output)
            except Exception:
                logger.warning("tool %s could not name its nodes", name, exc_info=True)
        return result(
            "ok",
            text,
            data=output.model_dump(mode="json"),
            truncated=truncated,
            nodes=nodes,
        )


REGISTRY = ToolRegistry()


def function_tools(
    allowlist: Iterable[str] | None = None, *, strict: bool = False
) -> list[dict[str, Any]]:
    """:meth:`ToolRegistry.function_tools` on the shared registry."""
    return REGISTRY.function_tools(allowlist, strict=strict)
