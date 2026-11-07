"""Screening repository text for instructions aimed at the model.

Every successful tool result that carries repository text is screened once per
tools-node round, and so are the retrieval results put in front of the agent
before its first turn. Each ``<source>`` block is judged on its own, so one
poisoned file withholds that file and not the clean results beside it; a result
with no blocks is judged whole. All of a round's texts go to the decision model
in one batched request, so a turn of ten tool calls costs one screening request,
not ten.

A block whose text clears the threshold is replaced, in what the model sees,
with a quarantine block::

    <quarantined key="F:app/auth/security.py:4-8" p="0.83">This content was
    withheld because it appears to contain instructions aimed at an AI assistant.</quarantined>

The original text is kept for the step log and the timeline, never shown to the
model. A failed or unusable decision quarantines too: text nobody could screen is
not text that has been cleared.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.agent.events import Event
from app.services.agent.tools.registry import ToolResult
from app.services.decisions import (
    Decider,
    Question,
    RecordDecision,
    Result,
    record_decision,
)
from app.services.decisions.points import (
    InjectionDecision,
    injection_decision,
    injection_question,
    injection_state,
)

if TYPE_CHECKING:
    from app.services.agent.deps import AgentDeps

logger = logging.getLogger(__name__)

_GUARD_STATE = "Repository text returned by an agent's tools, one injection check per question."

# One fenced block. The fencing escapes a closing tag inside the text, so the
# first closing tag after an opening one always ends that block.
_SOURCE_BLOCK = re.compile(r'<source key="(?P<key>[^"]*)"[^>]*>.*?</source>', re.DOTALL)

QUARANTINE_REASON = (
    "This content was withheld because it appears to contain instructions aimed at an AI assistant."
)


@dataclass(frozen=True)
class Quarantine:
    """Text withheld from one tool result.

    Attributes:
        tool: The tool that produced it.
        key: The first withheld citation key, or ``tool:<name>`` when the result
            carried no blocks and was withheld whole.
        keys: Every withheld citation key, in order.
        probability: The highest probability, among the withheld texts, that
            the text was an injection attempt.
        original: The text as the tool produced it, for the step log only.
    """

    tool: str
    key: str
    keys: tuple[str, ...]
    probability: float
    original: str


@dataclass(frozen=True)
class ScreenOutcome:
    """What screening a round of tool results produced.

    Attributes:
        results: The results in the order they arrived, with withheld text
            replaced by the block the model may see.
        quarantines: One entry per result, ``None`` when nothing in that result
            was withheld.
    """

    results: tuple[ToolResult, ...]
    quarantines: tuple[Quarantine | None, ...]


RoundScreen = Callable[[Sequence[ToolResult]], Awaitable[ScreenOutcome]]
"""Screens every result of one tools-node round, in one batch."""


def quarantine_block(key: str, probability: float) -> str:
    """The text shown to the model in place of withheld repository text."""
    safe = key.replace('"', "&quot;").replace("<", "&lt;")
    return f'<quarantined key="{safe}" p="{probability:.2f}">{QUARANTINE_REASON}</quarantined>'


def _screened(result: ToolResult) -> bool:
    """Whether a result carries repository text that must be screened."""
    return result.status == "ok" and result.carries_repo_text and bool(result.text.strip())


@dataclass(frozen=True)
class _Piece:
    """One stretch of text judged on its own: a fenced block, or a whole result."""

    owner: int
    key: str | None
    start: int
    end: int
    text: str


def _pieces(owner: int, text: str) -> list[_Piece]:
    """The fenced blocks of ``text``, or the whole of it when it has none."""
    blocks = [
        _Piece(
            owner=owner,
            key=match.group("key").replace("&quot;", '"').replace("&lt;", "<"),
            start=match.start(),
            end=match.end(),
            text=match.group(0),
        )
        for match in _SOURCE_BLOCK.finditer(text)
    ]
    return blocks or [_Piece(owner=owner, key=None, start=0, end=len(text), text=text)]


async def judge_texts(
    texts: Sequence[str],
    decider: Decider | None,
    *,
    threshold: float,
    record: RecordDecision | None = None,
    on_degraded: Callable[[str], Awaitable[None]] | None = None,
) -> list[InjectionDecision]:
    """Judges each text for injected instructions, in one batched request.

    Text that could not be judged, because there is no decider, the request
    failed or the answer was unusable, is judged suspicious.

    Args:
        texts: The texts to judge.
        decider: Who judges them.
        threshold: The probability at or above which text is suspicious.
        record: Where decision records go, when the caller keeps them.
        on_degraded: Reports a screening outage, when the caller wants an event.

    Returns:
        One decision per text, in order.
    """
    if not texts:
        return []
    questions: dict[str, Question] = {
        f"text{index}": injection_question(text) for index, text in enumerate(texts)
    }
    answers: Mapping[str, Result] = {}
    if decider is None:
        if on_degraded is not None:
            await on_degraded("no decider is available")
    else:
        try:
            answers = await decider.batch(_GUARD_STATE, questions)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"[:300]
            logger.warning("screening repository text failed closed: %s", reason)
            if on_degraded is not None:
                await on_degraded(reason)

    decisions: list[InjectionDecision] = []
    for index, text in enumerate(texts):
        answer = answers.get(f"text{index}")
        if answer is not None and record is not None:
            await record_decision(record, "injection", injection_state(text), answer)
        decisions.append(injection_decision(answer, threshold=threshold))
    return decisions


async def screen_round(
    results: Sequence[ToolResult],
    decider: Decider | None,
    *,
    threshold: float,
    record: RecordDecision | None = None,
    on_degraded: Callable[[str], Awaitable[None]] | None = None,
) -> ScreenOutcome:
    """Screens one round of tool results, replacing withheld text.

    Args:
        results: The round's results, in call order.
        decider: Who judges the text; ``None`` withholds all repository text.
        threshold: The probability at or above which text is withheld.
        record: Where decision records go, when the caller keeps them.
        on_degraded: Reports a screening outage, when the caller wants an event.

    Returns:
        The results to show the model, and one quarantine record per result
        that had anything withheld.
    """
    pieces = [
        piece
        for index, result in enumerate(results)
        if _screened(result)
        for piece in _pieces(index, result.text)
    ]
    decisions = await judge_texts(
        [piece.text for piece in pieces],
        decider,
        threshold=threshold,
        record=record,
        on_degraded=on_degraded,
    )

    withheld: dict[int, list[tuple[_Piece, InjectionDecision]]] = {}
    for piece, decision in zip(pieces, decisions, strict=True):
        if decision.suspicious:
            withheld.setdefault(piece.owner, []).append((piece, decision))

    shown = list(results)
    quarantines: list[Quarantine | None] = [None] * len(results)
    for index, flagged in withheld.items():
        result = results[index]
        text = result.text
        for piece, decision in sorted(flagged, key=lambda item: item[0].start, reverse=True):
            block = quarantine_block(piece.key or f"tool:{result.tool}", decision.probability)
            text = text[: piece.start] + block + text[piece.end :]
        keys = tuple(piece.key for piece, _ in flagged if piece.key is not None)
        shown[index] = result.model_copy(update={"text": text})
        quarantines[index] = Quarantine(
            tool=result.tool,
            key=keys[0] if keys else f"tool:{result.tool}",
            keys=keys,
            probability=max(decision.probability for _, decision in flagged),
            original=result.text,
        )

    return ScreenOutcome(tuple(shown), tuple(quarantines))


def build_guard(deps: AgentDeps) -> RoundScreen:
    """The run's injection screen, bound to its decider, threshold and step log."""
    decider = deps.decider
    threshold = deps.config.checks.injection_threshold
    record = deps.decision_sink("guard")

    async def screen(results: Sequence[ToolResult]) -> ScreenOutcome:
        async def degraded(reason: str) -> None:
            await deps.event(Event.DEGRADED, {"stage": "guard", "reason": reason})

        return await screen_round(
            results, decider, threshold=threshold, record=record, on_degraded=degraded
        )

    return screen
