"""The step log: what a run did, in order, in a form a replay can read.

A step is one thing the run did: a model call, a tool call, a decision, the
seed retrieval. :class:`StepRecorder` is where steps go. The default,
:class:`InMemorySteps`, keeps them in a list; a persistent recorder implements
the same two methods. Steps are written as they happen, so a run that fails
part-way still leaves the steps it took.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.services.agent.runner import RunResult

StepKind = Literal[
    "seed",
    "plan",
    "worker",
    "merge",
    "model_call",
    "tool_call",
    "decision",
    "gate",
    "compact",
    "synthesize",
    "verify",
    "error",
]


@dataclass(frozen=True)
class StepRecord:
    """One recorded step.

    Attributes:
        index: Position in the run, from zero, in the order steps were started.
        kind: What kind of step it was.
        node: The graph node it ran in.
        payload: The step's JSON-serialisable details.
        worker_id: The worker that took it, or ``None`` for the main agent.
        duration_ms: Wall time of the step.
    """

    index: int
    kind: StepKind
    node: str
    payload: dict[str, Any]
    worker_id: str | None = None
    duration_ms: float = 0.0


class StepRecorder(Protocol):
    """Where a run writes its steps and its outcome."""

    async def record(self, step: StepRecord) -> None:
        """Stores one step."""
        ...

    async def finish(self, result: RunResult) -> None:
        """Stores how the run ended."""
        ...


@dataclass
class InMemorySteps:
    """A recorder that keeps everything in lists.

    Attributes:
        steps: The recorded steps, in the order they were written.
        result: How the run ended, once it has.
    """

    steps: list[StepRecord] = field(default_factory=list)
    result: RunResult | None = None

    async def record(self, step: StepRecord) -> None:
        """Stores one step."""
        self.steps.append(step)

    async def finish(self, result: RunResult) -> None:
        """Stores how the run ended."""
        self.result = result

    def of_kind(self, kind: StepKind) -> list[StepRecord]:
        """The steps of one kind, in order."""
        return [step for step in self.steps if step.kind == kind]
