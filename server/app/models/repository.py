import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Identity, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    repo_number: Mapped[int] = mapped_column(
        Integer,
        Identity(),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    github_url: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str] = mapped_column(String, nullable=True)
    primary_language: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "cloning",
            "parsing",
            "embedding",
            "analyzing",
            "ready",
            "failed",
            name="repo_status",
        ),
        server_default="pending",
    )
    detected_stack: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    entry_points: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    architecture_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.utcnow
    )
