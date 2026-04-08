import uuid
from datetime import datetime

from app.core.database import Base
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column


class HealthMetric(Base):
    __tablename__ = "health_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id"), nullable=True
    )  # null = repo-level
    overall_score: Mapped[float] = mapped_column(Float, nullable=True)
    complexity_score: Mapped[float] = mapped_column(Float, nullable=True)
    coupling_score: Mapped[float] = mapped_column(Float, nullable=True)
    duplication_score: Mapped[float] = mapped_column(Float, nullable=True)
    total_loc: Mapped[int] = mapped_column(Integer, nullable=True)
    avg_cyclomatic: Mapped[float] = mapped_column(Float, nullable=True)
    circular_deps: Mapped[int] = mapped_column(Integer, nullable=True)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("now()")
    )
