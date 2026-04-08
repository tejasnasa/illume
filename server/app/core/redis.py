import ssl

import redis
import redis.asyncio as aioredis
from app.core.config import settings


def get_sync_redis():
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )


def get_async_redis() -> aioredis.Redis:

    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )
