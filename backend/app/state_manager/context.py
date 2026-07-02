"""Agent 运行时上下文管理器。

每次 Agent 调用的"工作内存"：系统提示、中间结果、对话历史片段。
存储结构：STRING（json.dumps），TTL=24h，每次 set 续期。
"""

from __future__ import annotations

import json

import redis.asyncio

from app.state_manager.keys import get_agent_context_key


class AgentContextManager:
    """管理单次 Agent 调用的运行时上下文（Redis STRING）。"""

    TTL = 86400

    def __init__(self, redis: redis.asyncio.Redis) -> None:
        self._redis = redis

    async def set(self, execution_id: str, agent_id: str, data: dict) -> None:
        """写入或更新 Agent 上下文，同时刷新 TTL。"""
        key = get_agent_context_key(execution_id, agent_id)
        await self._redis.set(key, json.dumps(data), ex=self.TTL)

    async def get(self, execution_id: str, agent_id: str) -> dict | None:
        """读取上下文；键不存在或已过期返回 None。"""
        key = get_agent_context_key(execution_id, agent_id)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, execution_id: str, agent_id: str) -> None:
        """显式删除，早于 TTL 释放内存。"""
        key = get_agent_context_key(execution_id, agent_id)
        await self._redis.delete(key)
