"""M3 Redis 状态管理器集成测试。

前置条件：Redis 在 localhost:6379 可访问（docker compose up -d redis）。
每个测试用例结束后 fixture 自动 FLUSHDB DB 1，防止脏数据。
"""

import pytest
import redis.asyncio

from app.state_manager.context import AgentContextManager


@pytest.fixture
async def redis_client():
    """使用 DB 1，与开发环境 DB 0 隔离。"""
    client = redis.asyncio.from_url(
        "redis://localhost:6379/1",
        encoding="utf-8",
        decode_responses=True,
    )
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def ctx_mgr(redis_client):
    return AgentContextManager(redis_client)


async def test_context_set_and_get(ctx_mgr):
    data = {"system_prompt": "你是一个助手", "variables": {"k": "v"}}

    await ctx_mgr.set("exec-1", "agent-1", data)

    result = await ctx_mgr.get("exec-1", "agent-1")

    assert result == data


async def test_context_get_missing_returns_none(ctx_mgr):
    result = await ctx_mgr.get("no-exec", "no-agent")

    assert result is None


async def test_context_set_refreshes_ttl(ctx_mgr, redis_client):
    await ctx_mgr.set("exec-2", "agent-2", {"x": 1})

    key = "agent_context:exec-2:agent-2"
    ttl = await redis_client.ttl(key)

    assert ttl > 0


async def test_context_delete(ctx_mgr):
    await ctx_mgr.set("exec-3", "agent-3", {"y": 2})

    await ctx_mgr.delete("exec-3", "agent-3")

    assert await ctx_mgr.get("exec-3", "agent-3") is None
