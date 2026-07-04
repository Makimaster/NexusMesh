# M6 Orchestrator 核心 — 设计文档

**版本**：1.0.0
**日期**：2026-07-04
**状态**：已确认，待实现
**上游文档**：[模块路线图](./2026-07-01-module-roadmap.md) §M6

---

## 1. 职责定位

M6 Orchestrator 是 NexusMesh 的**编排引擎核心（DeepAgents）**，驱动一次工作流执行走完 INIT→RECEIVE→ROUTE→EXECUTE→FINISH 五阶段协议，串联 M2（协议封包）、M3（热状态）、M5（LLM 调用），并将事件双写到 Redis（实时广播）与 PostgreSQL（持久化追踪）。

**职责边界**：
- ✅ 创建工作流执行实例、驱动五阶段状态机流转
- ✅ 静态 DAG 路由（`router.py`），决定下一跳 Agent
- ✅ 从 PG 加载 Agent 配置并实例化可执行的 `BaseAgent`
- ✅ 调用 M5 流式补全，实时广播 token + 阶段事件
- ✅ 失败收口：任何异常统一收敛为 `FINISH(success=False)` + `workflow_executions.status=failed`
- ❌ **不做**：HTTP 路由（M8）、业务 CRUD（M7）、LLM 底层适配（M5）、Redis 读写原语（M3）、节点级重试/降级路由（Phase 3）

---

## 2. 五大架构支柱（决策锁定）

本设计经完整头脑风暴对齐，五个核心决策已锁死：

| # | 支柱 | 决策 | 一句话理由 |
|---|---|---|---|
| 1 | 触发入口 | **M7 同步调用 `Coordinator.start_execution()`，内部 `asyncio.create_task` 后台异步流转（Fire-and-Forget）** | 保持同进程单向依赖的干净，同时不阻塞 HTTP 响应 |
| 2 | 路由范式 | **「A 壳 C 心」：MVP 走静态 DAG 查表；topology 强类型结构预留 LLM Handoff 切面** | 零 LLM 路由开销跑通五阶段，未来无需重构调度层 |
| 3 | 文件职责 | **4+1 文件：coordinator / scheduler / router / base_agent + event_emitter（横切双写）** | 事件封包发布是横切关注点，抽出后四个核心文件只管调度 |
| 4 | 持久化 | **EventEmitter 双写网关（PG 短事务 + Redis 广播）；仅此文件 + scheduler 允许依赖 db/models** | 双写天然一致，DB 依赖隔离在单个横切文件 |
| 5 | 失败语义 | **顶层 try/except 兜底 → 失败也发 FINISH(success=False)；单 Agent 失败 = 整个 execution 失败（快速失败）** | 前端必收到终结信号；MVP 不做节点级重试 |

---

## 3. 演进边界：何时从 A 升级到 C（ADR）

选项 A（`create_task` 后台协程）与 API 进程共享生命周期，这是其根本软肋。下列任一信号出现即触发升级到 C 方案（独立 Worker 进程消费 Redis 队列）：

| 触发信号 | 本质原因 | 紧迫度 |
|---|---|---|
| **执行不能丢** | 进程重启/OOM 时 `create_task` 协程被杀，工作流中途丢失且无法恢复 | 🔴 硬约束 |
| **单机扛不住并发** | 大量长耗时 LLM 协程堆积，挤占 API 进程内存与事件循环，HTTP P99 抖动 | 🟠 SLA 退化 |
| **需要横向扩展** | 编排负载需独立于 API 层水平扩容，单进程事件循环触顶 | 🟠 容量瓶颈 |
| **需要重试/削峰** | `create_task` 无 at-least-once 保证，需死信队列、任务重试、流量削峰 | 🟡 可靠性 |

**量化建议**：并发长任务数持续逼近单机上限（数十~上百），或发生过一次「部署导致执行丢失且业务不可接受」的事故 —— 满足其一即启动迁移。届时只需新增 `worker.py` 消费循环复用 `Coordinator._execute_workflow_loop`，M6 核心调度代码零改动。

---

## 4. 文件结构

```
backend/app/orchestrator/
├── __init__.py         # 导出 Coordinator 门面
├── coordinator.py      # 核心引擎：门面 + 顶层 try/except + 五阶段 _execute_workflow_loop
├── scheduler.py        # Agent 工厂：短事务查 PG 加载配置 → 实例化 BaseAgent；执行结算落库
├── router.py           # 纯净静态 DAG 查表器；预留 Phase 3 LLM Handoff 抽象切面
├── base_agent.py       # 内聚单 Agent 执行：调 M5 → 流式 emit_token → 累积 → 产 ExecutePayload
├── event_emitter.py    # 横切双写网关：复用 M2 序列化，emit_event 走 await 短事务落库
└── exceptions.py       # OrchestratorError（编排层统一异常，可选）
```

**依赖纯净性约束（对路线图 §5.2 的正式修正案）**：

- 路线图原声明 `orchestrator/ → state_manager/ → common/`，遗漏了 M6 对 `models/` 与 `db/` 的合法依赖。M3 设计文档 §1 已明确「PG 写入由 M6 负责」，此处正式补齐。
- **仅允许** `event_emitter.py` 与 `scheduler.py` 向上引用 `app/db/session.py`（`AsyncSessionLocal`）与 `app/models/`（ORM 实体）。
- `coordinator.py`、`base_agent.py`、`router.py` **保持绝对纯净**，不感知任何数据库与 ORM。

---

## 5. 组件职责与协作链

### 5.1 五阶段生命周期流转节奏

```
start_execution(execution_id)                    ← M7 调用，同步返回
  └─ asyncio.create_task(_execute_workflow_loop) ← 后台异步接管

_execute_workflow_loop(execution_id):            ← Coordinator 持有
  ┌─ try:
  │  1. [INIT]    TaskStateManager.create → emit_event(INIT, agent_spawn)
  │  2. [RECEIVE] 读 execution.input     → emit_event(RECEIVE, agent_call)
  │  3. current_node = None; while True:
  │       A. [ROUTE]  decision = Router.route_next(current_node, topology)
  │                   emit_event(ROUTE, agent_call, RoutePayload(decision))
  │                   若 decision.next_node_id is None → break
  │       B. [SCHED]  agent = Scheduler.load_agent(decision.next_agent_id)  ← 短事务查 PG
  │       C. [EXEC]   payload = await agent.run(execution_id, ...)
  │                     └─ BaseAgent 内部高频循环:
  │                          M5.stream_completion → LLMStreamChunk
  │                          token/reasoning → emit_token(高频纯广播)
  │                          usage 尾帧 → 组装 ExecutePayload
  │                   emit_event(EXECUTE, agent_finish, payload)
  │                   current_node = decision.next_node_id
  │  4. [FINISH]  emit_event(FINISH, agent_finish, success=True)
  │               Scheduler.settle_execution(status=completed, output=...)
  └─ except (LLMServiceError, ConcurrencyError, Exception) as e:
        emit_event(FINISH, agent_finish, success=False, error=...)
        Scheduler.settle_execution(status=failed, error=...)
```

### 5.2 各组件一句话职责

| 组件 | 职责 | 依赖 |
|---|---|---|
| **Coordinator** | 门面 + 五阶段主循环 + 顶层失败收口 | EventEmitter、Scheduler、Router、TaskStateManager |
| **Router** | 输入 `current_agent_id + topology` → 输出 `RoutePayload`（静态查表） | 无（纯函数式，无状态） |
| **Scheduler** | 短事务查 PG 加载 Agent 配置 → `new BaseAgent`；执行结算落库 | db/session、models、LLMService、EventEmitter |
| **BaseAgent** | 单 Agent 一次 EXECUTE：组 prompt → 调 M5 → 流式 emit_token → 产 ExecutePayload | LLMService、EventEmitter、AgentContextManager |
| **EventEmitter** | 双写网关：M2 封包 → Redis 广播 +（低频）PG 短事务落库 | redis、db/session、models、protocol |

---

## 6. Topology JSONB 契约（对齐 React Flow 12.x）

`Workflow.topology` 首代强类型结构，前端 `@xyflow/react` 节点/边快照可直接映射：

```json
{
  "nodes": [
    { "id": "node-1", "type": "agent", "data": { "agent_id": "<uuid>" } },
    { "id": "node-2", "type": "agent", "data": { "agent_id": "<uuid>" } }
  ],
  "edges": [
    {
      "id": "edge-1",
      "source": "node-1",
      "target": "node-2",
      "data": { "condition": "default" }
    }
  ]
}
```

**MVP 路由规则（node 空间查表）**：
- 起点约定：首代取「无入边的第一个 node」为入口（即不作为任何 `edge.target` 的 node）。`current_node_id=None` 时 Router 返回入口 node。
- `route_next`：顺 `edges` 找 `source == current_node_id` 的第一条边，取其 `target` node，返回 `RouteDecision(next_node_id=target, next_agent_id=target_node.data.agent_id, reason=...)`。
- 找不到出边 → 叶子节点 → 返回 `RouteDecision(None, None, ...)` → Coordinator 跳出循环进 FINISH。
- `data.condition` 首代仅识别 `"default"`；Phase 3 识别 `"llm_handoff"` 时在 `route_next` 内原地调 M5 在合法出边中决策。

> **注意**：topology 的 `data.agent_id` 是字符串，Scheduler 通过 `uuid.UUID(agent_id)` 转为 PG 原生 UUID 查库；非法字符串或查无此 Agent → 抛异常 → 快速失败。

---

## 7. 组件接口设计

### 7.1 Coordinator（门面 + 主循环）

```python
# backend/app/orchestrator/coordinator.py
import asyncio

import redis.asyncio as redis

from app.orchestrator.event_emitter import EventEmitter
from app.orchestrator.router import AgentRouter
from app.orchestrator.scheduler import Scheduler
from app.services.llm_service import LLMService
from app.state_manager.task_state import TaskStateManager


class Coordinator:
    """M6 编排引擎门面。对 M7 暴露唯一入口 start_execution()。"""

    def __init__(self, redis_client: redis.Redis, llm_service: LLMService) -> None:
        self._emitter = EventEmitter(redis_client)
        self._task_state = TaskStateManager(redis_client)
        self._router = AgentRouter()
        self._scheduler = Scheduler(llm_service, self._emitter)

    async def start_execution(self, execution_id: str) -> None:
        """唯一对外总入口（M7 调用）。触发后立即返回，不阻塞 HTTP 响应。"""
        asyncio.create_task(self._execute_workflow_loop(execution_id))

    async def _execute_workflow_loop(self, execution_id: str) -> None:
        """五阶段协议状态机主循环（后台协程）。见 §5.1 节奏。"""
        ...
```

**依赖注入链路（§5 支柱 5 + 六点定稿 ⑤）**：
- Coordinator 在应用启动时由 M7 构造，注入共享 `redis_client` 与 `LLMService(settings)`（手动注入，非 FastAPI 请求作用域）。
- Coordinator 内部显式 `new` 出 EventEmitter / TaskStateManager / Router / Scheduler，无副作用。
- Scheduler 自建短事务 `AsyncSessionLocal`，Coordinator 不感知 DB。

### 7.2 AgentRouter（静态 DAG 查表）

```python
# backend/app/orchestrator/router.py
from dataclasses import dataclass
from typing import Any


@dataclass
class RouteDecision:
    """一次路由结果。next_node_id/next_agent_id 同为 None 表示已到叶子节点。"""

    next_node_id: str | None
    next_agent_id: str | None
    reason: str


class AgentRouter:
    """ROUTE 阶段内核：静态拓扑查表。无状态、无副作用、微秒级。"""

    def route_next(
        self, current_node_id: str | None, topology: dict[str, Any]
    ) -> RouteDecision:
        """决定下一跳。current_node_id=None 表示求入口节点。

        路由在 **node 空间** 进行（topology.edges 的 source/target 是 node id），
        再从目标 node.data.agent_id 取出 Agent。
        - next_node_id 非 None：流转到该节点，next_agent_id 供 Scheduler 加载
        - 均为 None：叶子节点，Coordinator 进入 FINISH
        """
        ...
```

