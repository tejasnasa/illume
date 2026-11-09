"""The seed node: one retrieval before the first model turn.

The configured pipeline runs once on the question and its best results are put
in front of the agent, so it starts from what a single-shot answer would have
seen instead of from nothing. The seed is a head start, never a requirement: if
retrieval fails the agent begins without it.
"""

from __future__ import annotations

import logging
import time

from app.services.agent.deps import AgentDeps
from app.services.agent.events import Event
from app.services.agent.prompts import seed_message
from app.services.agent.state import AgentState, Evidence
from app.services.retrieval.candidate import Candidate
from app.services.retrieval.context import SOURCE_LABELS, render_block
from app.services.retrieval.pipeline import retrieve

logger = logging.getLogger(__name__)


async def _screen(deps: AgentDeps, candidates: list[Candidate], step: int) -> dict[str, str]:
    """Screens the retrieval results; returns the replacement text of each withheld one."""
    if not deps.config.checks.guard or not candidates:
        return {}

    async def degraded(reason: str) -> None:
        await deps.event(Event.DEGRADED, {"stage": "guard", "reason": reason})

    decisions = await judge_texts(
        [render_block(candidate) for candidate in candidates],
        deps.decider,
        threshold=deps.config.checks.injection_threshold,
        record=deps.decision_sink("guard"),
        on_degraded=degraded,
    )
    withheld: dict[str, str] = {}
    for candidate, decision in zip(candidates, decisions, strict=True):
        if not decision.suspicious:
            continue
        withheld[candidate.key] = quarantine_block(candidate.key, decision.probability)
        await deps.budget.note_quarantine()
        payload = {
            "tool": "seed",
            "key": candidate.key,
            "keys": [candidate.key],
            "probability": decision.probability,
            "step": step,
        }
        # The original goes to the step log only; the event never carries it.
        await deps.record("quarantine", "seed", {**payload, "text": candidate.text})
        await deps.event(Event.QUARANTINE, payload)
    return withheld


def make_seed_node(deps: AgentDeps):
    """Builds the seed node."""

    async def seed(state: AgentState) -> dict:
        if not deps.agent.seed:
            return {}
        started = time.perf_counter()
        step = deps.next_step()
        try:
            async with deps.tool_ctx.session_factory() as db:
                result = await retrieve(
                    deps.config,
                    state["question"],
                    ctx=deps.tool_ctx.retrieval(db),
                    history=state["history"],
                    llm=deps.llm,
                )
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"[:300]
            logger.warning("seed retrieval failed: %s", reason)
            await deps.event(Event.DEGRADED, {"stage": "seed", "reason": reason})
            await deps.record("seed", "seed", {"error": reason}, index=step, started=started)
            return {}

        candidates = list(result.candidates)
        evidence = {
            candidate.key: Evidence(
                key=candidate.key,
                text=candidate.text,
                label=SOURCE_LABELS.get(candidate.source_type, candidate.source_type),
                provenance=candidate.provenance,
                first_step=step,
                found_by=("seed",),
            )
            for candidate in candidates
        }
        keys = list(evidence)
        await deps.record(
            "seed",
            "seed",
            {
                "standalone_question": result.question,
                "keys": keys,
                "degraded": list(result.trace.degraded),
                "config_hash": result.trace.config_hash,
            },
            index=step,
            started=started,
        )
        channels: dict[str, int] = {}
        for entry in result.trace.channels:
            channels[entry.channel] = channels.get(entry.channel, 0) + entry.candidates
        await deps.event(
            Event.SEED,
            {
                "keys": keys,
                "standalone_question": result.question,
                "channels": channels,
                "reranker": result.trace.reranker,
            },
        )
        return {
            "standalone_question": result.question,
            "items": [{"role": "user", "content": seed_message(candidates)}],
            "evidence": evidence,
        }

    return seed
