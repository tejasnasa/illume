import uuid
from datetime import datetime

from app.core.database import Base
from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    github_url: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str] = mapped_column(String, nullable=True)
    primary_language: Mapped[str] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "cloning",
            "parsing",
            "embedding",
            "scoring",
            "ready",
            "failed",
            name="repo_status",
        ),
        server_default="pending",
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("now()"), onupdate=datetime.utcnow
    )
