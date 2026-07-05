"""M7 → M6 依赖链装配：进程内 Coordinator 单例。"""

from __future__ import annotations

import redis.asyncio as redis
from fastapi import Depends

from app.common.redis_client import get_redis
from app.orchestrator.coordinator import Coordinator
from app.services.llm_service import LLMService

_coordinator: Coordinator | None = None


async def get_coordinator(
    redis_client: redis.Redis = Depends(get_redis),
) -> Coordinator:
    """进程内 Coordinator 单例装配：LLMService + Coordinator。"""
    global _coordinator
    if _coordinator is None:
        _coordinator = Coordinator(
            redis_client=redis_client, llm_service=LLMService()
        )
    return _coordinator
