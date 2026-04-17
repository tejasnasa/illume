import uuid

from sqlalchemy import UUID, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CodeOwner(Base):
    __tablename__ = "code_owners"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    primary_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    contributors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    bus_factor: Mapped[int] = mapped_column(Integer, default=0)
    is_knowledge_silo: Mapped[bool] = mapped_column(Boolean, default=False)
