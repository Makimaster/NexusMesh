# M3 Redis 状态机设计文档

**版本**：1.0.0
**日期**：2026-07-02
**状态**：已审定，待实施
**上游文档**：[模块路线图](./2026-07-01-module-roadmap.md) §M3

---

## 1. 定位与职责

M3 是 NexusMesh 的**热状态访问层**，管理 Agent 执行期的三类运行时状态：

| 类型 | 维度 | 说明 |
|------|------|------|
| Agent 上下文 | per agent-run | 系统提示、中间结果、对话历史片段 |
| 会话 | per WS连接 | 用户身份、当前订阅的 execution_id |
| 执行任务态 | per workflow-execution | 协议阶段、状态、当前 agent、版本号 |

**边界约束**：
- M3 仅操作 Redis，不读写 PostgreSQL（PG 写入由 M6 Orchestrator 负责）
- 无 HTTP 路由，无 FastAPI 依赖，可完全独立单测
- 仅依赖 `common/redis_client`（已有）

---

## 2. 架构方案

**三个独立 Manager 类，构造函数注入 `redis.asyncio.Redis`**，与 Phase 1 `AuthService(session)` 风格一致。

```
backend/app/state_manager/
├── __init__.py          # 导出三个 Manager 类
├── context.py           # AgentContextManager
├── session.py           # SessionManager
├── task_state.py        # TaskStateManager（含乐观锁）
├── keys.py              # 全部键名与 channel 参数化函数
└── exceptions.py        # ConcurrencyError
```

**依赖关系**：

```
M6 Orchestrator
  ├── TaskStateManager(redis)    ← 驱动五阶段流转
  └── AgentContextManager(redis) ← 读写 Agent 工作内存

M4 WebSocket Gateway
  └── SessionManager(redis)      ← 查询订阅关系；断线时 delete_session
      keys.py                    ← 订阅 Pub/Sub channel 名
```

---

## 3. 键命名规范（keys.py）

所有 Redis 键名和 Pub/Sub channel 名**集中在 `keys.py` 以参数化函数形式定义**，M3 和 M4 均从此处 import，杜绝字符串漂移。

```python
# backend/app/state_manager/keys.py

# ─── 状态键 ─────────────────────────────────────────────────
def get_agent_context_key(execution_id: str, agent_id: str) -> str:
    return f"agent_context:{execution_id}:{agent_id}"


def get_session_key(session_id: str) -> str:
    return f"session:{session_id}"


def get_task_state_key(execution_id: str) -> str:
    return f"task_state:{execution_id}"


# ─── Pub/Sub 广播通道（M4 订阅同一份） ───────────────────────
def get_channel_status(execution_id: str) -> str:
    return f"channel:execution:{execution_id}:status"


def get_channel_events(execution_id: str) -> str:
    return f"channel:execution:{execution_id}:events"
```

---

## 4. 自定义异常（exceptions.py）

```python
# backend/app/state_manager/exceptions.py

class ConcurrencyError(RuntimeError):
    """task_state 乐观锁冲突，超过最大重试次数时抛出。
    由 M6 Orchestrator 捕获后决策：中止当前调度步骤或上层重试。
    """
```

---

## 5. AgentContextManager（context.py）

**存储结构**：`STRING`，值为 `json.dumps(data)`
**TTL**：`86400` 秒（24 小时），每次 `set` 时续期

### 5.1 接口

```python
class AgentContextManager:
    TTL = 86400

    def __init__(self, redis: redis.asyncio.Redis) -> None: ...

    async def set(
        self, execution_id: str, agent_id: str, data: dict
    ) -> None:
        """写入或更新 Agent 上下文，同时刷新 TTL。"""

    async def get(
        self, execution_id: str, agent_id: str
    ) -> dict | None:
        """读取上下文；键不存在或已过期返回 None。"""

    async def delete(
        self, execution_id: str, agent_id: str
    ) -> None:
        """显式删除（Agent 正常完成时调用，早于 TTL 释放内存）。"""
```

