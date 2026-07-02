# M4 WebSocket 网关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 WebSocket 网关（JWT 鉴权 + Redis psubscribe 广播），将工作流执行事件实时推送到前端，整个网关只占用 1 条 Redis 连接。

**Architecture:** 三个文件分工明确：`broadcaster.py` 持有唯一的 Redis psubscribe 连接并做进程内 fan-out；`handlers.py` 管理 WebSocket 连接生命周期并操作 M3 SessionManager；`gateway.py` 负责 JWT 校验和路由。Broadcaster 作为模块级单例由 `main.py` lifespan 管理启动/停止。

**Tech Stack:** Python 3.13, FastAPI 0.115, redis-py 5.x (`redis.asyncio`), Starlette TestClient (lifespan context manager 触发 lifespan), pytest-asyncio 0.24.x

---

## 文件结构

| 操作 | 路径 | 职责 |
|------|------|------|
| 修改 | `backend/app/common/redis_client.py` | 新增 `get_redis_instance()` 非生成器版本供 lifespan 使用 |
| 创建 | `backend/app/websocket/broadcaster.py` | 单全局 psubscribe + fan-out 单例 |
| 创建 | `backend/app/websocket/handlers.py` | `on_connect` / `on_disconnect` 连接生命周期 |
| 创建 | `backend/app/websocket/gateway.py` | WebSocket 路由 + JWT 鉴权 + `handle_connection` |
| 修改 | `backend/app/main.py` | lifespan 挂载 broadcaster；注册 ws_router |
| 创建 | `backend/tests/integration/test_websocket.py` | 集成测试（happy path + auth failure） |
| 创建 | `backend/tests/unit/test_broadcaster.py` | `_extract_execution_id` 单元测试 |

---

## Task 1：redis_client 新增 get_redis_instance()

lifespan 需要直接拿到 Redis 客户端对象（非生成器），而现有 `get_redis()` 是 FastAPI Depends 用的 async generator。此 Task 在 `redis_client.py` 中补一个直接返回实例的函数。

**Files:**
- 修改: `backend/app/common/redis_client.py`

- [ ] **Step 1: 写失败测试（验证函数存在）**

新建 `backend/tests/unit/test_broadcaster.py`（复用后续追加测试的文件）：

```python
"""M4 WebSocket broadcaster 单元测试。"""
import pytest


def test_get_redis_instance_importable():
    from app.common.redis_client import get_redis_instance
    assert callable(get_redis_instance)
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
uv run pytest tests/unit/test_broadcaster.py::test_get_redis_instance_importable -v
```

期望：`FAILED` — `ImportError: cannot import name 'get_redis_instance'`

- [ ] **Step 3: 在 redis_client.py 追加函数**

在 `backend/app/common/redis_client.py` 末尾追加：

```python


async def get_redis_instance() -> aioredis.Redis:
    """返回共享 Redis 客户端实例（非生成器版本，供 lifespan 直接调用）。"""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
uv run pytest tests/unit/test_broadcaster.py::test_get_redis_instance_importable -v
```

期望：`1 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/common/redis_client.py backend/tests/unit/test_broadcaster.py
git commit -m "feat: 新增 get_redis_instance() 供 lifespan 直接获取 Redis 客户端"
```

---

## Task 2：Broadcaster（broadcaster.py）+ 单元测试

**Files:**
- 创建: `backend/app/websocket/broadcaster.py`
- 修改: `backend/tests/unit/test_broadcaster.py`

- [ ] **Step 1: 追加 _extract_execution_id 单元测试**

在 `backend/tests/unit/test_broadcaster.py` 末尾追加：

```python
from app.websocket.broadcaster import broadcaster


def test_extract_valid_channel():
    assert broadcaster._extract_execution_id("channel:execution:abc-123:events") == "abc-123"


def test_extract_uuid_channel():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert broadcaster._extract_execution_id(f"channel:execution:{uid}:events") == uid


def test_extract_empty_execution_id_returns_none():
    assert broadcaster._extract_execution_id("channel:execution::events") is None


def test_extract_bad_format_returns_none():
    assert broadcaster._extract_execution_id("bad:format") is None


def test_extract_too_many_parts_returns_none():
    assert broadcaster._extract_execution_id("channel:execution:abc:events:extra") is None
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
uv run pytest tests/unit/test_broadcaster.py -k "extract" -v
```

期望：`FAILED` — `ImportError: cannot import name 'broadcaster'`

- [ ] **Step 3: 实现 broadcaster.py**

