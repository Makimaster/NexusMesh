from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from app.config.settings import settings

_redis: aioredis.Redis | None = None


async def get_redis() -> AsyncGenerator[aioredis.Redis]:
    """FastAPI dependency: yields the shared Redis client."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    yield _redis


async def get_redis_instance() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close the Redis connection on shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
