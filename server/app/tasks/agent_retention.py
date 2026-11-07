"""Retention for agent run steps.

A run's steps can be large (tool results, model text), so they are deleted after
:data:`~app.services.agent.persistence.RETENTION_DAYS`. The run rows stay: they
are small, and they are what a history of questions and an evaluation read.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.celery import celery
from app.core.database import SyncSessionLocal
from app.models.agent_step import AgentStep
from app.services.agent.persistence import RETENTION_DAYS

logger = logging.getLogger(__name__)

# Rows removed per statement, so one pass never holds a long lock or a huge transaction.
PRUNE_BATCH_SIZE = 5_000


@celery.task(name="app.tasks.agent_retention.prune_agent_steps")
def prune_agent_steps(retention_days: int = RETENTION_DAYS) -> int:
    """Deletes step rows older than the retention period.

    Args:
        retention_days: How many days of steps to keep.

    Returns:
        How many rows were deleted.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed = 0
    session = SyncSessionLocal()
    try:
        while True:
            oldest = (
                select(AgentStep.id)
                .where(AgentStep.created_at < cutoff)
                .order_by(AgentStep.created_at)
                .limit(PRUNE_BATCH_SIZE)
            )
            result = session.execute(delete(AgentStep).where(AgentStep.id.in_(oldest)))
            session.commit()
            count = int(result.rowcount or 0)
            removed += count
            if count < PRUNE_BATCH_SIZE:
                break
    except Exception:
        session.rollback()
        logger.exception("pruning agent steps failed after removing %d rows", removed)
        raise
    finally:
        session.close()
    if removed:
        logger.info("pruned %d agent step rows older than %d days", removed, retention_days)
    return removed
