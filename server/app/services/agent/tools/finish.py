"""The ``finish`` tool: how the agent ends its run with an answer."""

from __future__ import annotations

from pydantic import Field

from app.services.agent.tools.context import ToolContext
from app.services.agent.tools.output import ToolOutput
from app.services.agent.tools.registry import REGISTRY, Tool, ToolInput


class FinishInput(ToolInput):
    answer: str = Field(
        min_length=1,
        max_length=30_000,
        description=(
            "The final answer in markdown. Cite evidence inline with the keys the tools "
            "returned, for example [F:app/main.py:3-9] or [C:a1b2c3d4]."
        ),
    )
    confidence_note: str | None = Field(
        default=None,
        max_length=1000,
        description="What is uncertain or missing, if anything. Omit when the answer is complete.",
    )


class FinishOutput(ToolOutput):
    answer: str
    confidence_note: str | None = None

    def render(self) -> str:
        return "Answer recorded."


async def _finish(ctx: ToolContext, args: FinishInput) -> FinishOutput:
    return FinishOutput(answer=args.answer, confidence_note=args.confidence_note)


REGISTRY.register(
    Tool(
        name="finish",
        description=(
            "End the run with the final answer. Call it once, when the evidence gathered is "
            "enough or no more can be found. Cite what supports each claim with the keys "
            "from the tool results."
        ),
        input_model=FinishInput,
        output_model=FinishOutput,
        handler=_finish,
        cost="none",
        timeout_s=5,
    )
)
