"""
Push token model definition.

Stores the Expo push tokens a user's devices have registered, so a background
task can reach them when something worth interrupting them for happens.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PushToken(Base):
    """
    SQLAlchemy model representing one registered device push token.

    One row is one device installation. The token is unique across the table
    rather than unique per user, because a device keeps its token when the
    account behind it changes: the same phone signs out of one account and
    into another, and the second registration has to be able to take the
    token over from the first.
    """

    __tablename__ = "push_tokens"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('android', 'ios')",
            name="ck_push_tokens_platform",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC),
    )
