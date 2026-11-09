"""A scripted stand-in for the model, and the helpers an agent run needs.

:class:`ScriptedModel` replays fixed Responses API outputs, one per model call,
and records every request it receives, verbatim. A test therefore asserts both
what the agent did and what it sent. It answers the way the real client does
when asked to stream: text deltas first, then a final event carrying the whole
response, built from the SDK's own ``Response`` type so that the agent reads
the same fields it would read from a provider.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from openai.types.responses import Response

from app.services.decisions.base import NoulResult
from app.services.retrieval.config import (
    HYBRID,
    AgentConfig,
    PipelineConfig,
    PlannerConfig,
    QueryConfig,
)

DEFAULT_INPUT_TOKENS = 100
DEFAULT_OUTPUT_TOKENS = 20


# --- output items -----------------------------------------------------------------

_call_ids = itertools.count(1)


def call(name: str, arguments: Any = None, *, call_id: str | None = None):
    """A function call output item, as a provider returns it.

    A dict is serialised to JSON; a string is sent as the model wrote it, which
    is how a test sends malformed arguments.
    """
    import json

    number = next(_call_ids)
    return {
        "type": "function_call",
        "id": f"fc_{number}",
        "call_id": call_id or f"call_{number}",
        "name": name,
        "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments or {}),
        "status": "completed",
    }


def finish(answer: str, note: str | None = None, *, call_id: str | None = None):
    """A ``finish`` call."""
    arguments: dict[str, Any] = {"answer": answer}
    if note is not None:
        arguments["confidence_note"] = note
    return call("finish", arguments, call_id=call_id)


def plan_reply(subquestions: Sequence[dict[str, str]], hint: str = "") -> Turn:
    """A reply to the structured plan call."""
    return turn(message(json.dumps({"subquestions": list(subquestions), "synthesis_hint": hint})))


def message(text: str) -> dict[str, Any]:
    """An assistant message output item."""
    return {
        "type": "message",
        "id": f"msg_{next(_call_ids)}",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def reasoning(identifier: str = "rs_1") -> dict[str, Any]:
    """A reasoning output item, which must be sent back unchanged."""
    return {"type": "reasoning", "id": identifier, "summary": []}


@dataclass
class Turn:
    """One scripted model reply.

    Attributes:
        output: The output items.
        input_tokens: The input tokens the reply reports.
        output_tokens: The output tokens the reply reports.
        error: Raised from the call instead of replying.
        before: Awaited before replying, to hold the call or change the world.
        status: The response status.
        stall_after_text: Stream the text, then never finish the response.
    """

    output: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = DEFAULT_INPUT_TOKENS
    output_tokens: int = DEFAULT_OUTPUT_TOKENS
    error: BaseException | None = None
    before: Callable[[], Awaitable[None]] | None = None
    status: str = "completed"
    stall_after_text: bool = False


def turn(*output: dict[str, Any], **fields: Any) -> Turn:
    """A reply made of the given output items."""
    return Turn(output=list(output), **fields)


def say(text: str, **fields: Any) -> Turn:
    """A reply that is only text."""
    return Turn(output=[message(text)], **fields)


def build_response(reply: Turn) -> Response:
    """The SDK ``Response`` for a scripted reply."""
    return Response.model_validate(
        {
            "id": f"resp_{uuid.uuid4().hex[:8]}",
            "created_at": 0.0,
            "model": "test-model",
            "object": "response",
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "output": reply.output,
            "status": reply.status,
            "usage": {
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "total_tokens": reply.input_tokens + reply.output_tokens,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
    )


class ScriptedModel:
    """Replays scripted replies and records the requests.

    Every call to ``responses.create`` takes the next scripted reply. When the
    script runs out the call raises, unless ``repeat`` is given, in which case
    it supplies a reply from the call's number.

    Attributes:
        requests: A deep copy of every request's keyword arguments, in order.
        client_inits: The keyword arguments of every client built.
    """

    def __init__(
        self,
        script: Sequence[Turn] = (),
        *,
        repeat: Callable[[int], Turn] | None = None,
    ) -> None:
        self._script = list(script)
        self._repeat = repeat
        self.requests: list[dict[str, Any]] = []
        self.client_inits: list[dict[str, Any]] = []
        self.responses = self

    def factory(self, **kwargs: Any) -> SimpleNamespace:
        """A client factory: records the client arguments and returns this model."""
        self.client_inits.append(kwargs)
        return SimpleNamespace(responses=self)

    @property
    def agent_requests(self) -> list[dict[str, Any]]:
        """The requests that offered tools: the agent's turns."""
        return [request for request in self.requests if request.get("tools")]

    @property
    def synthesis_requests(self) -> list[dict[str, Any]]:
        """The requests that offered no tools: the closing answer."""
        return [request for request in self.requests if not request.get("tools")]

    def input_texts(self, index: int) -> list[str]:
        """Every string in one request's input, for substring assertions."""
        found: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, str):
                found.append(value)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self.requests[index]["input"])
        return found

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(copy.deepcopy(kwargs))
        number = len(self.requests)
        if self._script:
            reply = self._script.pop(0)
        elif self._repeat is not None:
            reply = self._repeat(number)
        else:
            raise AssertionError(f"the script has no reply for model call {number}")
        if reply.before is not None:
            await reply.before()
        if reply.error is not None:
            raise reply.error
        return self._events(reply)

    async def _events(self, reply: Turn):
        yield SimpleNamespace(type="response.created")
        for item in reply.output:
            if item.get("type") != "message":
                continue
            for content in item["content"]:
                text = content["text"]
                for start in range(0, len(text), 7):
                    yield SimpleNamespace(
                        type="response.output_text.delta", delta=text[start : start + 7]
                    )
        if reply.stall_after_text:
            await never()
        yield SimpleNamespace(type="response.completed", response=build_response(reply))


