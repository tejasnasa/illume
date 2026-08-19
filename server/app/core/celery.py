from app.core.config import settings
from celery import Celery

celery = Celery(
    "illume",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.ingest"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# uv run celery -A app.core.celery worker --loglevel=info --pool=solo
