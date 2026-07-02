"""前端 WebSocket 连接会话管理器。

存储用户身份与当前订阅的 execution_id，TTL=60min（对齐 JWT 有效期）。
M4 WebSocket 网关在断线时调用 delete() 清理热状态。
"""
from __future__ import annotations

from datetime import UTC, datetime

import redis.asyncio

from app.state_manager.keys import get_session_key


class SessionManager:
    """管理前端 WebSocket 连接的会话状态（Redis HASH）。"""

    TTL = 3600
    _UPDATE_SUBSCRIPTION_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end
redis.call('HSET', KEYS[1], 'subscribed_execution_id', ARGV[1])
return 1
"""

    def __init__(self, redis: redis.asyncio.Redis) -> None:
        self._redis = redis

    async def create(
        self, session_id: str, user_id: str, execution_id: str
    ) -> None:
        """建立会话，写入订阅关系与连接时间戳。"""
        key = get_session_key(session_id)
        await self._redis.hset(
            key,
            mapping={
                "user_id": user_id,
                "subscribed_execution_id": execution_id,
                "connected_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._redis.expire(key, self.TTL)

    async def get(self, session_id: str) -> dict | None:
        """读取会话；键不存在或已过期返回 None。"""
        key = get_session_key(session_id)
        data = await self._redis.hgetall(key)
        return data if data else None

    async def update_subscription(
        self, session_id: str, execution_id: str
    ) -> None:
        """前端切换看板时，单独更新 subscribed_execution_id。"""
        key = get_session_key(session_id)
        updated = await self._redis.eval(
            self._UPDATE_SUBSCRIPTION_SCRIPT, 1, key, execution_id
        )
        if updated == 0:
            raise ValueError("session not found")

    async def delete(self, session_id: str) -> None:
        """M4 WebSocket 断线时调用，清理热状态。"""
        key = get_session_key(session_id)
        await self._redis.delete(key)