新建 `backend/app/websocket/broadcaster.py`：

```python
"""Redis psubscribe 广播器。

单全局实例，整个进程只占 1 条 Redis 连接。
lifespan 启动时调用 start()，关闭时调用 stop()。
"""
from __future__ import annotations

import asyncio

from fastapi import WebSocket
from redis.asyncio import Redis
from redis.exceptions import RedisError


class Broadcaster:
    """单全局 psubscribe + 进程内 fan-out。"""

    def __init__(self) -> None:
        # key = channel 全名（如 "channel:execution:xxx:events"）
        self._channels: dict[str, set[WebSocket]] = {}
        self._task: asyncio.Task | None = None
        self._pubsub = None

    async def start(self, redis: Redis) -> None:
        """lifespan 启动时调用，开启唯一监听任务。"""
        self._pubsub = redis.pubsub()
        await self._pubsub.psubscribe("channel:execution:*:events")
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """lifespan 关闭时调用，优雅下线。"""
        if self._task:
            self._task.cancel()
        if self._pubsub:
            await self._pubsub.punsubscribe()

    async def subscribe(self, channel: str, ws: WebSocket) -> None:
        """将 WebSocket 加入指定 channel 的广播集合。"""
        self._channels.setdefault(channel, set()).add(ws)

    async def unsubscribe(self, channel: str, ws: WebSocket) -> None:
        """从广播集合移除 WebSocket；集合变空则清理 key。"""
        sockets = self._channels.get(channel, set())
        sockets.discard(ws)
        if not sockets:
            self._channels.pop(channel, None)

    def _extract_execution_id(self, channel: str) -> str | None:
        """从 'channel:execution:{id}:events' 提取 execution_id。

        空字符串 execution_id 视为非法，返回 None。
        """
        parts = channel.split(":")
        # 格式固定：channel / execution / {id} / events → 恰好 4 段
        if len(parts) == 4 and parts[0] == "channel" and parts[3] == "events":
            execution_id = parts[2]
            return execution_id if execution_id else None
        return None

    async def _listen_loop(self) -> None:
        """Redis psubscribe 监听循环。

        偶发 ConnectionError 时等待 1s 后重连，不让 Task 彻底挂掉。
        CancelledError（lifespan stop）则优雅退出。
        """
        while True:
            try:
                async for message in self._pubsub.listen():
                    if message["type"] != "pmessage":
                        continue
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    execution_id = self._extract_execution_id(channel)
                    if execution_id is None:
                        continue
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    # 复制一份避免循环中修改 set 触发 RuntimeError
                    sockets = list(self._channels.get(channel, set()))
                    for ws in sockets:
                        try:
                            await ws.send_text(data)
                        except Exception:
                            # 静默忽略；handlers.on_disconnect 的 finally 负责清理
                            pass
            except asyncio.CancelledError:
                return  # lifespan stop，正常退出
            except (RedisError, ConnectionError):
                # 网络抖动，等待后重新 psubscribe
                await asyncio.sleep(1)
                try:
                    await self._pubsub.psubscribe("channel:execution:*:events")
                except Exception:
                    pass

    def _clear_for_test(self) -> None:
        """仅供测试使用：清空进程内连接映射，防止用例间污染。"""
        self._channels.clear()


# 模块级单例，gateway.py 和 main.py 直接 import
broadcaster = Broadcaster()
```

- [ ] **Step 4: 跑单元测试，确认通过**

```bash
uv run pytest tests/unit/test_broadcaster.py -v
```

期望：`6 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/websocket/broadcaster.py backend/tests/unit/test_broadcaster.py
git commit -m "feat: 新增 Broadcaster 单全局 psubscribe 广播器及单元测试"
```

---

## Task 3：handlers.py — 连接生命周期

**Files:**
- 创建: `backend/app/websocket/handlers.py`

- [ ] **Step 1: 实现 handlers.py**

新建 `backend/app/websocket/handlers.py`：