# A phrase from the merge prompt that no other request carries.
MERGE_MARKER = "combining the findings of several investigators"


class RoutedModel(ScriptedModel):
    """A scripted model that answers each branch of a parallel run differently.

    With workers running at once, one ordered script would make a test depend on
    which worker reached the model first. This model picks the reply from what
    the request is: the structured plan call, one of the workers (by the
    sub-question in its input), the merge call, or the single agent when
    planning was skipped.

    Attributes:
        requests: A deep copy of every request's keyword arguments, in order.
        tags: One tag per request: ``planner``, ``merge``, ``worker:<id>`` or
            ``fallback``.
    """

    def __init__(
        self,
        *,
        planner: Turn | None = None,
        merge: Turn | None = None,
        workers: Mapping[str, Sequence[Turn]] | None = None,
        fallback: Sequence[Turn] = (),
    ) -> None:
        self.planner = planner
        self.merge = merge
        self._workers = {key: list(script) for key, script in (workers or {}).items()}
        self._fallback = list(fallback)
        self.requests = []
        self.tags: list[str] = []
        self.client_inits: list[dict[str, Any]] = []
        self.responses = self

    def tagged(self, tag: str) -> list[dict[str, Any]]:
        """The requests one branch received, in order."""
        return [
            request for request, name in zip(self.requests, self.tags, strict=True) if name == tag
        ]

    def worker_requests(self, subquestion: str) -> list[dict[str, Any]]:
        """The requests one worker made."""
        return self.tagged(f"worker:{subquestion}")

    def _next(self, request: dict[str, Any]) -> tuple[str, Turn]:
        if "text" in request and self.planner is not None:
            return "planner", self.planner
        texts = _strings(request.get("input"))
        if self.merge is not None and any(MERGE_MARKER in text for text in texts):
            return "merge", self.merge
        matches = [key for key in self._workers if any(key in text for text in texts)]
        if matches:
            key = max(matches, key=len)
            script = self._workers[key]
            if not script:
                raise AssertionError(f"the script for {key!r} is used up")
            return f"worker:{key}", script.pop(0)
        if self._fallback:
            return "fallback", self._fallback.pop(0)
        raise AssertionError(f"no scripted reply for a request carrying {texts[-1][:120]!r}")

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(copy.deepcopy(kwargs))
        tag, reply = self._next(kwargs)
        self.tags.append(tag)
        if reply.before is not None:
            await reply.before()
        if reply.error is not None:
            raise reply.error
        if not kwargs.get("stream"):
            return build_response(reply)
        return self._events(reply)