**node_id vs agent_id（歧义定音）**：topology 的 `edges.source/target` 是**节点 id**（如 `node-1`），Agent 挂在 `node.data.agent_id`。二者不同空间。因此：
- Router 在 node 空间查表，主循环追踪 `current_node_id`（非 agent_id）。
- Router 返回内部 `RouteDecision`（含 `next_node_id` + `next_agent_id`），**不复用 M2 `RoutePayload` 作为返回值** —— 因为 M2 的 `RoutePayload` 只有 `next_agent_id`，不足以驱动下一跳的 node 查表。
- Coordinator 拿 `RouteDecision` 后：用 `next_agent_id` 交 Scheduler 加载 Agent；用 `next_node_id` 更新循环游标；同时构造 M2 `RoutePayload(next_agent_id, routing_reason=reason)` 封包成 ROUTE 事件交 EventEmitter 广播落库。

### 7.3 Scheduler（Agent 工厂 + 执行结算）

```python
# backend/app/orchestrator/scheduler.py
import uuid

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.execution import WorkflowExecution
from app.orchestrator.base_agent import BaseAgent
from app.orchestrator.event_emitter import EventEmitter
from app.services.llm_service import LLMService


class Scheduler:
    """Agent 实例化工厂 + workflow_executions 结算落库。"""

    def __init__(self, llm_service: LLMService, emitter: EventEmitter) -> None:
        self._llm = llm_service
        self._emitter = emitter

    async def load_agent(self, agent_id: str) -> BaseAgent:
        """短事务查 PG 加载 Agent 配置，工厂化 new 出 BaseAgent。

        agent_id 非法或查无此 Agent → 抛异常（快速失败）。
        """
        async with AsyncSessionLocal() as session:
            row = await session.get(Agent, uuid.UUID(agent_id))
        if row is None:
            raise ValueError(f"Agent 不存在: {agent_id}")
        return BaseAgent(
            agent_id=agent_id,
            llm_model=row.llm_model,
            system_prompt=row.system_prompt,
            llm_service=self._llm,
            emitter=self._emitter,
        )

    async def settle_execution(
        self,
        execution_id: str,
        status: str,
        output: dict | None = None,
        error: str | None = None,
    ) -> None:
        """短事务更新 workflow_executions 最终状态（completed / failed）。"""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                exec_row = await session.get(
                    WorkflowExecution, uuid.UUID(execution_id)
                )
                if exec_row is not None:
                    exec_row.status = status
                    exec_row.output = output
                    exec_row.error = error
```

### 7.4 BaseAgent（单 Agent 执行）

```python
# backend/app/orchestrator/base_agent.py
from app.orchestrator.event_emitter import EventEmitter
from app.protocol import ExecutePayload
from app.services.llm_service import LLMService


class BaseAgent:
    """单个 Agent 的一次 EXECUTE。内聚 token 拼接、思维链、用量结算。"""

    def __init__(
        self,
        agent_id: str,
        llm_model: str,
        system_prompt: str | None,
        llm_service: LLMService,
        emitter: EventEmitter,
    ) -> None:
        self._agent_id = agent_id
        self._llm_model = llm_model
        self._system_prompt = system_prompt
        self._llm = llm_service
        self._emitter = emitter

    async def run(self, execution_id: str, task_input: dict) -> ExecutePayload:
        """执行一次 LLM 补全，原地流式广播 token，返回 ExecutePayload。

        - chunk.token / reasoning_content → emit_token（高频纯广播，不落库）+ 累积
        - chunk.usage 尾帧 → 组装 ExecutePayload（model 取自 self._llm_model）
        """
        messages = self._build_messages(task_input)
        buffer: list[str] = []
        payload = None
        async for chunk in self._llm.stream_completion(
            messages=messages, model=self._llm_model
        ):
            if chunk.token:
                buffer.append(chunk.token)
                await self._emitter.emit_token(
                    execution_id, self._agent_id, chunk.token
                )
            if chunk.reasoning_content:
                await self._emitter.emit_token(
                    execution_id, self._agent_id,
                    chunk.reasoning_content, reasoning=True,
                )
            if chunk.usage:
                payload = ExecutePayload(
                    agent_message="".join(buffer),
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    model=self._llm_model,          # 六点定稿 ③：来自 Agent.llm_model
                    model_cost_usd=chunk.usage.model_cost_usd,
                )
        if payload is None:  # 厂商未回 usage 尾帧的兜底
            payload = ExecutePayload(
                agent_message="".join(buffer),
                prompt_tokens=0, completion_tokens=0,
                model=self._llm_model, model_cost_usd=0.0,
            )
        return payload
```

