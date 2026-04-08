import uuid

from app.core.database import Base
from sqlalchemy import JSON, Enum, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ast_symbols.id"), nullable=False
    )
    target_symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ast_symbols.id"), nullable=False
    )
    dep_type: Mapped[str] = mapped_column(
        Enum("imports", "calls", "inherits", "instantiates", name="dep_type"),
        nullable=False,
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=True)
