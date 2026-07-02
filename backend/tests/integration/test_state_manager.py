"""M3 Redis 状态管理器集成测试。

前置条件：Redis 在 localhost:6379 可访问（docker compose up -d redis）。
每个测试用例结束后 fixture 只删除自己创建的 key，防止并行测试互相干扰。
"""

import asyncio
from uuid import uuid4

import pytest
import redis.asyncio

from app.state_manager.context import AgentContextManager
from app.state_manager.exceptions import ConcurrencyError
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


async def test_task_transition_happy_path(task_mgr):
    execution_id = "exec-200"
    await task_mgr.delete(execution_id)
    try:
        await task_mgr.create(execution_id)
        await task_mgr.transition(
            execution_id, "RECEIVE", "running", agent_id="agent-A"
        )
        state = await task_mgr.get(execution_id)
        assert state["protocol_stage"] == "RECEIVE"
        assert state["status"] == "running"
        assert state["current_agent_id"] == "agent-A"
        assert state["version"] == "1"
    finally:
        await task_mgr.delete(execution_id)


async def test_task_transition_increments_version(task_mgr):
    execution_id = "exec-201"
    await task_mgr.delete(execution_id)
    try:
        await task_mgr.create(execution_id)
        await task_mgr.transition(execution_id, "RECEIVE", "running")
        await task_mgr.transition(execution_id, "EXECUTE", "running")
        state = await task_mgr.get(execution_id)
        assert state["version"] == "2"
    finally:
        await task_mgr.delete(execution_id)


async def test_task_transition_refreshes_ttl(task_mgr, redis_client):
    execution_id = "exec-202"
    await task_mgr.delete(execution_id)
    try:
        await task_mgr.create(execution_id)
        key = get_task_state_key(execution_id)
        initial_ttl = await redis_client.ttl(key)
        await asyncio.sleep(1.1)
        ttl_before_transition = await redis_client.ttl(key)
        await task_mgr.transition(execution_id, "FINISH", "completed")
        ttl_after_transition = await redis_client.ttl(key)
        assert initial_ttl > ttl_before_transition > 0
        assert ttl_after_transition > ttl_before_transition
    finally:
        await task_mgr.delete(execution_id)


async def test_task_transition_missing_key_raises(task_mgr):
    with pytest.raises(ValueError):
        await task_mgr.transition("no-exec-999", "RECEIVE", "running")


async def test_task_transition_conflict_backoff_every_failure(monkeypatch):
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    class AlwaysConflictPipeline:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def watch(self, key):
            return None

        async def hgetall(self, key):
            return {"version": "0"}

        def multi(self):
            return None

        def hset(self, key, mapping):
            return None

        def expire(self, key, ttl):
            return None

        async def execute(self):
            raise redis.asyncio.WatchError

    class AlwaysConflictRedis:
        def pipeline(self):
            return AlwaysConflictPipeline()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    task_mgr = TaskStateManager(AlwaysConflictRedis())

    with pytest.raises(ConcurrencyError):
        await task_mgr.transition("exec-conflict", "EXECUTE", "running")

    assert sleep_calls == [0.005, 0.01, 0.02]


async def test_concurrent_transition_raises(task_mgr):
    """乐观锁冲突验证：4 路并发同时流转同一 execution_id。

    MAX_RETRIES=1 确保冲突必触发 ConcurrencyError（不靠重试消化）。
    至少一个成功、至少一个失败、总数等于任务数——三条断言缺一不可。
    """
    execution_id = "exec-concurrent-001"
    await task_mgr.delete(execution_id)
    try:
        await task_mgr.create(execution_id)
        task_mgr.MAX_RETRIES = 1
        task_count = 4
        ready_count = 0
        ready_lock = asyncio.Lock()
        release = asyncio.Event()

        class BarrierPipeline:
            def __init__(self, inner):
                self._inner = inner

            async def __aenter__(self):
                await self._inner.__aenter__()
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return await self._inner.__aexit__(exc_type, exc, tb)

            async def watch(self, key):
                return await self._inner.watch(key)

            async def hgetall(self, key):
                nonlocal ready_count
                current = await self._inner.hgetall(key)
                async with ready_lock:
                    ready_count += 1
                    if ready_count == task_count:
                        release.set()
                await release.wait()
                return current

            async def unwatch(self):
                return await self._inner.unwatch()

            def multi(self):
                return self._inner.multi()

            def hset(self, key, mapping):
                return self._inner.hset(key, mapping=mapping)

            def expire(self, key, ttl):
                return self._inner.expire(key, ttl)

            async def execute(self):
                return await self._inner.execute()

        class BarrierRedis:
            def __init__(self, inner):
                self._inner = inner

            def pipeline(self):
                return BarrierPipeline(self._inner.pipeline())

            def __getattr__(self, name):
                return getattr(self._inner, name)

        task_mgr._redis = BarrierRedis(task_mgr._redis)

        tasks = [
            task_mgr.transition(execution_id, "RECEIVE", "running"),
            task_mgr.transition(execution_id, "ROUTE", "running"),
            task_mgr.transition(execution_id, "EXECUTE", "running"),
            task_mgr.transition(execution_id, "FINISH", "completed"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for result in results if result is None)
        error_count = sum(
            1 for result in results if isinstance(result, ConcurrencyError)
        )

        assert success_count >= 1
        assert error_count >= 1
        assert success_count + error_count == len(tasks)
    finally:
        await task_mgr.delete(execution_id)