> `ExecutePayload` 复用 M2，字段 `agent_message` / `prompt_tokens` / `completion_tokens` / `model` / `model_cost_usd` 与 M5 `UsageStats` + `Agent.llm_model` 完全对齐（M5 设计文档 §3.1 已确认此映射）。

### 7.5 EventEmitter（双写网关）

```python
# backend/app/orchestrator/event_emitter.py
import json
import uuid

import redis.asyncio as redis
from loguru import logger

from app.db.session import AsyncSessionLocal
from app.models.event import ExecutionEvent
from app.protocol import ProtocolEvent, to_payload
from app.state_manager.keys import get_channel_events


class EventEmitter:
    """M6 双写网关：Redis 实时广播 +（低频阶段事件）PG 短事务落库。"""

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def emit_event(self, execution_id: str, event: ProtocolEvent) -> None:
        """低频阶段协议事件：先广播（实时优先），再 await 短事务落库。"""
        data = to_payload(event)               # M2 序列化：字段全铺平进 dict
        channel = get_channel_events(execution_id)
        await self._redis.publish(channel, json.dumps(data))   # 实时优先
        await self._persist(execution_id, event, data)         # await，不 fire-and-forget

    async def emit_token(
        self, execution_id: str, agent_id: str,
        text: str, reasoning: bool = False,
    ) -> None:
        """高频 token 流：仅 Redis 广播，不落库（避免高频 I/O 压垮 PG）。"""
        channel = get_channel_events(execution_id)
        frame = {
            "event_type": "agent_chunk_stream",
            "agent_id": agent_id,
            "text": text,
            "reasoning": reasoning,
        }
        await self._redis.publish(channel, json.dumps(frame))

    async def _persist(
        self, execution_id: str, event: ProtocolEvent, data: dict
    ) -> None:
        """短事务落库，Fail-Safe：PG 挂了记 CRITICAL 日志，不阻断调度。"""
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    session.add(ExecutionEvent(
                        execution_id=uuid.UUID(execution_id),
                        protocol_stage=event.protocol_stage.value,
                        event_type=event.event_type.value,
                        payload=data,                # 全部铺平进 JSONB
                    ))
        except Exception as exc:
            logger.critical(f"[M6 EventEmitter] 事件持久化失败: {exc}")
```

**关键纠正记录（对齐真实 ORM）**：
- `ExecutionEvent` 实际列仅有 `id / execution_id / protocol_stage / event_type / payload / created_at`（见 [event.py](../../../backend/app/models/event.py)）。**没有** `agent_id` / `token_count` / `stage` 列 —— 这些语义全部铺平进 `payload` JSONB。
- 落库用 `await`（非 `asyncio.create_task`），保证事件按因果顺序落库、进程停机不丢，守住 M12 Timeline 的完整追踪。
- `emit_token` 高频路径**只广播不落库**；`emit_event` 低频路径（一次执行仅数条）双写。

---

## 8. 数据流与 Redis 通道

### 8.1 单通道设计（六点定稿 ①）

M6 所有事件（阶段协议事件 + token 流）统一走 `get_channel_events(execution_id)` 单通道。前端 M4 只订阅一条线路，靠帧内 `event_type` 区分：

