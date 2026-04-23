import asyncio
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


@router.websocket("/ws/ingest/{repo_id}")
async def ingest_ws(
    websocket: WebSocket,
    repo_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    await websocket.accept()

    token = websocket.cookies.get("access_token") or websocket.query_params.get("token")
    if not token:
        logger.error("WebSocket auth failed: No token provided")
        await websocket.close(code=1008, reason="Not authenticated")
        return

    user_id = decode_access_token(token)
    if not user_id:
        logger.error(f"WebSocket auth failed: Invalid token {token}")
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
            if message["type"] != "message":
                continue

            data = message["data"]
            await websocket.send_text(data)

            if data in ("DONE", "ERROR"):
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for repo %s", repo_id)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.aclose()
