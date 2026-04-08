import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.redis import get_async_redis

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/ingest/{repo_id}")
async def ingest_ws(websocket: WebSocket, repo_id: str):
    await websocket.accept()
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
