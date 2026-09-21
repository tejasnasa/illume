"""
Vector embedding model definition.

Stores pgvector embeddings for semantic search and Retrieval-Augmented Generation (RAG).
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import UUID, Enum, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Embedding(Base):
    """
    SQLAlchemy model representing a high-dimensional vector embedding.

    Powers semantic search functionality over code, commits, and documents.
    """

    __tablename__ = "embeddings"
    __table_args__ = (
        Index("ix_embeddings_repository_id", "repository_id"),
        UniqueConstraint(
            "repository_id",
            "source_type",
            "source_id",
            name="uq_embedding_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)
    source_type: Mapped[str] = mapped_column(
        Enum(
            "symbol",
            "commit",
            "pull_request",
            "document",
            "file",
            name="source_type",
            native_enum=False,
        )
    )
    # sha256-style hash of the rendered ``chunk_text`` at insert time.
    chunk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
