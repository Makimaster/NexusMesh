# M4 WebSocket 网关设计文档

**版本**：1.0.0
**日期**：2026-07-02
**状态**：已审定，待实施
**上游文档**：[模块路线图](./2026-07-01-module-roadmap.md) §M4

---

## 1. 定位与职责

M4 是 NexusMesh 的**实时事件推送网关**，订阅 Redis Pub/Sub，将工作流执行事件推送到前端 WebSocket 连接。

| 输入 | 输出 | 依赖 |
|------|------|------|
| 前端 WebSocket 连接（带 JWT query param） | 实时 JSON 事件帧 | M2（事件格式）、M3（channel 命名、SessionManager）、Phase 1 JWT |
| Redis `channel:execution:{id}:events` 消息 | — | `common/redis_client`（已有） |

**边界约束**：
- 只订阅 `:events` channel，`:status` channel 留给 M15 可观测性
- 不做消息重放（断线后错过的事件不补发，YAGNI）
- 不做多进程路由（单进程，M15 再议）
- 无数据库写入，无 PostgreSQL 依赖

---

## 2. 架构方案

**单全局 `psubscribe` + 进程内 fan-out**，整个网关永远只占用 1 条 Redis 连接。

```
backend/app/websocket/
├── gateway.py      # FastAPI WebSocket 路由端点 + JWT 鉴权
├── broadcaster.py  # 单全局 Redis psubscribe + 进程内 fan-out
└── handlers.py     # 连接生命周期：on_connect / on_disconnect
```

**数据流**：

```
前端 ws://host/ws/executions/{execution_id}?token=<JWT>
  │
  ├─ gateway.py: verify_token() → 失败 raise WebSocketException(1008)
  │
  ├─ handlers.on_connect(): accept + 写 M3 SessionManager + broadcaster.subscribe()
  │
  ├─ broadcaster._listen_loop(): psubscribe("channel:execution:*:events")
  │     └─ 收到消息 → 解析 execution_id → fan-out 给对应 set[WebSocket]
  │
  └─ 断线 finally: handlers.on_disconnect() → broadcaster.unsubscribe() → SessionManager.delete()
```

**模块级单例**：`broadcaster` 在 `broadcaster.py` 模块层定义，`gateway.py` 直接 import，无需依赖注入。挂载到 `main.py` lifespan 管理生命周期。

---

## 3. JWT 鉴权方案

**选型**：Query param（`?token=<JWT>`）

WebSocket 握手阶段浏览器不能自定义 `Authorization` 头，Query param 是最简实现，开发期排查最直接。token 出现在服务端日志属可接受风险（内部网关，非公网端点）。

```python
@router.websocket("/ws/executions/{execution_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    execution_id: str,
    token: str = Query(...),
):
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
    # 移交 handlers
    await handle_connection(websocket, execution_id, user_id)
```

**关键细节**：`raise WebSocketException` 必须在 `await websocket.accept()` 之前调用，Starlette 会在握手阶段以 `1008` 拒绝连接。调用 `websocket.close()` 需要先 `accept`，鉴权失败场景禁止使用。

---

## 4. Broadcaster（broadcaster.py）

**单全局 psubscribe，整个进程只占 1 条 Redis 连接。**

```python
class Broadcaster:
    def __init__(self) -> None:
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
        self._channels.setdefault(channel, set()).add(ws)

    async def unsubscribe(self, channel: str, ws: WebSocket) -> None:
        sockets = self._channels.get(channel, set())
        sockets.discard(ws)
        if not sockets:
            self._channels.pop(channel, None)

    def _extract_execution_id(self, channel: str) -> str | None:
        """从 'channel:execution:{id}:events' 提取 execution_id。"""
        parts = channel.split(":")
        # 格式固定：channel / execution / {id} / events → 4 段
        if len(parts) == 4 and parts[0] == "channel" and parts[3] == "events":
            return parts[2]
        return None

    async def _listen_loop(self) -> None:
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
                sockets = list(self._channels.get(channel, set()))
                for ws in sockets:
                    try:
                        await ws.send_text(data)
                    except Exception:
                        # 静默忽略；handlers.on_disconnect 的 finally 负责清理
                        pass
        except asyncio.CancelledError:
            pass

    def _clear_for_test(self) -> None:
        """仅供测试使用：清空进程内连接映射，防止用例间污染。"""
        self._channels.clear()


# 模块级单例，gateway.py 和 main.py 直接 import
broadcaster = Broadcaster()
```

---

## 5. handlers.py — 连接生命周期

```python
async def on_connect(
    ws: WebSocket,
    execution_id: str,
    user_id: str,
    session_mgr: SessionManager,
) -> str:
    """accept + 写 M3 Session + 注册 broadcaster，返回 session_id。"""
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
    """注销 broadcaster + 删 M3 Session。"""
    channel = get_channel_events(execution_id)
    await broadcaster.unsubscribe(channel, ws)
    await session_mgr.delete(session_id)
```

