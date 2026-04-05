from datetime import datetime

from app.db.base import Base
from sqlalchemy import Column, DateTime, String


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)

    email = Column(String, unique=True, index=True, nullable=False)

    password = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
