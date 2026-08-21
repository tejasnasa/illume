"""
Redis client configuration and session management.

Provides both synchronous and asynchronous Redis clients for pub/sub,
caching, and Celery broker operations.
"""
import redis
import redis.asyncio as aioredis
from app.core.config import settings


def get_sync_redis():
    """
    Creates and returns a synchronous Redis client.
    
    Returns:
        redis.Redis: A connected synchronous Redis client instance.
    """
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )


def get_async_redis() -> aioredis.Redis:
    """
    Creates and returns an asynchronous Redis client.
    
    Returns:
        aioredis.Redis: A connected async Redis client instance.
    """
    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