**gateway.py 完整连接循环**：

```python
async def handle_connection(
    websocket: WebSocket,
    execution_id: str,
    user_id: str,
) -> None:
    session_mgr = SessionManager(await _get_redis_client())
    session_id = await on_connect(websocket, execution_id, user_id, session_mgr)
    try:
        while True:
            await websocket.receive_text()  # 保持连接，忽略客户端上行消息
    except WebSocketDisconnect:
        pass
    finally:
        await on_disconnect(session_id, execution_id, websocket, session_mgr)
```

---

## 6. main.py 改动

`Broadcaster` 挂载到 `lifespan`，保证容器平滑重启时资源优雅释放：

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    redis = await _get_redis_client()
    await broadcaster.start(redis)
    yield
    await broadcaster.stop()
    await close_redis()
```

路由注册追加 websocket router：

```python
from app.websocket.gateway import router as ws_router
app.include_router(ws_router)   # 无前缀，路径为 /ws/executions/{id}
```

---

## 7. 错误处理总表

| 场景 | 处理 | 负责方 |
|------|------|--------|
| JWT 无效/过期/类型错 | `raise WebSocketException(code=1008)` | gateway.py |
| 用户不存在/inactive | 同上 | gateway.py |
| 发送时 WebSocket 已断开 | 捕获 `Exception`，静默跳过 | broadcaster._listen_loop |
| Redis 连接断开 | `_listen_loop` 抛 `ConnectionError` → task 结束 | broadcaster（lifespan stop 兜底） |
| `on_disconnect` 重复调用 | `SessionManager.delete` 幂等（DEL 不存在 key 不报错） | handlers.py |
| `receive_text` 收到客户端主动 close | 抛 `WebSocketDisconnect` → finally 清理 | gateway.py handle_connection |

---

## 8. 测试策略

**测试工具**：`httpx.AsyncClient`（触发 lifespan）+ `pytest-asyncio`，**不使用** 同步 `TestClient`（不触发 lifespan，broadcaster.start 不执行）。

**测试隔离**：每个测试用例结束后调用 `broadcaster._clear_for_test()` 清空进程内映射。

### 8.1 核心用例

**Happy path（广播端到端）**：

```python
async def test_websocket_broadcast_happy_path(test_app, redis_client, valid_token):
    execution_id = "test-exec-ws-001"
    channel = get_channel_events(execution_id)
    payload = '{"event_type":"agent_spawn","stage":"INIT"}'

    async with AsyncClient(app=test_app, base_url="http://test") as client:
        async with client.websocket_connect(
            f"/ws/executions/{execution_id}?token={valid_token}"
        ) as ws:
            await asyncio.sleep(0.05)   # 等待 subscribe 写入 _channels
            await redis_client.publish(channel, payload)
            received = await ws.receive_text()
            assert received == payload

    broadcaster._clear_for_test()
```

**鉴权失败**：

```python
async def test_websocket_auth_failure(test_app):
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with pytest.raises(Exception) as exc:
            async with client.websocket_connect(
                "/ws/executions/any-id?token=bad_token"
            ):
                pass
        assert "1008" in str(exc.value)
```

**`_extract_execution_id` 单元测试**（无需 Redis）：

```python
def test_extract_execution_id():
    b = broadcaster
    assert b._extract_execution_id("channel:execution:abc-123:events") == "abc-123"
    assert b._extract_execution_id("channel:execution::events") == ""
    assert b._extract_execution_id("bad:format") is None
```

---

## 9. 完成标准（DoD）

- [ ] `ws://localhost:8000/ws/executions/{id}?token=<valid JWT>` 连接成功
- [ ] Redis publish 一条消息，WebSocket 客户端收到完全相同的帧
- [ ] 无效 token 连接被以 `1008` 拒绝（握手阶段，未 accept）
- [ ] 进程关闭时 `broadcaster.stop()` 优雅 punsubscribe + cancel task
- [ ] `uv run ruff check app/websocket/` 无输出
- [ ] `_extract_execution_id` 单元测试通过
- [ ] 集成测试（happy path + auth failure）通过

---

## 10. 与相邻模块的契约

| 模块 | 接触点 |
|------|--------|
| M2 协议层 | 不直接交互；broadcaster 透传 Redis 消息原文（JSON字符串），不解析 |
| M3 state_manager | `SessionManager` 管理会话；`keys.get_channel_events()` 获取 channel 名 |
| M6 Orchestrator | 写 Redis channel，触发广播；M4 不感知 M6 内部逻辑 |
| Phase 1 auth | `verify_token()` 复用；不查数据库（无需 AsyncSession 依赖） |
