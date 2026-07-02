"""工作流执行状态管理器。

管理单次工作流执行的热状态：协议阶段、运行状态、当前 Agent、版本号。
transition() 使用 WATCH/MULTI/EXEC 乐观锁保证原子更新。
"""
from __future__ import annotations

import asyncio

import redis.asyncio as redis
from redis.exceptions import WatchError

from app.state_manager.exceptions import ConcurrencyError
from app.state_manager.keys import get_task_state_key


class TaskStateManager:
    """管理工作流执行态（Redis HASH），提供乐观锁状态流转。"""

    TTL = 604800
    MAX_RETRIES = 3

    def __init__(self, redis: redis.Redis) -> None:
        self._redis = redis

    async def create(
        self, execution_id: str, initial_stage: str = "INIT"
    ) -> None:
        """初始化执行态，version=0，status=pending。"""
        key = get_task_state_key(execution_id)
        await self._redis.hset(
            key,
            mapping={
                "status": "pending",
                "protocol_stage": initial_stage,
                "current_agent_id": "",
                "version": "0",
            },
        )
        await self._redis.expire(key, self.TTL)

    async def get(self, execution_id: str) -> dict | None:
        """读取当前执行态；键不存在返回 None。"""
        key = get_task_state_key(execution_id)
        data = await self._redis.hgetall(key)
        return data if data else None

    async def delete(self, execution_id: str) -> None:
        """显式删除（一般不需要，TTL 自然过期即可）。"""
        key = get_task_state_key(execution_id)
        await self._redis.delete(key)

    async def transition(
        self,
        execution_id: str,
        new_stage: str,
        new_status: str,
        agent_id: str | None = None,
    ) -> None:
        """以乐观锁原子更新执行态（Task 5 实现）。"""
        key = get_task_state_key(execution_id)

        for attempt in range(self.MAX_RETRIES):
            async with self._redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    current = await pipe.hgetall(key)
                    if not current:
                        await pipe.unwatch()
                        raise ValueError(
                            f"task_state for execution_id={execution_id!r} "
                            "does not exist."
                        )

                    mapping: dict[str, str] = {
                        "protocol_stage": new_stage,
                        "status": new_status,
                        "version": str(int(current.get("version", "0")) + 1),
                    }
                    if agent_id is not None:
                        mapping["current_agent_id"] = agent_id

                    pipe.multi()
                    pipe.hset(key, mapping=mapping)
                    pipe.expire(key, self.TTL)
                    await pipe.execute()
                    return
                except WatchError:
                    pass

            await asyncio.sleep(0.005 * (attempt + 1))

        raise ConcurrencyError(
            f"task_state transition conflict for execution_id={execution_id!r}"
        )