```python
"""WebSocket 连接生命周期处理器。

on_connect : accept + 写 M3 SessionManager + 注册 broadcaster
on_disconnect: 注销 broadcaster + 删 M3 SessionManager
"""
from __future__ import annotations

import uuid

from fastapi import WebSocket

from app.state_manager.keys import get_channel_events
from app.state_manager.session import SessionManager
from app.websocket.broadcaster import broadcaster


async def on_connect(
    ws: WebSocket,
    execution_id: str,
    user_id: str,
    session_mgr: SessionManager,
) -> str:
    """建立连接：accept → 写 Session → 注册广播。返回 session_id。"""
    await ws.accept()
    session_id = str(uuid.uuid4())
    channel = get_channel_events(execution_id)
    await session_mgr.create(session_id, user_id, execution_id)
    await broadcaster.subscribe(channel, ws)
    return session_id


async def on_disconnect(
    session_id: str,
    execution_id: str,
    ws: WebSocket,
    session_mgr: SessionManager,
) -> None:
    """断开连接：注销广播 → 删 Session（幂等，可重复调用）。"""
    channel = get_channel_events(execution_id)
    await broadcaster.unsubscribe(channel, ws)
    await session_mgr.delete(session_id)
```

- [ ] **Step 2: 验证导入**

```bash
cd backend
uv run python -c "from app.websocket.handlers import on_connect, on_disconnect; print('OK')"
```

期望：`OK`

- [ ] **Step 3: 提交**

```bash
git add backend/app/websocket/handlers.py
git commit -m "feat: 新增 WebSocket 连接生命周期处理器 on_connect/on_disconnect"
```

---

## Task 4：gateway.py — 路由 + JWT 鉴权

**Files:**
- 创建: `backend/app/websocket/gateway.py`

- [ ] **Step 1: 实现 gateway.py**

新建 `backend/app/websocket/gateway.py`：

```python
"""WebSocket 路由端点 + JWT 鉴权。

路由：/ws/executions/{execution_id}?token=<JWT>
鉴权失败在握手前 raise WebSocketException(1008)——禁止先 accept 再 close。
"""
from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from fastapi.websockets import WebSocketState
from starlette.websockets import WebSocketException

from app.common.redis_client import get_redis_instance
from app.core.security import verify_token
from app.state_manager.session import SessionManager
from app.websocket.handlers import on_connect, on_disconnect

router = APIRouter()


@router.websocket("/ws/executions/{execution_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    execution_id: str,
    token: str = Query(...),
) -> None:
    """WebSocket 端点。JWT 通过 query param 传入。"""
    # 1. 握手前验证 JWT（必须在 accept 前，失败则 raise，不调 close）
    try:
        payload = verify_token(token)
    except Exception:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token",
        )
    if payload.get("type") != "access":
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid token type",
        )
    user_id: str = payload["sub"]

    # 2. 移交连接生命周期
    await _handle_connection(websocket, execution_id, user_id)


async def _handle_connection(
    websocket: WebSocket,
    execution_id: str,
    user_id: str,
) -> None:
    """accept + 保持连接 + finally 清理。"""
    redis = await get_redis_instance()
    session_mgr = SessionManager(redis)
    session_id = await on_connect(websocket, execution_id, user_id, session_mgr)
    try:
        while True:
            # 忽略客户端上行消息，仅保持连接活跃
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await on_disconnect(session_id, execution_id, websocket, session_mgr)
```

- [ ] **Step 2: 验证导入**

```bash
cd backend
uv run python -c "from app.websocket.gateway import router; print('OK', router)"
```

期望：`OK <APIRouter ...>`

- [ ] **Step 3: 提交**

```bash
git add backend/app/websocket/gateway.py
git commit -m "feat: 新增 WebSocket 路由端点，JWT query param 鉴权"
```

---

## Task 5：main.py — 挂载 lifespan + 注册路由

**Files:**
- 修改: `backend/app/main.py`

- [ ] **Step 1: 更新 main.py**

将 `backend/app/main.py` 全文替换为：

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.common.redis_client import close_redis, get_redis_instance
from app.config.settings import settings
from app.core.exceptions import register_exception_handlers
from app.websocket.broadcaster import broadcaster
from app.websocket.gateway import router as ws_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    redis = await get_redis_instance()
    await broadcaster.start(redis)
    yield
    await broadcaster.stop()
    await close_redis()


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws_router)  # 无前缀，路径为 /ws/executions/{id}


@app.get("/health", tags=["health"])
async def root_health() -> dict:
    return {"status": "ok", "version": "0.1.0", "env": settings.APP_ENV}
```

- [ ] **Step 2: 验证应用可启动**

```bash
cd backend
uv run python -c "from app.main import app; print('OK', app.title)"
```

期望：`OK NexusMesh API`

- [ ] **Step 3: 提交**

```bash
git add backend/app/main.py
git commit -m "feat: lifespan 挂载 Broadcaster，注册 WebSocket 路由"
```

---

## Task 6：集成测试

**Files:**
- 创建: `backend/tests/integration/test_websocket.py`

> 使用 `starlette.testclient.TestClient` **作为 context manager**（`with TestClient(app) as client:`），这会正确触发 FastAPI lifespan（broadcaster.start 和 broadcaster.stop）。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/integration/test_websocket.py`：

