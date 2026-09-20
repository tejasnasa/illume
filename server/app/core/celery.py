"""
Celery background task queue configuration.

Initializes the Celery application and binds it to the Redis broker.
"""

from celery import Celery

from app.core.config import settings

# Initialize Celery app with Redis broker and backend
celery = Celery(
    "illume",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.ingest"],
)

# Configure Celery settings (serialization, timezone, SSL).
#
# ``worker_max_tasks_per_child`` recycles the worker process after N tasks so
# memory used by an ingest does not accumulate across runs. ``worker_prefetch_multiplier=1``
# avoids pulling a second ingestion into RAM while the first is still running
# -- each ingest peaks at several hundred MB, and a prefetch of 2 with the
# default pool would double that floor.
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_max_tasks_per_child=10,
    worker_prefetch_multiplier=1,
)

# Recommended worker invocation:
#
#   uv run celery -A app.core.celery worker --loglevel=info --pool=prefork --concurrency=1
#
# ``--concurrency=1`` serialises ingests (the only thing more than one
# concurrent ingest can do is multiply parse-phase memory). ``--pool=prefork``
# is required for ``--max-tasks-per-child`` to take effect -- ``--pool=solo``
# ignores both.
