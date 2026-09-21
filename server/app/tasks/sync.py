"""Sync a single repository against its current head.

The actual delta algorithm lands here alongside the rest of the core work;
this file exists today so ``celery.py``'s ``include`` and ``task_routes``
can reference a real module without the import failing. The body is a
no-op so the beat process keeps the dispatch contract honest until the
full implementation arrives.
"""

from app.core.celery import celery


@celery.task(name="app.tasks.sync.sync_repository")
def sync_repository(repo_id: str, access_token: str | None = None) -> None:
    """Run a single sync against ``repo_id``.

    Args:
        repo_id: The :class:`app.models.repository.Repository.id` UUID
            as a string -- Celery serialises arguments as JSON, so the
            id round-trips as ``str``.
        access_token: Optional GitHub OAuth token. ``None`` is a public
            repo; the task does its own lookup of the user's token from
            the repository's owner when this is missing.
    """
    del repo_id, access_token  # Placeholder body; populated by the delta engine.
