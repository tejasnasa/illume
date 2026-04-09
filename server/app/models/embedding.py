import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ast_symbols.id", ondelete="CASCADE"), nullable=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=True)