| event_type | 来源 | 落库 | 前端用途 |
|---|---|---|---|
| `agent_spawn` / `agent_call` / `agent_finish` | `emit_event`（阶段事件） | ✅ | 看板状态、Timeline |
| `agent_chunk_stream` | `emit_token`（token 流） | ❌ | LogStream 打字机 |

> `get_channel_status` 通道 MVP 暂不使用；若 M4 已约定其用途，实现时对齐 M4。

### 8.2 完整调用链路

```
M8 REST → M7 WorkflowService
            ├─ PG 建 workflow_executions (status=pending)  [M1]
            └─ await coordinator.start_execution(exec_id)
                 └─ create_task → 立即返回 → M8 响应 202
                                                    │
                        ┌───────────────────────────┘ (后台协程)
                        ▼
              _execute_workflow_loop
                 ├─ 每阶段: emit_event → Redis publish + PG execution_events
                 ├─ EXECUTE: BaseAgent → M5 stream → emit_token (高频广播)
                 └─ FINISH: settle_execution → PG workflow_executions (completed/failed)
                                                    │
                        M4 WebSocket 订阅 channel_events ──→ 前端实时渲染
```

---

## 9. 错误处理与失败语义

### 9.1 顶层兜底收口（§2 支柱 5）

`_execute_workflow_loop` 用单个顶层 `try/except` 包裹全流程，任何未预期异常都保证收口，绝不留下僵尸 `running` 执行：

```python
try:
    # INIT → RECEIVE → 循环(ROUTE → SCHED → EXECUTE) → FINISH(success=True)
    ...
except Exception as e:
    error_msg = f"工作流执行异常: {e}"
    logger.error(f"[M6] execution_id={execution_id} 失败结算: {error_msg}")
    # 1. 发终结信号（双写）：前端 M4 立刻停止转圈、弹错误
    await self._emitter.emit_event(
        execution_id,
        ProtocolEvent(
            protocol_stage=ProtocolStage.FINISH,
            event_type=EventType.AGENT_FINISH,
            payload=FinishPayload(success=False, output={"error": error_msg}),
        ),
    )
    # 2. PG 结算：workflow_executions 标 failed
    await self._scheduler.settle_execution(
        execution_id, status="failed", error=error_msg
    )
```

### 9.2 故障分类处理

| 故障源 | 场景 | 处理 |
|---|---|---|
| `LLMServiceError`（M5） | LLM 鉴权/限流/网络失败 | 顶层捕获 → FINISH(success=False) → status=failed |
| `ConcurrencyError`（M3） | 乐观锁冲突超限 | 单协程串行驱动理论不冲突；若出现视为致命 → 同上 |
| `ValueError`（Router/Scheduler） | topology 断裂 / Agent 不存在 / UUID 非法 | ROUTE 或 SCHED 阶段即失败 → 同上（不进 EXECUTE） |
| 未预期 `Exception` | 任意兜底 | 顶层捕获 → 同上，记 `error` 级日志 |

### 9.3 边界原则

- **快速失败**：单个 Agent 的 EXECUTE 失败 = 整个 execution 失败。不做节点级重试/降级路由（Phase 3）。
- **EventEmitter 落库 Fail-Safe**：PG 写失败仅记 CRITICAL 日志，不阻断调度与 Redis 广播。
- **不吞 `asyncio.CancelledError`**：主动取消（进程停机）透传运行时，不误标 failed。

---

## 10. 测试策略

### 10.1 纯 Mock 单元测试（六点定稿 ⑥）

M6 的核心价值是**编排流程正确性**，而非 Redis/PG 读写正确性。因此把 `EventEmitter`、`Scheduler`、`LLMService` 全部 mock，专注验证 Coordinator 状态机流转逻辑。测试位置：`backend/tests/unit/test_orchestrator.py`。

**核心断言**：给定双 Agent 的 topology，跑完整循环，验证 `mock_emitter.emit_event.call_args_list` 的**事件类型与顺序**：

```
INIT → RECEIVE → ROUTE → EXECUTE → ROUTE → EXECUTE → ROUTE(叶子,None) → FINISH(success=True)
```