```python
"""M4 WebSocket 网关集成测试。

前置：Redis 在 localhost:6379 可访问（docker compose up -d redis）。
使用 TestClient 作为 context manager 触发 lifespan（broadcaster.start/stop）。
每个用例结束后调用 broadcaster._clear_for_test() 保证隔离。
"""
import asyncio
import threading

import pytest
import redis as sync_redis
from starlette.testclient import TestClient

from app.main import app
from app.state_manager.keys import get_channel_events
from app.websocket.broadcaster import broadcaster

# ─── 辅助：同步发布一条 Redis 消息 ──────────────────────────────────────
def _publish_sync(channel: str, data: str) -> None:
    """在独立线程里用同步 Redis 客户端 publish，避免阻塞 asyncio 事件循环。"""
    r = sync_redis.from_url("redis://localhost:6379/0", decode_responses=True)
    r.publish(channel, data)
    r.close()


# ─── 测试用 JWT（有效用户，developer 角色） ─────────────────────────────
# 通过 app.core.security.create_access_token 生成，payload type="access", sub=<uuid>
import uuid
from app.core.security import create_access_token

VALID_TOKEN = create_access_token({"sub": str(uuid.uuid4()), "type": "access"})


# ─── Happy path ──────────────────────────────────────────────────────────

def test_websocket_broadcast_happy_path():
    """连接 → publish Redis 消息 → WebSocket 收到相同帧。"""
    execution_id = "test-exec-ws-happy-001"
    channel = get_channel_events(execution_id)
    payload = '{"event_type":"agent_spawn","stage":"INIT"}'

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/executions/{execution_id}?token={VALID_TOKEN}"
        ) as ws:
            # 等待 subscribe() 写入 broadcaster._channels
            import time
            time.sleep(0.1)
            # 在后台线程发布消息（TestClient 在同步环境运行）
            t = threading.Thread(target=_publish_sync, args=(channel, payload))
            t.start()
            t.join()
            # 读取广播帧
            received = ws.receive_text()
            assert received == payload

    broadcaster._clear_for_test()


# ─── Auth failure ─────────────────────────────────────────────────────────

def test_websocket_auth_failure_invalid_token():
    """无效 token → 握手被拒（WebSocketDisconnect 或 1008）。"""
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/ws/executions/any-id?token=totally_invalid_token"
            ):
                pass
    broadcaster._clear_for_test()


def test_websocket_auth_failure_missing_token():
    """缺少 token query param → 422 或握手拒绝。"""
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/executions/any-id"):
                pass
    broadcaster._clear_for_test()
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend
uv run pytest tests/integration/test_websocket.py::test_websocket_auth_failure_invalid_token -v
```

期望：`FAILED` — `ImportError` 或 `ModuleNotFoundError`（broadcaster/gateway 模块尚未被导入过）

> 若此时模块已存在（Task 2-5 完成），则期望为 `PASSED`——跳过此验证步骤，直接执行 Step 3。

- [ ] **Step 3: 跑全套集成测试**

```bash
uv run pytest tests/integration/test_websocket.py -v
```

期望：`3 passed`

- [ ] **Step 4: 跑全量单元测试回归**

```bash
uv run pytest tests/unit/ -q
```

期望：原有 M1/M2 + M4 broadcaster 单元测试全部通过（无回归）

- [ ] **Step 5: ruff 检查**

```bash
uv run ruff check app/websocket/ app/common/redis_client.py
```

期望：无输出

- [ ] **Step 6: 提交**

```bash
git add backend/tests/integration/test_websocket.py
git commit -m "test: 新增 M4 WebSocket 集成测试（happy path + 鉴权失败）"
```

---

## 验收检查（DoD）

- [ ] `uv run pytest tests/unit/test_broadcaster.py -v` → 6 passed
- [ ] `uv run pytest tests/integration/test_websocket.py -v` → 3 passed（含 happy path 广播验证）
- [ ] 无效 token 连接被以 1008 拒绝（握手阶段，未 accept）
- [ ] `uv run ruff check app/websocket/ app/common/redis_client.py` → 无输出
- [ ] `uv run pytest tests/unit/ -q` → 原有测试无回归
- [ ] `from app.websocket.broadcaster import broadcaster` 可正常导入
- [ ] `from app.websocket.gateway import router` 可正常导入
