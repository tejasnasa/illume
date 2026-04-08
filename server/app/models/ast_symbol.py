import uuid

from app.core.database import Base
from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column


class AstSymbol(Base):
    __tablename__ = "ast_symbols"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), nullable=False)
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
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=True)
