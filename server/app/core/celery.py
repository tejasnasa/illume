from app.core.config import settings
from celery import Celery

celery_app = Celery(
    "illume",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.ingest"],
)

celery_app.conf.task_serializer = "json"
