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
    # The autoupdate module owns the sweep task; ``sync`` is the eventual
    # home of the per-repository sync task the sweep dispatches. Both must
    # be in ``include`` so the worker process imports them and registers
    # their tasks at startup.
    include=["app.tasks.ingest", "app.tasks.sync", "app.tasks.autoupdate"],
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
    # Two queues on a single ``--concurrency=1`` worker keeps the deploy
    # unit one process even when the auto-update traffic grows enough to
    # justify a dedicated worker pool -- the route split already exists,
    # the second worker slot is a deployment-only change. ``celery`` is
    # the implicit default queue; ``sync`` carries the per-repository
    # background work. Initial ingests stay on the default queue.
    task_routes={
        "app.tasks.sync.sync_repository": {"queue": "sync"},
    },
)

# The beat schedule is registered after both ``celery`` and the task
# modules are loaded -- ``autoupdate.py`` owns the cadence constant and
# installs the schedule entry on import. ``celery.beat`` is a separate
# process from the worker (``celery.py`` is imported by both) and keeps
# its last-run schedule in ``celerybeat-schedule``.

# Recommended worker invocation:
#
#   uv run celery -A app.core.celery worker --loglevel=info --pool=prefork --concurrency=1 -Q celery,sync
#
# ``--concurrency=1`` serialises ingests and syncs across both queues (the
# only thing more than one concurrent run can do is multiply parse-phase
# memory). ``-Q celery,sync`` is what makes the worker consume from both
# queues on the same process; ``--pool=prefork`` is required for
# ``--max-tasks-per-child`` to take effect (--pool=solo ignores both).
# Beat is run separately: ``uv run celery -A app.core.celery beat``.
