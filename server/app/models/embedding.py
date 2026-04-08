import uuid

from app.core.database import Base
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ast_symbols.id"), nullable=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), nullable=False)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id"), nullable=False
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=True)
