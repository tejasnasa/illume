"""
Celery background task queue configuration.

Initializes the Celery application and binds it to the Redis broker.
"""

from app.core.config import settings
from celery import Celery

# Initialize Celery app with Redis broker and backend
celery = Celery(
    "illume",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.ingest"],
)

# Configure Celery settings (serialization, timezone, SSL)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# uv run celery -A app.core.celery worker --loglevel=info --pool=solo
