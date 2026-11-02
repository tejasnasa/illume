"""
AST symbol model definition.

Represents an Abstract Syntax Tree symbol (e.g., function, class, method) extracted from a file.
"""

import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AstSymbol(Base):
    """
    SQLAlchemy model representing an AST symbol extracted from source code.

    Used to track definitions, complexity metrics, and serve as targets for dependency resolution.
    """

    __tablename__ = "ast_symbols"
    __table_args__ = (
        # Phase B indexes: the CASCADE delete on ast_symbols (triggered by every
        # ``DELETE FROM files WHERE repository_id = ?``) was a sequential scan
        # per row without these. The composite is what the embedder needs to
        # filter to embeddable kinds cheaply.
        Index("ix_ast_symbols_file_id", "file_id"),
        Index("ix_ast_symbols_file_id_kind", "file_id", "kind"),
        # Trigram indexes behind fuzzy name lookup and regex search over stored
        # bodies. Partial on the three kinds that are ever searched: imports and
        # variables make up much of the table and would only add index size.
        # A query uses these only when it repeats the same ``kind`` predicate.
        Index(
            "ix_ast_symbols_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=text("kind IN ('function', 'class', 'method')"),
        ),
        Index(
            "ix_ast_symbols_source_trgm",
            "source_code",
            postgresql_using="gin",
            postgresql_ops={"source_code": "gin_trgm_ops"},
            postgresql_where=text("kind IN ('function', 'class', 'method')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        Enum(
            "function",
            "class",
            "method",
            "import",
            "variable",
            "module",
            name="symbol_kind",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int] = mapped_column(Integer, nullable=True)
    source_code: Mapped[str] = mapped_column(Text, nullable=True)
    cyclomatic_complexity: Mapped[int] = mapped_column(Integer, nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