### 10.2 单元测试用例清单

| 测试名称 | 验证目标 |
|---|---|
| `test_router_static_next_node` | 静态查表返回正确 `RouteDecision`（next_node_id + next_agent_id） |
| `test_router_leaf_returns_none` | 叶子节点返回 `RouteDecision(None, None, ...)` |
| `test_router_entry_node` | `current_node_id=None` 时返回入口节点 |
| `test_base_agent_accumulates_tokens_and_usage` | token 累积 + 尾帧组装 `ExecutePayload`（mock M5） |
| `test_base_agent_emits_token_stream` | token 流触发 `emit_token`（高频广播） |
| `test_coordinator_single_agent_flow` | 单 Agent：INIT→RECEIVE→ROUTE→EXECUTE→FINISH 事件序列 |
| `test_coordinator_double_agent_flow` | 双 Agent：两跳 EXECUTE，事件顺序正确 |
| `test_coordinator_finish_success_true` | happy path 收口 FINISH(success=True) + settle completed |
| `test_coordinator_llm_error_settles_failed` | M5 抛 `LLMServiceError` → FINISH(success=False) + settle failed |
| `test_coordinator_unknown_agent_fails_fast` | Scheduler 查无 Agent → 快速失败收口 |
| `test_event_emitter_persist_failsafe` | PG 落库异常时 Redis 广播仍执行（mock session 抛错） |
| `test_event_emitter_token_not_persisted` | `emit_token` 只广播不写 PG |

> 全部 mock LLM/Redis/PG，毫秒级运行，无 flaky、不消耗真实配额。

---

## 11. 完成标准（DoD）

| 验收项 | 说明 |
|---|---|
| 双 Agent 端到端 | 给定双 Agent topology，完整跑通五阶段并产出正确事件序列（mock LLM） |
| 事件顺序正确 | `emit_event` 调用序列严格为 INIT→RECEIVE→(ROUTE→EXECUTE)*→FINISH |
| 失败收口 | 任意异常 → FINISH(success=False) + `workflow_executions.status=failed`，无僵尸 running |
| Token 流广播 | EXECUTE 阶段 token 通过 `emit_token` 高频广播，不落库 |
| 双写一致 | 阶段事件同时写 `execution_events`（PG）+ Redis 广播 |
| ORM 对齐 | `ExecutionEvent` 仅填 `protocol_stage`/`event_type`/`payload`，其余语义进 JSONB |
| 依赖纯净 | 仅 `event_emitter.py`/`scheduler.py` 依赖 db/models；其余三文件无 DB 感知 |
| 单测全绿 | `.venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py` 全通过 |
| Ruff 通过 | `ruff check app/orchestrator tests` 无报错 |
| 公共 API 导出 | `from app.orchestrator import Coordinator` 可正常导入 |

---

## 12. 前置依赖与下游影响

| 依赖方向 | 模块 | 说明 |
|---|---|---|
| M6 依赖 | M2 `protocol` | `ProtocolEvent` / `RoutePayload` / `ExecutePayload` / `FinishPayload` / `to_payload` |
| M6 依赖 | M3 `state_manager` | `TaskStateManager` / `AgentContextManager` / `keys.get_channel_events` |
| M6 依赖 | M5 `services.llm_service` | `LLMService.stream_completion` → `LLMStreamChunk` |
| M6 依赖 | M1 `models` + `db` | `Agent` / `WorkflowExecution` / `ExecutionEvent` / `AsyncSessionLocal`（仅限 emitter/scheduler） |
| M7 依赖 M6 | `Coordinator` | M7 构造注入并调用 `start_execution()` |
| M4 依赖 M6 | Redis `channel_events` | M4 订阅同一通道，靠 `event_type` 区分帧 |

> **对路线图 §5.2 的修正案**：正式补齐 `orchestrator/ → models/` 与 `orchestrator/ → db/` 的合法依赖（隔离在 emitter/scheduler 两文件），与 M3 设计文档 §1「PG 写入由 M6 负责」一致。
