from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.redis_client import get_redis
from app.config.settings import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0", "env": settings.APP_ENV}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@router.get("/health/redis")
async def health_redis(redis=Depends(get_redis)) -> dict:
    await redis.ping()
    return {"status": "ok", "redis": "connected"}
