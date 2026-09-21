"""
Repository model definition.

Represents a GitHub repository ingested into the system.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Repository(Base):
    """
    SQLAlchemy model representing an ingested GitHub repository.

    Stores metadata, analysis status, tech stack information, and ingestion tracking.
    """

    __tablename__ = "repositories"
    __table_args__ = (
        Index(
            "ix_repositories_next_sync_due",
            "next_sync_at",
            postgresql_where=text("auto_update_enabled"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    repo_number: Mapped[int] = mapped_column(
        Integer,
        Identity(),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    github_url: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str] = mapped_column(String, nullable=True)
    primary_language: Mapped[str] = mapped_column(String, nullable=True)
    # NOTE: these labels deliberately differ from the database's `repo_status` type,
    # which was created with "scoring" where this declares "analyzing". Reconciling
    # the two needs an enum migration, so the drift is left in place -- it has never
    # been reachable because nothing assigns either value. The pipeline only writes
    # pending/cloning/parsing/embedding/ready/failed, all of which exist in both.
    # Assigning `analyzing` would raise against the real column; assign one of the
    # shared labels, or migrate the type first.
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
    ingested_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    ingested_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    # Commit the deterministic data (files, symbols, deps, fan, criticality,
    # commits, PRs, stack) reflects. Written when the deterministic portion
    # of a sync commits.
    analysis_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC),
    )
    auto_update_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    auto_update_interval_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("6")
    )
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'idle'")
    )
    sync_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_generation: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_sync_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_sync_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
