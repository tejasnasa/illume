import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AstSymbol(Base):
    __tablename__ = "ast_symbols"

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
