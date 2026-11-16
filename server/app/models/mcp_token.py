"""
MCP token model definition.

Stores the personal access tokens a user has minted for MCP clients. Only a
hash of each token is kept; the plaintext is shown once, at creation.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class McpToken(Base):
    """
    SQLAlchemy model representing one personal access token for MCP.

    The token itself is a 256-bit random value, so a plain SHA-256 digest is
    enough to store it safely and lookup by that digest is a single indexed
    read. ``token_prefix`` holds the first characters after the ``ilm_``
    marker so the owner can tell their tokens apart in a list. A token stops
    working when ``revoked_at`` is set or ``expires_at`` passes; the row is
    kept so the owner still sees when it was last used.
    """

    __tablename__ = "mcp_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