### 5.2 行为约定

- `get` 返回 `None` 时由调用方（M6）决策：重新初始化还是报错
- JSON 解码失败抛原始 `json.JSONDecodeError`，上浮
- 不做内容校验，context 结构由 M6 自行定义

---

## 6. SessionManager（session.py）

**存储结构**：`HASH`，字段：`user_id` / `subscribed_execution_id` / `connected_at`（ISO 字符串）
**TTL**：`3600` 秒（60 分钟，对齐 JWT 有效期）

### 6.1 接口

```python
class SessionManager:
    TTL = 3600

    def __init__(self, redis: redis.asyncio.Redis) -> None: ...

    async def create(
        self, session_id: str, user_id: str, execution_id: str
    ) -> None:
        """建立会话，写入订阅关系与时间戳。"""

    async def get(self, session_id: str) -> dict | None:
        """读取会话；键不存在或已过期返回 None。"""

    async def update_subscription(
        self, session_id: str, execution_id: str
    ) -> None:
        """前端切换看板时，单独更新 subscribed_execution_id 字段（HSET 单字段）。"""

    async def delete(self, session_id: str) -> None:
        """M4 WebSocket 断线时调用，清理热状态。"""
```

### 6.2 行为约定

- `update_subscription` 只修改一个 HASH 字段，不重写整个 key，不重置 TTL
- `delete` 在 M4 断线处理器中被调用，M6 不感知

---

## 7. TaskStateManager（task_state.py）

**存储结构**：`HASH`，字段：`status` / `protocol_stage` / `current_agent_id` / `version`（整数字符串）
**TTL**：`604800` 秒（7 天，保留已完成执行供 M15 可观测性回溯）

### 7.1 合法状态值

| 字段 | 合法值 |
|------|--------|
| `status` | `pending` / `running` / `completed` / `failed` |
| `protocol_stage` | `INIT` / `RECEIVE` / `ROUTE` / `EXECUTE` / `FINISH` |

> M3 **不做枚举校验**——字符串合法性由 M2 `ProtocolStage`/`EventType` 在 M6 层保证；M3 只负责原子写入。

### 7.2 接口

```python
class TaskStateManager:
    TTL = 604800
    MAX_RETRIES = 3

    def __init__(self, redis: redis.asyncio.Redis) -> None: ...

    async def create(
        self, execution_id: str, initial_stage: str = "INIT"
    ) -> None:
        """初始化执行态，version=0，status=pending。"""

    async def get(self, execution_id: str) -> dict | None:
        """读取当前执行态；键不存在返回 None。"""

    async def transition(
        self,
        execution_id: str,
        new_stage: str,
        new_status: str,
        agent_id: str | None = None,
    ) -> None:
        """以乐观锁原子更新执行态。
        超过 MAX_RETRIES 次冲突后抛 ConcurrencyError。
        """

    async def delete(self, execution_id: str) -> None:
        """显式删除（一般不需要，TTL 自然过期即可）。"""
```

### 7.3 transition() 乐观锁逻辑

```
for attempt in range(MAX_RETRIES):
    WATCH task_state:{execution_id}
    读取 version（不存在则 unwatch + 抛 ValueError）
    MULTI
      HSET status=new_status, protocol_stage=new_stage,
           current_agent_id=agent_id, version=version+1
      EXPIRE key TTL        ← 每次流转顺便刷新生命周期
    EXEC
    若 EXEC 返回非 None → 成功，return
    若 EXEC 返回 None   → 被抢占
    await asyncio.sleep(0.005 * (2**attempt))  ← 指数退避防活锁

抛 ConcurrencyError
```

---

## 8. 错误处理总表

