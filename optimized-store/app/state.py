import redis.asyncio as aioredis
import os
import time

redis_client: aioredis.Redis | None = None
start_time: float = time.time()


async def get_redis() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            encoding="utf-8",
            decode_responses=True,
            # redis-py's ConnectionPool defaults to max_connections=100 —
            # under concurrent load tests above ~100 in-flight /buy calls
            # this silently starts raising MaxConnectionsError (500s), which
            # looks like a seller bottleneck but is actually just an
            # undersized client-side pool. Raised well above expected test
            # concurrency; override via REDIS_MAX_CONNECTIONS if needed.
            max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "500")),
        )
    return redis_client