def _strings(value: Any) -> list[str]:
    """Every string in a request value, for routing and substring assertions."""
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


# --- a decider that answers from a list -----------------------------------------------


class PlanDecider:
    """A decider whose probabilities come from a list, then repeat the last.

    Only the single-call ``noul`` path is answered, which is the one the planner
    asks.

    Attributes:
        calls: The state and instructions of every question asked.
    """

    kind = "fake"
    model_id = "fake-decider"

    def __init__(self, *probabilities: float, defaulted: bool = False) -> None:
        self._probabilities = list(probabilities) or [1.0]
        self.defaulted = defaulted
        self.calls: list[tuple[Any, str]] = []

    async def noul(self, state: Any, instructions: str) -> NoulResult:
        self.calls.append((state, instructions))
        probability = (
            self._probabilities.pop(0) if len(self._probabilities) > 1 else self._probabilities[0]
        )
        return NoulResult(
            noul=probability,
            confidence=0.9,
            latency_ms=1.0,
            model=self.model_id,
            provider="fake",
            defaulted=self.defaulted,
        )

    async def choice(self, state: Any, instructions: str, options: Any):
        raise AssertionError("the agent asks no choice questions")

    async def score(self, state: Any, instructions: str, levels: Any):
        raise AssertionError("the agent asks no score questions")

    async def batch(self, state: Any, questions: Any):
        raise AssertionError("the agent asks no batched questions")


# --- configuration -----------------------------------------------------------------------


def agent_config(
    *,
    seed: bool = True,
    tools: tuple[str, ...] | None = None,
    **limits: Any,
) -> PipelineConfig:
    """A pipeline configuration for agent execution over the retrieval fixture.

    It searches with the hybrid channels, so the seed needs no model key.

    Args:
        seed: Run the retrieval before the first model turn.
        tools: Restrict the tools offered.
        **limits: Overrides for the agent's limits.
    """
    return PipelineConfig(
        name="agent_test",
        query=QueryConfig(condense=False, history_messages=10),
        channels=HYBRID.channels,
        execution="agent",
        agent=AgentConfig(seed=seed, tools=tools, **limits),
    )


def planner_config(
    *,
    seed: bool = True,
    max_workers: int = 4,
    worker_iterations: int = 8,
    min_subquestions: int = 2,
    plan_threshold: float = 0.5,
    **limits: Any,
) -> PipelineConfig:
    """A pipeline configuration for parallel execution over the retrieval fixture.

    Args:
        seed: Run the retrieval before fanning out.
        max_workers: The most sub-questions a plan may hold.
        worker_iterations: Model turns per worker.
        min_subquestions: The fewest sub-questions worth fanning out.
        plan_threshold: The probability at which planning runs.
        **limits: Overrides for the agent's limits.
    """
    return PipelineConfig(
        name="planner_test",
        query=QueryConfig(condense=False, history_messages=10),
        channels=HYBRID.channels,
        execution="planner",
        agent=AgentConfig(seed=seed, **limits),
        planner=PlannerConfig(
            max_workers=max_workers,
            worker_iterations=worker_iterations,
            min_subquestions=min_subquestions,
            plan_threshold=plan_threshold,
        ),
    )


def with_hard_cancel(config: PipelineConfig, seconds: int) -> PipelineConfig:
    """The configuration with a hard cancel shorter than the validated minimum.

    Validation requires at least ten seconds; a test cannot wait that long, so
    this builds the agent settings without validating.
    """
    assert config.agent is not None
    return config.model_copy(
        update={"agent": config.agent.model_copy(update={"hard_cancel_seconds": seconds})}
    )


def serialized(factory: Any) -> Any:
    """A session factory whose sessions never overlap.

    Tests run on one database connection, which cannot serve two statements at
    once, while a real run gives every concurrent tool call a connection of its
    own. Holding a lock for the length of each session makes the shared
    connection safe; calls that do not touch the database still run together.
    """
    lock = asyncio.Lock()

    @asynccontextmanager
    async def open_session():
        async with lock:
            async with factory() as session:
                yield session

    return open_session


class FakeClock:
    """A monotonic clock a test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def never() -> None:
    """Waits until cancelled."""
    await asyncio.Event().wait()
