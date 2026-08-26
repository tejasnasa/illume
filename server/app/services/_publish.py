"""Redis progress-log publishing for repository analysis tasks.

Provides a single helper that publishes structured log events to a
per-repository Redis channel so clients can follow task progress live.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def publish_log(redis_client, repo_id: str, event: str, message: str, **kwargs) -> None:
    """Publish a log message to a Redis channel for a specific repository task.

    Args:
        redis_client: Redis client instance.
        repo_id: The ID of the repository.
        event: The type of event.
        message: The log message.
        **kwargs: Additional data to include in the payload.
    """
    channel = f"task:{repo_id}:logs"
    data = {
        "event": event,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }

    try:
        # Progress logs are best-effort: a Redis outage must never fail the
        # analysis task that's merely reporting on itself.
        redis_client.publish(channel, json.dumps(data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis publish failed (channel=%s): %s", channel, exc)
    else:
        logger.info("[%s] %s: %s", repo_id, event, message)
