"""
Agent run model definition.

One row per question asked through the streaming endpoint, whatever preset
answered it. The row records what was asked, exactly which configuration
answered, and how the run ended; the steps it took live in ``agent_steps``.
"""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentRun(Base):
    """
    SQLAlchemy model representing one streamed answer.

    Rows outlive their steps: steps are pruned after a retention period while the
    run, which is small, stays. ``config`` holds the full effective pipeline
    configuration so a run can be reproduced and compared by ``config_hash``.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_user_repo_created", "user_id", "repository_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    # Set when the turn is saved to the chat history; cleared if that turn is deleted.
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "chat_messages.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_agent_runs_chat_message_id",
        ),
        nullable=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    standalone_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    preset: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ``provider:model``
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ``jev:<model id>`` or ``llm:<model>``
    decider: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    # running | done | failed | cancelled
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
