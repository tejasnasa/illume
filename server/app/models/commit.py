"""
Git commit model definition.

Stores metadata for commits associated with a repository.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Commit(Base):
    """
    SQLAlchemy model representing a Git commit.
    
    Used for historical analysis and tracking changes over time.
    """
    __tablename__ = "commits"

    __table_args__ = (
        UniqueConstraint("repository_id", "hash", name="uq_commit_repo_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    hash: Mapped[str] = mapped_column(String, nullable=False)
    author_name: Mapped[str] = mapped_column(String, nullable=False)
    author_email: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    changed_files_list: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    authored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
