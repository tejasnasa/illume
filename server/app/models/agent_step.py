"""
Agent step model definition.

The ordered record of what a run did. Rows of kind ``event`` are the events the
client saw; every other kind is detail kept for debugging and evaluation.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentStep(Base):
    """
    SQLAlchemy model representing one recorded step of a run.

    ``seq`` is unique per run and gives the order of every row, events and
    detail alike. Steps are deleted after a retention period; the run stays.
    """

    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_steps_run_seq"),
        Index("ix_agent_steps_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # event | seed | plan | worker | merge | model_call | tool_call | decision | ...
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # The event type, or the node or decision point the step belongs to.
    name: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
