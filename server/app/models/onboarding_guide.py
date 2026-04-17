import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OnboardingGuide(Base):
    __tablename__ = "onboarding_guides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    reading_order: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    critical_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    architecture_brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
