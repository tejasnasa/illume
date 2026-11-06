"""The events a run emits while it works.

An event is a name and a JSON-serialisable payload, delivered to an
:data:`~app.services.retrieval.channels.base.Emit` callable. The runner knows
nothing about who is listening: a streaming route turns events into frames, the
evaluation ignores them, and a test collects them in an :class:`EventLog`.
Events describe progress and never carry the only copy of anything; the answer
and the step log are returned and recorded separately.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from app.services.retrieval.channels.base import Emit

logger = logging.getLogger(__name__)


class Event(StrEnum):
    """The names of the events a run emits.

    Attributes:
        RUN_STARTED: The run began. Carries the run id, model and limits.
        NODE: A graph node started or finished (``phase``).
        ROUTE: The routing decision that chose this graph.
        SEED: Retrieval results were put in front of the agent.
        THINKING: A piece of the model's interim text.
        MODEL_CALL: One model call finished, with its token usage.
        TOOL_CALL: A tool call is about to run.
        TOOL_RESULT: A tool call finished, with its status.
        NODES: Files a tool looked at, for highlighting in the graph.
        EVIDENCE: New citable evidence was gathered.
        GATE: The sufficiency check answered.
        COMPACTED: Older tool results were replaced with stubs so the next
            model call fits the context window.
        ANSWER_DELTA: A piece of the answer being written.
        ANSWER: The final answer.
        DEGRADED: Something worked with less than asked: a limit was reached or
            a model-backed stage fell back.
        ERROR: The run failed.
        RUN_FINISHED: The run ended, however it ended.
    """

    RUN_STARTED = "run_started"
    NODE = "node"
    ROUTE = "route"
    SEED = "seed"
    THINKING = "thinking"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    NODES = "nodes"
    EVIDENCE = "evidence"
    GATE = "gate"
    COMPACTED = "compacted"
    ANSWER_DELTA = "answer_delta"
    ANSWER = "answer"
    DEGRADED = "degraded"
    ERROR = "error"
    RUN_FINISHED = "run_finished"


async def safe_emit(emit: Emit, event: str, payload: dict[str, Any]) -> None:
    """Emits an event, absorbing a failing listener.

    A listener that raises, such as a closed connection, must not fail a run
    that is otherwise fine.
    """
    try:
        await emit(event, payload)
    except Exception:
        logger.warning("emitting %s failed", event, exc_info=True)


class EventLog:
    """An emitter that keeps every event in memory."""

    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event: str, payload: dict[str, Any]) -> None:
        self.items.append((event, payload))

    def named(self, event: str) -> list[dict[str, Any]]:
        """The payloads of one kind of event, in order."""
        return [payload for name, payload in self.items if name == event]

    def names(self) -> list[str]:
        """Every event name, in order."""
        return [name for name, _ in self.items]
