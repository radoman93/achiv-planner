from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.core.config import settings

redis_pool: aioredis.ConnectionPool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL, decode_responses=True, max_connections=20
)


def get_redis_client() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.close()


async def check_redis_health() -> bool:
    try:
        client = get_redis_client()
        pong = await client.ping()
        await client.close()
        return bool(pong)
    except Exception:
        return False
