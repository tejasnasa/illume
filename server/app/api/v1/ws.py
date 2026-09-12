"""WebSocket route streaming live ingestion logs.

Authenticates via cookie or query token, verifies repository ownership,
then relays the per-repository Redis log channel until DONE/ERROR.
"""

import asyncio
import json
import logging
import uuid

from app.core.database import get_async_db
from app.core.redis import get_async_redis
from app.core.security import decode_access_token
from app.models.repository import Repository
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

_TERMINAL_MARKERS = ("DONE", "ERROR")


def _is_terminal(data: str) -> bool:
    """Report whether a raw log frame is the ingestion task's end-of-stream marker.

    The decoded `message` field is what carries the marker, which is why the raw frame
    cannot be compared directly. A bare marker is still accepted so that a future
    publisher that skips the JSON wrapper does not silently reintroduce the same bug.

    Args:
        data: Raw frame as it came off the Redis channel.

    Returns:
        True if the frame marks the end of the stream.
    """
    try:
        payload = json.loads(data)
    except (TypeError, ValueError):
        return data in _TERMINAL_MARKERS
    if isinstance(payload, dict):
        return payload.get("message") in _TERMINAL_MARKERS
    return payload in _TERMINAL_MARKERS


@router.websocket("/ws/ingest/{repo_id}")
async def ingest_ws(
    websocket: WebSocket,
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Stream ingestion progress logs for a repository over WebSocket.

    Args:
        websocket: Accepted WebSocket connection to push logs to.
        repo_id: ID of the repository whose log channel to relay.
        db: Async database session used for the ownership check.
    """
    await websocket.accept()

    # Query-param fallback supports EventSource-style clients that can't send cookies.
    token = websocket.cookies.get("access_token") or websocket.query_params.get("token")
    if not token:
        logger.error("WebSocket auth failed: No token provided")
        await websocket.close(code=1008, reason="Not authenticated")
        return

    user_id = decode_access_token(token)
    if not user_id:
        logger.warning("WebSocket auth failed: invalid token for repo %s", repo_id)
        await websocket.close(code=1008, reason="Invalid token")
        return

    result = await db.execute(
        select(Repository).where(
            Repository.id == repo_id, Repository.user_id == user_id
        )
    )
    repo = result.scalar_one_or_none()

    if not repo:
        logger.error(f"WebSocket auth failed: Repo not found or access denied for user {user_id}")
        await websocket.close(code=1008, reason="Repository not found or access denied")
        return

    redis_client = get_async_redis()
    pubsub = redis_client.pubsub()
    channel = f"task:{repo_id}:logs"

    await pubsub.subscribe(channel)
    logger.info("WebSocket subscribed to %s", channel)

    try:
        async for message in pubsub.listen():
            # Skip subscribe-confirmation frames; only relay real log payloads.
            if message["type"] != "message":
                continue

            data = message["data"]
            # The frame is relayed verbatim -- the client renders it by parsing
            # `parsed.message` -- so only the terminal *check* decodes it.
            await websocket.send_text(data)

            if _is_terminal(data):
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for repo %s", repo_id)
    except asyncio.CancelledError:
        # Re-raised, so that `task.cancel()` and `asyncio.wait_for(...)` can bound this
        # handler. Absorbing it made the task look like it had completed normally, which
        # left `wait_for` unable to time the stream out.
        raise
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.aclose()
