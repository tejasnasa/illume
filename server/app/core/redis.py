import ssl

import redis
from app.core.config import settings


def get_sync_redis():
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )
