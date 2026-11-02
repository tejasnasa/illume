"""
Vector embedding model definition.

Stores pgvector embeddings for semantic search and Retrieval-Augmented Generation (RAG).
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    UUID,
    Computed,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SEARCH_TSV_EXPRESSION = (
    "to_tsvector('simple'::regconfig, "
    "regexp_replace("
    "regexp_replace("
    r"regexp_replace(chunk_text, '([A-Z]+)([A-Z][a-z])', '\1 \2', 'g'), "
    r"'([a-z0-9])([A-Z])', '\1 \2', 'g'), "
    "'[_./:-]+', ' ', 'g') "
    "|| ' ' || chunk_text)"
)


class Embedding(Base):
    """
    SQLAlchemy model representing a high-dimensional vector embedding.

    Powers semantic search functionality over code, commits, and documents.
    """

    __tablename__ = "embeddings"
    __table_args__ = (
        Index("ix_embeddings_repository_id", "repository_id"),
        # Declared here so autogenerate cannot classify the live HNSW index as
        # stray schema and drop it -- which is exactly what happened to the
        # first version of this index.
        Index(
            "ix_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_embeddings_search_tsv", "search_tsv", postgresql_using="gin"),
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
    # Full-text index of ``chunk_text``, computed by Postgres on every write.
    # Identifiers are split into words (camelCase, acronyms, snake_case, dotted
    # names, paths) and the original text is appended, so a chunk matches an
    # identifier both whole and as words. ``simple`` rather than ``english``:
    # stemming and stop words damage identifiers such as ``get`` and ``is``.
    # The Python twin is ``retrieval.identifiers.split_identifiers``. Deferred:
    # it is only ever used inside SQL, so loading it with every row would ship
    # the whole tsvector to Python for nothing.
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_TSV_EXPRESSION, persisted=True),
        nullable=True,
        deferred=True,
    )
