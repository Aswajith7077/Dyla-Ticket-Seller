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
        )
    return redis_client
