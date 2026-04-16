from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.core.config import settings


def get_redis_client() -> aioredis.Redis:
    """Create a fresh Redis client safe for any event loop context.

    Each call creates a new connection (no shared pool) to avoid
    'Event loop is closed' errors when asyncio.run() is called
    repeatedly from Celery tasks.
    """
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def check_redis_health() -> bool:
    try:
        client = get_redis_client()
        pong = await client.ping()
        await client.aclose()
        return bool(pong)
    except Exception:
        return False
