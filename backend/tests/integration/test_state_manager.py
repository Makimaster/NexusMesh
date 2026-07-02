"""M3 Redis 状态管理器集成测试。

前置条件：Redis 在 localhost:6379 可访问（docker compose up -d redis）。
每个测试用例结束后 fixture 只删除自己创建的 key，防止并行测试互相干扰。
"""

import asyncio
from uuid import uuid4

import pytest
import redis.asyncio

from app.state_manager.context import AgentContextManager
from app.state_manager.keys import (
    get_agent_context_key,
    get_session_key,
    get_task_state_key,
)
from app.state_manager.session import SessionManager
from app.state_manager.task_state import TaskStateManager


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


@pytest.fixture
async def session_id(redis_client):
    session_id_value = f"sess-{uuid4()}"

    yield session_id_value

    await redis_client.delete(get_session_key(session_id_value))


@pytest.fixture
async def missing_session_id(redis_client):
    session_id_value = f"missing-sess-{uuid4()}"

    yield session_id_value

    await redis_client.delete(get_session_key(session_id_value))


@pytest.fixture
def sess_mgr(redis_client):
    return SessionManager(redis_client)


@pytest.fixture
async def task_execution_id(redis_client):
    execution_id = f"exec-{uuid4()}"

    yield execution_id

    await redis_client.delete(get_task_state_key(execution_id))


@pytest.fixture
def task_mgr(redis_client):
    return TaskStateManager(redis_client)


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


async def test_session_create_and_get(sess_mgr, session_id):
    await sess_mgr.create(session_id, "user-1", "exec-1")
    result = await sess_mgr.get(session_id)
    ttl = await sess_mgr._redis.ttl(get_session_key(session_id))
    assert result["user_id"] == "user-1"
    assert result["subscribed_execution_id"] == "exec-1"
    assert "connected_at" in result
    assert 0 < ttl <= SessionManager.TTL


async def test_session_get_missing_returns_none(sess_mgr, missing_session_id):
    assert await sess_mgr.get(missing_session_id) is None


async def test_session_update_subscription(sess_mgr, session_id):
    await sess_mgr.create(session_id, "user-2", "exec-A")
    key = get_session_key(session_id)
    initial_ttl = await sess_mgr._redis.ttl(key)
    await asyncio.sleep(1.1)
    ttl_before_update = await sess_mgr._redis.ttl(key)
    await sess_mgr.update_subscription(session_id, "exec-B")
    ttl_after_update = await sess_mgr._redis.ttl(key)
    result = await sess_mgr.get(session_id)
    assert result["subscribed_execution_id"] == "exec-B"
    assert result["user_id"] == "user-2"
    assert initial_ttl > ttl_before_update > 0
    assert ttl_after_update <= ttl_before_update
    assert ttl_after_update > 0


async def test_session_update_subscription_missing_raises_value_error(
    sess_mgr, missing_session_id
):
    with pytest.raises(ValueError, match="session not found"):
        await sess_mgr.update_subscription(missing_session_id, "exec-B")


async def test_session_update_subscription_is_atomic_under_key_loss(
    redis_client, session_id
):
    class RedisRaceProxy:
        def __init__(self, inner):
            self._inner = inner

        async def exists(self, key):
            exists = await self._inner.exists(key)
            await self._inner.delete(key)
            return exists

        async def hset(self, *args, **kwargs):
            return await self._inner.hset(*args, **kwargs)

        async def eval(self, script, numkeys, *keys_and_args):
            await self._inner.delete(get_session_key(session_id))
            return await self._inner.eval(script, numkeys, *keys_and_args)

    sess_mgr = SessionManager(RedisRaceProxy(redis_client))
    await SessionManager(redis_client).create(session_id, "user-4", "exec-A")

    with pytest.raises(ValueError, match="session not found"):
        await sess_mgr.update_subscription(session_id, "exec-B")

    assert await redis_client.hgetall(get_session_key(session_id)) == {}


async def test_session_delete(sess_mgr, session_id):
    await sess_mgr.create(session_id, "user-3", "exec-3")
    await sess_mgr.delete(session_id)
    assert await sess_mgr.get(session_id) is None


async def test_task_create_and_get(task_mgr, task_execution_id):
    await task_mgr.create(task_execution_id)
    state = await task_mgr.get(task_execution_id)
    assert state["status"] == "pending"
    assert state["protocol_stage"] == "INIT"
    assert state["current_agent_id"] == ""
    assert state["version"] == "0"


async def test_task_create_custom_stage(task_mgr, task_execution_id):
    await task_mgr.create(task_execution_id, initial_stage="RECEIVE")
    state = await task_mgr.get(task_execution_id)
    assert state["protocol_stage"] == "RECEIVE"


async def test_task_get_missing_returns_none(task_mgr, task_execution_id):
    missing_execution_id = f"missing-{task_execution_id}"
    assert await task_mgr.get(missing_execution_id) is None


async def test_task_delete(task_mgr, task_execution_id):
    await task_mgr.create(task_execution_id)
    await task_mgr.delete(task_execution_id)
    assert await task_mgr.get(task_execution_id) is None


async def test_task_create_sets_ttl(task_mgr, redis_client, task_execution_id):
    await task_mgr.create(task_execution_id)
    ttl = await redis_client.ttl(get_task_state_key(task_execution_id))
    assert TaskStateManager.TTL - 5 <= ttl <= TaskStateManager.TTL
