"""Run the decision points against a real decision model, one request each.

Run from ``server/``::

    uv run python -m tests.tools.decide
    uv run python -m tests.tools.decide plan
    uv run python -m tests.tools.decide --decider llm

The default runs every point once; at present that is the planning decision.
Naming points narrows it. ``--decider llm`` uses the LLM stand-in instead of Jev, which is the
comparison the evaluation is built around; ``jev`` needs ``OPENROUTER_API_KEY`` in ``server/.env``.

**This spends real credit.** Every point is one request to OpenRouter (or one
model call for ``--decider llm``); the script prints each request's reported
cost and the total. It reads no database and writes nothing.

Each decision is printed with its answer, confidence, the exact model snapshot
that answered and the latency. The records the points produce are the same
objects the step log will hold.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import settings
from app.services.decisions import (
    Decider,
    DecisionRecord,
    RecordDecision,
    decide_plan,
    get_decider,
)

QUESTION = (
    "How does the login endpoint verify a password, and what would break if the "
    "hashing moved to another module?"
)

PASSAGE = (
    "def verify_password(plain, hashed):\n"
    "    return bcrypt.checkpw(plain, hashed)\n"
    "# Hashing happens in the same module that defines the login route's dependency."
)


async def _run_point(name: str, decider: Decider, record: RecordDecision) -> str:
    """Runs one named point and returns a one-line description of the answer."""
    if name == "plan":
        plan = await decide_plan(decider, QUESTION, record=record)
        return f"plan={plan.plan} (p={plan.probability:.3f})"
    raise SystemExit(f"unknown decision point {name!r}")


POINTS = ("plan",)


async def main(decider_kind: str, points: list[str]) -> int:
    if decider_kind == "jev" and not settings.OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY is not set in server/.env", file=sys.stderr)
        return 2

    records: list[DecisionRecord] = []

    async def record(item: DecisionRecord) -> None:
        records.append(item)

    degraded: list[dict] = []

    async def emit(event: str, payload: dict) -> None:
        if event == "degraded":
            degraded.append(payload)

    decider = get_decider(decider_kind, emit=emit, session_id="manual-decisions")
    print(f"decider : {decider.kind} ({decider.model_id})")
    print(f"question: {QUESTION}\n")

    for point in points:
        before = len(records)
        answer = await _run_point(point, decider, record)
        [item] = records[before:]
        print(f"{point:<12} {answer}")
        print(
            f"{'':<12} model={item.model} provider={item.provider} "
            f"latency={item.latency_ms:.0f}ms cost=${item.cost or 0:.6f}"
        )

    total = sum(item.cost or 0.0 for item in records)
    print(f"\ndecisions: {len(records)}  reported cost: ${total:.6f}")
    for payload in degraded:
        print(f"degraded: {payload['reason']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "points",
        nargs="*",
        choices=POINTS,
        help="decision points to run; the default is all of them",
    )
    parser.add_argument(
        "--decider",
        choices=["jev", "llm"],
        default="jev",
        help="who answers: the decision model (default) or the LLM stand-in",
    )
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(main(arguments.decider, arguments.points or list(POINTS))))
