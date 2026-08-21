"""
Glossary entry model definition.

Stores domain-specific terminology extracted from repository code and documentation.
"""
import uuid

from app.core.database import Base
from sqlalchemy import UUID, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class GlossaryEntry(Base):
    """
    SQLAlchemy model representing an automatically generated glossary term.
    
    Helps explain repository-specific jargon to users.
    """
    __tablename__ = "glossary_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ast_symbols.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
