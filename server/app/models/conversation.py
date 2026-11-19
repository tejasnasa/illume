"""
Conversation model definition.

Groups the chat turns a user has had about one repository into named threads.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Conversation(Base):
    """
    SQLAlchemy model representing one chat thread.

    A conversation belongs to one user and one repository, and owns its messages:
    deleting it deletes them. ``updated_at`` moves forward whenever a turn is added,
    which is what orders the list newest first.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_user_repo_updated",
            "user_id",
            "repository_id",
            text("updated_at DESC"),
        ),
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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
