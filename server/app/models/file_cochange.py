"""
File co-change model definition.

Stores, for each pair of files in a repository, how often they changed in the
same commit. Files that keep changing together are usually coupled even when
neither imports the other, which makes this a second structural signal beside
the import graph.
"""

import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FileCochange(Base):
    """
    SQLAlchemy model representing one co-changing pair of files.

    A pair is stored once, with ``file_a_id`` the smaller UUID, so lookups for
    one file read both columns. The table is derived data: it is rebuilt from
    the stored commits whenever history is analysed, and both foreign keys
    cascade so a deleted file takes its pairs with it.
    """

    __tablename__ = "file_cochange"
    __table_args__ = (
        CheckConstraint("file_a_id < file_b_id", name="ck_file_cochange_ordered_pair"),
        Index("ix_file_cochange_repository_id", "repository_id"),
        Index("ix_file_cochange_file_b_id", "file_b_id"),
    )

    file_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    file_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    # Commits that touched both files, then each file on its own.
    together: Mapped[int] = mapped_column(Integer, nullable=False)
    a_count: Mapped[int] = mapped_column(Integer, nullable=False)
    b_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # together / (a_count + b_count - together): the share of either file's
    # changes that it made alongside the other.
    jaccard: Mapped[float] = mapped_column(Float, nullable=False)
