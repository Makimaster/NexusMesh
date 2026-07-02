"""M3 Redis 状态管理器集成测试。

前置条件：Redis 在 localhost:6379 可访问（docker compose up -d redis）。
每个测试用例结束后 fixture 只删除自己创建的 key，防止并行测试互相干扰。
"""

import asyncio
from uuid import uuid4

import pytest
import redis.asyncio

from app.state_manager.context import AgentContextManager
from app.state_manager.keys import get_agent_context_key


@pytest.fixture
async def redis_client():
    """使用 DB 1，与开发环境 DB 0 隔离。"""
    client = redis.asyncio.from_url(
        "redis://localhost:6379/1",
        encoding="utf-8",
        decode_responses=True,
    )
    yield client
    await client.aclose()


@pytest.fixture
async def context_ids(redis_client):
    execution_id = f"exec-{uuid4()}"
    agent_id = f"agent-{uuid4()}"

    yield execution_id, agent_id

    await redis_client.delete(get_agent_context_key(execution_id, agent_id))


@pytest.fixture
def ctx_mgr(redis_client):
    return AgentContextManager(redis_client)


async def test_context_set_and_get(ctx_mgr, context_ids):
    data = {"system_prompt": "你是一个助手", "variables": {"k": "v"}}
    execution_id, agent_id = context_ids

    await ctx_mgr.set(execution_id, agent_id, data)

    result = await ctx_mgr.get(execution_id, agent_id)

    assert result == data


async def test_context_get_missing_returns_none(ctx_mgr, context_ids):
    execution_id, agent_id = context_ids

    result = await ctx_mgr.get(execution_id, agent_id)

    assert result is None


async def test_context_set_refreshes_ttl(ctx_mgr, redis_client, context_ids):
    execution_id, agent_id = context_ids

    await ctx_mgr.set(execution_id, agent_id, {"x": 1})

    key = get_agent_context_key(execution_id, agent_id)
    initial_ttl = await redis_client.ttl(key)

    await asyncio.sleep(1.1)

    ttl_before_refresh = await redis_client.ttl(key)
    await ctx_mgr.set(execution_id, agent_id, {"x": 2})
    ttl_after_refresh = await redis_client.ttl(key)

    assert initial_ttl > ttl_before_refresh > 0
    assert ttl_after_refresh > ttl_before_refresh


async def test_context_delete(ctx_mgr, context_ids):
    execution_id, agent_id = context_ids

    await ctx_mgr.set(execution_id, agent_id, {"y": 2})
    await ctx_mgr.delete(execution_id, agent_id)

    assert await ctx_mgr.get(execution_id, agent_id) is None