| 场景 | 处理方式 | 捕获方 |
|------|---------|--------|
| `transition()` 乐观锁超限 | 抛 `ConcurrencyError` | M6 Orchestrator |
| `get()` 键不存在/已过期 | 返回 `None` | 调用方 |
| JSON 解码失败（context） | 抛 `json.JSONDecodeError` | 上浮 |
| Redis 连接断开 | 抛 `redis.exceptions.ConnectionError` | 上浮 |
| `transition()` 目标 key 不存在 | 抛 `ValueError` | M6 Orchestrator |

---

## 9. 测试策略

**测试类型**：集成测试（对真实 Redis，非 Mock），放在 `tests/integration/`。

**pytest 配置**（追加至 `pyproject.toml`）：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

**Redis fixture**（使用 DB 1，与 DB 0 开发环境隔离）：

```python
@pytest.fixture
async def redis_client():
    client = redis.asyncio.from_url("redis://localhost:6379/1")
    yield client
    await client.flushdb()   # 测试结束后清理，防止脏数据
    await client.aclose()
```

### 9.1 AgentContextManager 用例

| 用例 | 断言 |
|------|------|
| `set` → `get` | 值完全一致 |
| `set` 后 key 存在 TTL | `ttl > 0` |
| `delete` 后 `get` | 返回 `None` |
| key 从未创建时 `get` | 返回 `None` |

### 9.2 SessionManager 用例

| 用例 | 断言 |
|------|------|
| `create` → `get` | 三字段均正确 |
| `update_subscription` | 只改 `subscribed_execution_id`，`user_id` 不变 |
| `delete` → `get` | 返回 `None` |

### 9.3 TaskStateManager 用例

| 用例 | 断言 |
|------|------|
| `create` → `get` | `status=pending`，`version=0`，`protocol_stage=INIT` |
| `transition` happy path | `version` 递增为 1，字段更新正确 |
| `transition` 后 TTL 刷新 | `ttl > 0` |
| key 不存在时 `transition` | 抛 `ValueError` |

### 9.4 并发测试（DoD 核心）

```python
async def test_concurrent_transition_raises(redis_client):
    mgr = TaskStateManager(redis_client)
    execution_id = "test-exec-concurrent-001"
    await mgr.create(execution_id)

    # 强制重试上限为 1，确保乐观锁冲突必触发
    mgr.MAX_RETRIES = 1

    tasks = [
        mgr.transition(execution_id, "RECEIVE", "running"),
        mgr.transition(execution_id, "ROUTE", "running"),
        mgr.transition(execution_id, "EXECUTE", "running"),
        mgr.transition(execution_id, "FINISH", "completed"),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = sum(1 for r in results if r is None)
    error_count = sum(1 for r in results if isinstance(r, ConcurrencyError))

    assert success_count >= 1        # 至少一个成功
    assert error_count >= 1          # 至少一个被乐观锁拦截
    assert success_count + error_count == len(tasks)  # 无遗漏
```

---

## 10. 完成标准（DoD）

- [ ] `uv run pytest tests/integration/test_state_manager.py -v` 全部通过
- [ ] 并发测试可稳定复现 `ConcurrencyError`（`MAX_RETRIES=1` 下 4 路并发必触发）
- [ ] `uv run ruff check app/state_manager/` 无输出
- [ ] `from app.state_manager import AgentContextManager, SessionManager, TaskStateManager` 可正常导入
- [ ] `keys.py` 中所有函数 M3 与 M4 均可直接 import，无重复字符串定义
- [ ] `ConcurrencyError` 可被 `from app.state_manager import ConcurrencyError` 导入

---

## 11. 与相邻模块的契约

| 模块 | 与 M3 的接触点 |
|------|--------------|
| M2 协议层 | 不直接交互；M6 负责将 M2 `ProtocolStage` 值传入 `transition()` |
| M4 WebSocket | 使用 `SessionManager` 查询订阅；import `keys.py` 订阅 channel |
| M6 Orchestrator | 主要消费方；驱动 `TaskStateManager.transition()` 和 `AgentContextManager` |
| M15 可观测性 | `task_state:*` TTL=7d 保留，供监控脚本回溯；不需要 M3 提供额外接口 |
