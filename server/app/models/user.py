"""
User model definition.

Represents a registered user in the system.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    """
    SQLAlchemy model representing an application user.

    Stores authentication details, GitHub OAuth tokens, profile information,
    and the per-user stored-LLM-key credential together with the free-tier
    counters.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    github_access_token: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ai_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_key_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    free_ingestions_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    free_chat_messages_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
