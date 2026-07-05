# M6 Orchestrator 核心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 M6 编排引擎，驱动工作流执行走完 INIT→RECEIVE→ROUTE→EXECUTE→FINISH 五阶段协议，串联 M2/M3/M5，并将事件双写到 Redis（实时广播）与 PostgreSQL（持久化）。

**Architecture:** 4+1 文件（coordinator/scheduler/router/base_agent + event_emitter 横切双写）。Coordinator 持有五阶段主循环与顶层失败收口；Router 做静态 DAG 查表；Scheduler 短事务查 PG 加载 Agent 与执行上下文；BaseAgent 消费 M5 流式补全并原地广播 token；EventEmitter 复用 M2 序列化，低频阶段事件双写、高频 token 只广播。仅 event_emitter/scheduler 依赖 db/models，其余三文件 DB-pure。

**Tech Stack:** Python 3.13, Pydantic 2.10, SQLAlchemy 2.0（asyncpg）, redis 5.x（asyncio）, litellm 1.50.*, pytest 8 + pytest-asyncio 0.24（`asyncio_mode=auto`）

---

## 关键实现约束（动工前必读）

1. **日志用 stdlib，不是 loguru**：设计文档代码片段里的 `from loguru import logger` 是笔误。项目统一用 `from app.common.logger import log`（stdlib logging）。所有日志调用写 `log.error(...)` / `log.critical(...)`。
2. **pytest-asyncio 已是 `auto` 模式**：测试函数**不需要** `@pytest.mark.asyncio` 装饰器，`async def test_*` 直接生效。
3. **必须用项目专属 venv 跑测试**：Windows 下 `cd backend && .venv/Scripts/python.exe -m pytest ...`，不能用系统 Python（否则缺 litellm/fastapi 报 ModuleNotFoundError）。
4. **复用 M2 协议对象**：`from app.protocol import ProtocolEvent, ProtocolStage, EventType, InitPayload, ReceivePayload, RoutePayload, ExecutePayload, FinishPayload, to_payload`。不要自造 payload。
5. **复用 M3 键函数**：`from app.state_manager.keys import get_channel_events`；`from app.state_manager.task_state import TaskStateManager`。
6. **ExecutionEvent 真实列**：仅 `id / execution_id / protocol_stage / event_type / payload(JSONB) / created_at`。没有 agent_id/token_count/stage 列。
7. **DB 依赖隔离**：只有 `event_emitter.py`、`scheduler.py` 允许 `from app.db.session import AsyncSessionLocal` 和 `from app.models...`。

---

## 文件结构

| 操作 | 路径 | 职责 |
|------|------|------|
| 创建 | `backend/app/orchestrator/exceptions.py` | `OrchestratorError`（编排层统一异常，可选兜底用） |
| 创建 | `backend/app/orchestrator/router.py` | `RouteDecision` dataclass + `AgentRouter`（静态 DAG 查表，node 空间） |
| 创建 | `backend/app/orchestrator/event_emitter.py` | `EventEmitter` 双写网关（Redis 广播 + PG 短事务落库） |
| 创建 | `backend/app/orchestrator/base_agent.py` | `BaseAgent`（消费 M5 流、累积、产 ExecutePayload、发 token） |
| 创建 | `backend/app/orchestrator/scheduler.py` | `Scheduler`（load_agent / load_execution_context / settle_execution，短事务） |
| 创建 | `backend/app/orchestrator/coordinator.py` | `Coordinator`（门面 + 五阶段主循环 + 顶层失败收口） |
| 修改 | `backend/app/orchestrator/__init__.py` | 导出 `Coordinator` 公共 API（当前为空文件） |
| 创建 | `backend/tests/unit/test_orchestrator.py` | 全部单元测试（纯 mock） |
| 创建 | `backend/tests/integration/test_orchestrator_smoke.py` | 集成 smoke（真实 Redis+PG，mock M5；DoD 加分项） |

**主循环内部契约（供 Coordinator 与测试对齐）**：

```
current_node = None
try:
  ctx = await scheduler.load_execution_context(execution_id)   # workflow_id, topology, task_input
  [INIT]    task_state.create(exec, "INIT")     → emit(INIT,    AGENT_SPAWN, InitPayload(agent_id="orchestrator", workflow_id=ctx.workflow_id))
  [RECEIVE] task_state.transition(RECEIVE,running)→ emit(RECEIVE, AGENT_CALL,  ReceivePayload(task_input=ctx.task_input))
  while True:
    decision = router.route_next(current_node, ctx.topology)
    task_state.transition(ROUTE,running, agent_id=decision.next_agent_id)
    emit(ROUTE, AGENT_CALL, RoutePayload(next_agent_id=decision.next_agent_id, routing_reason=decision.reason))
    if decision.next_node_id is None: break
    agent = await scheduler.load_agent(decision.next_agent_id)
    task_state.transition(EXECUTE,running, agent_id=decision.next_agent_id)
    payload = await agent.run(execution_id, ctx.task_input)     # ExecutePayload
    emit(EXECUTE, AGENT_FINISH, payload)
    current_node = decision.next_node_id
  [FINISH]  task_state.transition(FINISH,completed) → emit(FINISH, AGENT_FINISH, FinishPayload(success=True, output={"message": last_message}))
            scheduler.settle_execution(exec, status="completed", output={"message": last_message})
except Exception as e:
  emit(FINISH, AGENT_FINISH, FinishPayload(success=False, output={"error": str(e)}))
  scheduler.settle_execution(exec, status="failed", error=str(e))
```

单 Agent（1 节点无边）事件序列：`INIT, RECEIVE, ROUTE, EXECUTE, ROUTE(None), FINISH`（6 条）。
双 Agent（node-1→node-2）事件序列：`INIT, RECEIVE, ROUTE, EXECUTE, ROUTE, EXECUTE, ROUTE(None), FINISH`（8 条）。

---

## Task 1: OrchestratorError 异常 + AgentRouter 静态路由

**Files:**
- Create: `backend/app/orchestrator/exceptions.py`
- Create: `backend/app/orchestrator/router.py`
- Test: `backend/tests/unit/test_orchestrator.py`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/unit/test_orchestrator.py`，写入：

```python
"""M6 Orchestrator 单元测试（纯 mock）。"""
from app.orchestrator.router import AgentRouter, RouteDecision


def _topology_double():
    """node-1 → node-2 的双节点拓扑。"""
    return {
        "nodes": [
            {"id": "node-1", "type": "agent", "data": {"agent_id": "aaaaaaaa-0000-0000-0000-000000000001"}},
            {"id": "node-2", "type": "agent", "data": {"agent_id": "aaaaaaaa-0000-0000-0000-000000000002"}},
        ],
        "edges": [
            {"id": "edge-1", "source": "node-1", "target": "node-2", "data": {"condition": "default"}},
        ],
    }


def test_router_entry_node():
    """current_node_id=None → 返回入口节点（无入边的节点）。"""
    router = AgentRouter()
    decision = router.route_next(None, _topology_double())
    assert decision.next_node_id == "node-1"
    assert decision.next_agent_id == "aaaaaaaa-0000-0000-0000-000000000001"


def test_router_static_next_node():
    """current=node-1 → 顺 edge 返回 node-2。"""
    router = AgentRouter()
    decision = router.route_next("node-1", _topology_double())
    assert decision.next_node_id == "node-2"
    assert decision.next_agent_id == "aaaaaaaa-0000-0000-0000-000000000002"


def test_router_leaf_returns_none():
    """叶子节点 node-2 无出边 → RouteDecision(None, None, ...)。"""
    router = AgentRouter()
    decision = router.route_next("node-2", _topology_double())
    assert decision.next_node_id is None
    assert decision.next_agent_id is None


def test_router_single_node_entry_then_leaf():
    """单节点拓扑：入口后即叶子。"""
    topo = {
        "nodes": [{"id": "solo", "type": "agent", "data": {"agent_id": "bbbbbbbb-0000-0000-0000-000000000001"}}],
        "edges": [],
    }
    router = AgentRouter()
    entry = router.route_next(None, topo)
    assert entry.next_node_id == "solo"
    leaf = router.route_next("solo", topo)
    assert leaf.next_node_id is None
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -v
```

期望：`ModuleNotFoundError: No module named 'app.orchestrator.router'`

- [ ] **Step 3: 实现 exceptions.py**

新建 `backend/app/orchestrator/exceptions.py`：

```python
"""M6 编排层统一异常。"""


class OrchestratorError(RuntimeError):
    """编排引擎运行期异常。顶层 try/except 收口后统一标记 execution 为 failed。"""
```

- [ ] **Step 4: 实现 router.py**

新建 `backend/app/orchestrator/router.py`：

```python
"""ROUTE 阶段内核：静态 DAG 查表（node 空间）。

MVP 走确定性静态路由；Phase 3 在此处 route_next 内识别
data.condition == "llm_handoff" 时原地调 M5 在合法出边中决策。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RouteDecision:
    """一次路由结果。

    next_node_id / next_agent_id 同为 None 表示已到叶子节点，
    Coordinator 应据此跳出循环进入 FINISH。
    """

    next_node_id: str | None
    next_agent_id: str | None
    reason: str


class AgentRouter:
    """静态拓扑查表器。无状态、无副作用、微秒级。"""

    def route_next(
        self, current_node_id: str | None, topology: dict[str, Any]
    ) -> RouteDecision:
        """决定下一跳。current_node_id=None 表示求入口节点。"""
        nodes = topology.get("nodes", [])
        edges = topology.get("edges", [])

        if current_node_id is None:
            entry = self._find_entry_node(nodes, edges)
            if entry is None:
                return RouteDecision(None, None, "拓扑无入口节点，直接终结。")
            return RouteDecision(
                entry["id"],
                self._agent_id_of(entry),
                f"静态拓扑入口节点: {entry['id']}。",
            )

        for edge in edges:
            if edge.get("source") == current_node_id:
                target_id = edge.get("target")
                target = self._node_by_id(nodes, target_id)
                if target is None:
                    return RouteDecision(None, None, f"目标节点缺失: {target_id}。")
                return RouteDecision(
                    target_id,
                    self._agent_id_of(target),
                    f"静态拓扑流转至下一节点: {target_id}。",
                )

        return RouteDecision(None, None, "已到达叶子节点，准备结算。")

    @staticmethod
    def _find_entry_node(
        nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """入口节点 = 不作为任何 edge.target 的第一个节点。"""
        targets = {edge.get("target") for edge in edges}
        for node in nodes:
            if node.get("id") not in targets:
                return node
        return None

    @staticmethod
    def _node_by_id(
        nodes: list[dict[str, Any]], node_id: str | None
    ) -> dict[str, Any] | None:
        for node in nodes:
            if node.get("id") == node_id:
                return node
        return None

    @staticmethod
    def _agent_id_of(node: dict[str, Any]) -> str | None:
        return node.get("data", {}).get("agent_id")
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -v
```

期望：`4 passed`

- [ ] **Step 6: 提交**

```bash
git add backend/app/orchestrator/exceptions.py backend/app/orchestrator/router.py backend/tests/unit/test_orchestrator.py
git commit -m "feat: 新增 M6 OrchestratorError 异常与 AgentRouter 静态 DAG 路由"
```

---

## Task 2: EventEmitter 双写网关

**Files:**
- Create: `backend/app/orchestrator/event_emitter.py`
- Test: `backend/tests/unit/test_orchestrator.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `test_orchestrator.py` 末尾追加：

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.orchestrator.event_emitter import EventEmitter
from app.protocol import EventType, InitPayload, ProtocolEvent, ProtocolStage


def _init_event():
    return ProtocolEvent(
        protocol_stage=ProtocolStage.INIT,
        event_type=EventType.AGENT_SPAWN,
        payload=InitPayload(agent_id="orchestrator", workflow_id="wf-1"),
    )


async def test_emit_event_publishes_and_persists():
    """emit_event 先 Redis 广播，再落库 PG（短事务）。"""
    redis = MagicMock()
    redis.publish = AsyncMock()
    emitter = EventEmitter(redis)

    exec_id = "aaaaaaaa-0000-0000-0000-0000000000ff"
    with patch.object(emitter, "_persist", new=AsyncMock()) as persist:
        await emitter.emit_event(exec_id, _init_event())

    redis.publish.assert_awaited_once()
    channel, raw = redis.publish.await_args.args
    assert channel == f"channel:execution:{exec_id}:events"
    data = json.loads(raw)
    assert data["protocol_stage"] == "INIT"
    assert data["event_type"] == "agent_spawn"
    persist.assert_awaited_once()


async def test_emit_token_publishes_only_no_persist():
    """emit_token 只广播，不落库。"""
    redis = MagicMock()
    redis.publish = AsyncMock()
    emitter = EventEmitter(redis)

    exec_id = "aaaaaaaa-0000-0000-0000-0000000000ee"
    with patch.object(emitter, "_persist", new=AsyncMock()) as persist:
        await emitter.emit_token(exec_id, "agent-1", "Hello")

    redis.publish.assert_awaited_once()
    channel, raw = redis.publish.await_args.args
    assert channel == f"channel:execution:{exec_id}:events"
    frame = json.loads(raw)
    assert frame["event_type"] == "agent_chunk_stream"
    assert frame["text"] == "Hello"
    assert frame["reasoning"] is False
    persist.assert_not_awaited()


async def test_emit_event_persist_failsafe():
    """PG 落库抛异常时，Redis 广播仍已执行，异常被吞（Fail-Safe）。"""
    redis = MagicMock()
    redis.publish = AsyncMock()
    emitter = EventEmitter(redis)

    async def boom(*args, **kwargs):
        raise RuntimeError("PG down")

    with patch.object(emitter, "_persist", new=boom):
        # 不应抛出：_persist 的异常在 emit_event 内部被 Fail-Safe 处理
        await emitter.emit_event("aaaaaaaa-0000-0000-0000-0000000000dd", _init_event())

    redis.publish.assert_awaited_once()
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k emit -v
```

期望：`ModuleNotFoundError: No module named 'app.orchestrator.event_emitter'`

- [ ] **Step 3: 实现 event_emitter.py**

新建 `backend/app/orchestrator/event_emitter.py`：

```python
"""M6 双写网关：Redis 实时广播 +（低频阶段事件）PG 短事务落库。

- emit_event：低频协议阶段事件，先广播再 await 短事务落库。
- emit_token：高频 token 流，仅广播不落库（避免高频 I/O 压垮 PG）。
落库 Fail-Safe：PG 挂了记 CRITICAL 日志，绝不阻断调度与广播。
"""
from __future__ import annotations

import json
import uuid

import redis.asyncio as redis

from app.common.logger import log
from app.db.session import AsyncSessionLocal
from app.models.event import ExecutionEvent
from app.protocol import ProtocolEvent, to_payload
from app.state_manager.keys import get_channel_events


class EventEmitter:
    """双写网关。Coordinator/Scheduler/BaseAgent 通过它发布协议事件与 token。"""

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def emit_event(self, execution_id: str, event: ProtocolEvent) -> None:
        """低频阶段协议事件：先广播（实时优先），再 await 短事务落库。"""
        data = to_payload(event)
        channel = get_channel_events(execution_id)
        await self._redis.publish(channel, json.dumps(data))
        try:
            await self._persist(execution_id, event, data)
        except Exception as exc:  # Fail-Safe：落库失败不阻断调度
            log.critical("[M6 EventEmitter] 事件持久化失败: %s", exc)

    async def emit_token(
        self,
        execution_id: str,
        agent_id: str,
        text: str,
        reasoning: bool = False,
    ) -> None:
        """高频 token 流：仅 Redis 广播，不落库。"""
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
        """短事务落库到 execution_events。列仅填 protocol_stage/event_type/payload。"""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(
                    ExecutionEvent(
                        execution_id=uuid.UUID(execution_id),
                        protocol_stage=event.protocol_stage.value,
                        event_type=event.event_type.value,
                        payload=data,
                    )
                )
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k emit -v
```

期望：`3 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/orchestrator/event_emitter.py backend/tests/unit/test_orchestrator.py
git commit -m "feat: 新增 M6 EventEmitter 双写网关（Redis 广播 + PG 短事务落库 Fail-Safe）"
```

---

## Task 3: BaseAgent 单 Agent 执行

**Files:**
- Create: `backend/app/orchestrator/base_agent.py`
- Test: `backend/tests/unit/test_orchestrator.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `test_orchestrator.py` 末尾追加：

```python
from app.orchestrator.base_agent import BaseAgent
from app.services.llm_schemas import LLMStreamChunk, UsageStats


def _fake_stream(chunks):
    """构造一个异步生成器，模拟 LLMService.stream_completion。"""
    async def _gen(*args, **kwargs):
        for c in chunks:
            yield c
    return _gen


async def test_base_agent_accumulates_tokens_and_usage():
    """token 累积成 agent_message，尾帧 usage 组装 ExecutePayload。"""
    chunks = [
        LLMStreamChunk(token="Hello"),
        LLMStreamChunk(token=" world"),
        LLMStreamChunk(usage=UsageStats(
            prompt_tokens=10, completion_tokens=5,
            total_tokens=15, model_cost_usd=0.0001,
        )),
    ]
    llm = MagicMock()
    llm.stream_completion = _fake_stream(chunks)
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()

    agent = BaseAgent(
        agent_id="agent-1", llm_model="gpt-4o", system_prompt="you are helpful",
        llm_service=llm, emitter=emitter,
    )
    payload = await agent.run("exec-1", {"query": "hi"})

    assert payload.agent_message == "Hello world"
    assert payload.prompt_tokens == 10
    assert payload.completion_tokens == 5
    assert payload.model == "gpt-4o"          # 来自 Agent.llm_model
    assert payload.model_cost_usd == 0.0001


async def test_base_agent_emits_token_stream():
    """每个 token 触发一次 emit_token（高频广播）。"""
    chunks = [LLMStreamChunk(token="a"), LLMStreamChunk(token="b")]
    llm = MagicMock()
    llm.stream_completion = _fake_stream(chunks)
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()

    agent = BaseAgent(
        agent_id="agent-1", llm_model="gpt-4o", system_prompt=None,
        llm_service=llm, emitter=emitter,
    )
    await agent.run("exec-1", {"query": "hi"})

    assert emitter.emit_token.await_count == 2
    assert emitter.emit_token.await_args_list[0].args[2] == "a"


async def test_base_agent_no_usage_tail_fallback():
    """厂商未回 usage 尾帧时，用量填 0 兜底。"""
    chunks = [LLMStreamChunk(token="only text")]
    llm = MagicMock()
    llm.stream_completion = _fake_stream(chunks)
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()

    agent = BaseAgent(
        agent_id="agent-1", llm_model="qwen-max", system_prompt=None,
        llm_service=llm, emitter=emitter,
    )
    payload = await agent.run("exec-1", {"query": "hi"})

    assert payload.agent_message == "only text"
    assert payload.prompt_tokens == 0
    assert payload.completion_tokens == 0
    assert payload.model == "qwen-max"
    assert payload.model_cost_usd == 0.0


async def test_base_agent_emits_reasoning_content():
    """reasoning_content 也触发 emit_token（reasoning=True），但不进 agent_message。"""
    chunks = [
        LLMStreamChunk(reasoning_content="thinking..."),
        LLMStreamChunk(token="answer"),
    ]
    llm = MagicMock()
    llm.stream_completion = _fake_stream(chunks)
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()

    agent = BaseAgent(
        agent_id="agent-1", llm_model="deepseek-r1", system_prompt=None,
        llm_service=llm, emitter=emitter,
    )
    payload = await agent.run("exec-1", {"query": "hi"})

    assert payload.agent_message == "answer"      # reasoning 不计入正文
    assert emitter.emit_token.await_count == 2
    assert emitter.emit_token.await_args_list[0].kwargs.get("reasoning") is True
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k base_agent -v
```

期望：`ModuleNotFoundError: No module named 'app.orchestrator.base_agent'`

- [ ] **Step 3: 实现 base_agent.py**

新建 `backend/app/orchestrator/base_agent.py`：

```python
"""单个 Agent 的一次 EXECUTE。内聚 token 拼接、思维链广播、用量结算。"""
from __future__ import annotations

from app.orchestrator.event_emitter import EventEmitter
from app.protocol import ExecutePayload
from app.services.llm_service import LLMService


class BaseAgent:
    """DB-pure：只依赖 LLMService 与 EventEmitter，不感知数据库。"""

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
        """执行一次 LLM 补全，原地流式广播 token，返回 ExecutePayload。"""
        messages = self._build_messages(task_input)
        buffer: list[str] = []
        usage = None

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
                    execution_id,
                    self._agent_id,
                    chunk.reasoning_content,
                    reasoning=True,
                )
            if chunk.usage is not None:
                usage = chunk.usage

        return ExecutePayload(
            agent_message="".join(buffer),
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=self._llm_model,
            model_cost_usd=usage.model_cost_usd if usage else 0.0,
        )

    def _build_messages(self, task_input: dict) -> list[dict[str, str]]:
        """组装 OpenAI 格式消息列表。system_prompt 可选，task_input.query 为用户输入。"""
        messages: list[dict[str, str]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        query = task_input.get("query", "")
        messages.append({"role": "user", "content": str(query)})
        return messages
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k base_agent -v
```

期望：`4 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/orchestrator/base_agent.py backend/tests/unit/test_orchestrator.py
git commit -m "feat: 新增 M6 BaseAgent 流式执行与 ExecutePayload 用量结算"
```

---

## Task 4: Scheduler — Agent 工厂 + 上下文加载 + 执行结算

Coordinator 必须保持 DB-pure，但它需要 `workflow.topology` / `execution.input` / `workflow_id`。这些 PG 读全部收进 Scheduler 的 `load_execution_context()`，符合「仅 scheduler/emitter 碰 DB」的约束。

**Files:**
- Create: `backend/app/orchestrator/scheduler.py`
- Test: `backend/tests/unit/test_orchestrator.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `test_orchestrator.py` 末尾追加：

```python
import uuid as _uuid
from contextlib import asynccontextmanager

from app.orchestrator.scheduler import ExecutionContext, Scheduler


def _make_session_cm(get_return=None, begin_ok=True):
    """构造一个可作为 async context manager 的 mock session。

    支持 `async with AsyncSessionLocal() as session:` 与嵌套
    `async with session.begin():` 两种用法。
    """
    session = MagicMock()
    session.get = AsyncMock(return_value=get_return)

    @asynccontextmanager
    async def _begin():
        yield

    session.begin = _begin

    @asynccontextmanager
    async def _session_cm():
        yield session

    return _session_cm, session


async def test_scheduler_load_agent_builds_base_agent():
    """load_agent 查库命中 → new 出 BaseAgent，llm_model 透传。"""
    agent_row = MagicMock(llm_model="gpt-4o", system_prompt="sys")
    session_cm, _ = _make_session_cm(get_return=agent_row)

    llm = MagicMock()
    emitter = MagicMock()
    sched = Scheduler(llm, emitter)

    aid = str(_uuid.uuid4())
    with patch("app.orchestrator.scheduler.AsyncSessionLocal", session_cm):
        agent = await sched.load_agent(aid)

    assert agent._llm_model == "gpt-4o"
    assert agent._agent_id == aid


async def test_scheduler_load_agent_missing_fails_fast():
    """查无 Agent → 抛 OrchestratorError（快速失败）。"""
    session_cm, _ = _make_session_cm(get_return=None)
    sched = Scheduler(MagicMock(), MagicMock())

    with patch("app.orchestrator.scheduler.AsyncSessionLocal", session_cm):
        with pytest.raises(OrchestratorError, match="Agent 不存在"):
            await sched.load_agent(str(_uuid.uuid4()))


async def test_scheduler_load_agent_invalid_uuid_fails_fast():
    """agent_id 非法 UUID → 抛 OrchestratorError。"""
    sched = Scheduler(MagicMock(), MagicMock())
    with pytest.raises(OrchestratorError, match="非法"):
        await sched.load_agent("not-a-uuid")


async def test_scheduler_load_execution_context():
    """加载 execution.input + workflow.topology + workflow_id。"""
    wf_id = _uuid.uuid4()
    exec_row = MagicMock(workflow_id=wf_id, input={"query": "hi"})
    wf_row = MagicMock(topology={"nodes": [], "edges": []})

    session = MagicMock()
    session.get = AsyncMock(side_effect=[exec_row, wf_row])

    @asynccontextmanager
    async def _session_cm():
        yield session

    sched = Scheduler(MagicMock(), MagicMock())
    with patch("app.orchestrator.scheduler.AsyncSessionLocal", _session_cm):
        ctx = await sched.load_execution_context(str(_uuid.uuid4()))

    assert isinstance(ctx, ExecutionContext)
    assert ctx.workflow_id == str(wf_id)
    assert ctx.task_input == {"query": "hi"}
    assert ctx.topology == {"nodes": [], "edges": []}


async def test_scheduler_load_execution_context_missing_execution():
    """execution 不存在 → OrchestratorError。"""
    session_cm, _ = _make_session_cm(get_return=None)
    sched = Scheduler(MagicMock(), MagicMock())
    with patch("app.orchestrator.scheduler.AsyncSessionLocal", session_cm):
        with pytest.raises(OrchestratorError, match="执行实例不存在"):
            await sched.load_execution_context(str(_uuid.uuid4()))


async def test_scheduler_settle_execution_updates_status():
    """settle_execution 更新 status/output/error。"""
    exec_row = MagicMock()
    session_cm, _ = _make_session_cm(get_return=exec_row)
    sched = Scheduler(MagicMock(), MagicMock())

    with patch("app.orchestrator.scheduler.AsyncSessionLocal", session_cm):
        await sched.settle_execution(
            str(_uuid.uuid4()), status="completed", output={"message": "done"}
        )

    assert exec_row.status == "completed"
    assert exec_row.output == {"message": "done"}
    assert exec_row.error is None
```

> 测试顶部若尚未 `import pytest`，在文件已有 import 区补一行 `import pytest`（Task 1 已 import 了 router；此处确保 pytest 可用）。

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k scheduler -v
```

期望：`ModuleNotFoundError: No module named 'app.orchestrator.scheduler'`

- [ ] **Step 3: 实现 scheduler.py**

新建 `backend/app/orchestrator/scheduler.py`：

```python
"""Agent 实例化工厂 + 执行上下文加载 + workflow_executions 结算落库。

M6 中允许依赖 db/models 的两个文件之一（另一个是 event_emitter.py）。
所有 PG 访问用短事务 async with AsyncSessionLocal()，与后台协程生命周期对齐。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.orchestrator.base_agent import BaseAgent
from app.orchestrator.event_emitter import EventEmitter
from app.orchestrator.exceptions import OrchestratorError
from app.services.llm_service import LLMService


@dataclass
class ExecutionContext:
    """一次执行的静态上下文，从 PG 加载一次后驱动整个循环。"""

    workflow_id: str
    topology: dict
    task_input: dict


class Scheduler:
    """Agent 工厂 + 上下文加载 + 结算。"""

    def __init__(self, llm_service: LLMService, emitter: EventEmitter) -> None:
        self._llm = llm_service
        self._emitter = emitter

    async def load_execution_context(self, execution_id: str) -> ExecutionContext:
        """短事务加载 execution.input + 关联 workflow.topology + workflow_id。"""
        exec_uuid = self._to_uuid(execution_id, "execution_id")
        async with AsyncSessionLocal() as session:
            exec_row = await session.get(WorkflowExecution, exec_uuid)
            if exec_row is None:
                raise OrchestratorError(f"执行实例不存在: {execution_id}")
            topology: dict = {}
            if exec_row.workflow_id is not None:
                wf_row = await session.get(Workflow, exec_row.workflow_id)
                if wf_row is not None:
                    topology = wf_row.topology or {}
            return ExecutionContext(
                workflow_id=str(exec_row.workflow_id),
                topology=topology,
                task_input=exec_row.input or {},
            )

    async def load_agent(self, agent_id: str) -> BaseAgent:
        """短事务查 PG 加载 Agent 配置，工厂化 new 出 BaseAgent。"""
        agent_uuid = self._to_uuid(agent_id, "agent_id")
        async with AsyncSessionLocal() as session:
            row = await session.get(Agent, agent_uuid)
        if row is None:
            raise OrchestratorError(f"Agent 不存在: {agent_id}")
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
        """短事务更新 workflow_executions 最终状态。"""
        exec_uuid = self._to_uuid(execution_id, "execution_id")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                exec_row = await session.get(WorkflowExecution, exec_uuid)
                if exec_row is not None:
                    exec_row.status = status
                    exec_row.output = output
                    exec_row.error = error

    @staticmethod
    def _to_uuid(value: str, field: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise OrchestratorError(f"{field} 非法 UUID: {value}") from exc
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k scheduler -v
```

期望：`6 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/orchestrator/scheduler.py backend/tests/unit/test_orchestrator.py
git commit -m "feat: 新增 M6 Scheduler（Agent 工厂 + 执行上下文加载 + 结算，短事务）"
```

---

## Task 5: Coordinator — 五阶段主循环 + 失败收口

**Files:**
- Create: `backend/app/orchestrator/coordinator.py`
- Test: `backend/tests/unit/test_orchestrator.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `test_orchestrator.py` 末尾追加：

```python
from app.orchestrator.coordinator import Coordinator
from app.orchestrator.scheduler import ExecutionContext
from app.services.llm_exceptions import LLMServiceError


def _stage_sequence(emitter_mock):
    """从 emit_event 的调用记录里提取 protocol_stage 值序列。"""
    return [
        call.args[1].protocol_stage.value
        for call in emitter_mock.emit_event.await_args_list
    ]


def _build_coordinator(topology, exec_payload=None, run_exc=None):
    """构造一个所有依赖都被 mock 的 Coordinator。"""
    coord = Coordinator.__new__(Coordinator)  # 跳过 __init__ 真实依赖构造

    coord._emitter = MagicMock()
    coord._emitter.emit_event = AsyncMock()
    coord._task_state = MagicMock()
    coord._task_state.create = AsyncMock()
    coord._task_state.transition = AsyncMock()
    coord._router = AgentRouter()  # 用真实 router，验证真实流转

    coord._scheduler = MagicMock()
    coord._scheduler.load_execution_context = AsyncMock(
        return_value=ExecutionContext(
            workflow_id="wf-1", topology=topology, task_input={"query": "hi"}
        )
    )
    coord._scheduler.settle_execution = AsyncMock()

    fake_agent = MagicMock()
    if run_exc is not None:
        fake_agent.run = AsyncMock(side_effect=run_exc)
    else:
        fake_agent.run = AsyncMock(
            return_value=exec_payload
            or ExecutePayload(
                agent_message="done", prompt_tokens=1, completion_tokens=1,
                model="gpt-4o", model_cost_usd=0.0,
            )
        )
    coord._scheduler.load_agent = AsyncMock(return_value=fake_agent)
    return coord


async def test_coordinator_single_agent_flow():
    """单节点：INIT→RECEIVE→ROUTE→EXECUTE→ROUTE(None)→FINISH。"""
    topo = {
        "nodes": [{"id": "solo", "type": "agent", "data": {"agent_id": str(_uuid.uuid4())}}],
        "edges": [],
    }
    coord = _build_coordinator(topo)
    await coord._execute_workflow_loop("aaaaaaaa-0000-0000-0000-000000000010")

    assert _stage_sequence(coord._emitter) == [
        "INIT", "RECEIVE", "ROUTE", "EXECUTE", "ROUTE", "FINISH",
    ]
    # 收口为成功
    final = coord._emitter.emit_event.await_args_list[-1].args[1]
    assert final.payload.success is True
    coord._scheduler.settle_execution.assert_awaited_once()
    assert coord._scheduler.settle_execution.await_args.kwargs["status"] == "completed"


async def test_coordinator_double_agent_flow():
    """双节点 node-1→node-2：两跳 EXECUTE。"""
    coord = _build_coordinator(_topology_double())
    await coord._execute_workflow_loop("aaaaaaaa-0000-0000-0000-000000000011")

    assert _stage_sequence(coord._emitter) == [
        "INIT", "RECEIVE", "ROUTE", "EXECUTE", "ROUTE", "EXECUTE", "ROUTE", "FINISH",
    ]
    assert coord._scheduler.load_agent.await_count == 2


async def test_coordinator_llm_error_settles_failed():
    """BaseAgent.run 抛 LLMServiceError → FINISH(success=False) + settle failed。"""
    topo = {
        "nodes": [{"id": "solo", "type": "agent", "data": {"agent_id": str(_uuid.uuid4())}}],
        "edges": [],
    }
    coord = _build_coordinator(topo, run_exc=LLMServiceError("boom"))
    await coord._execute_workflow_loop("aaaaaaaa-0000-0000-0000-000000000012")

    final = coord._emitter.emit_event.await_args_list[-1].args[1]
    assert final.protocol_stage.value == "FINISH"
    assert final.payload.success is False
    assert "boom" in final.payload.output["error"]
    assert coord._scheduler.settle_execution.await_args.kwargs["status"] == "failed"


async def test_coordinator_unknown_agent_fails_fast():
    """Scheduler.load_agent 抛 OrchestratorError → 快速失败收口。"""
    coord = _build_coordinator(_topology_double())
    coord._scheduler.load_agent = AsyncMock(
        side_effect=OrchestratorError("Agent 不存在: x")
    )
    await coord._execute_workflow_loop("aaaaaaaa-0000-0000-0000-000000000013")

    final = coord._emitter.emit_event.await_args_list[-1].args[1]
    assert final.protocol_stage.value == "FINISH"
    assert final.payload.success is False
    assert coord._scheduler.settle_execution.await_args.kwargs["status"] == "failed"


async def test_start_execution_schedules_background_task():
    """start_execution 通过 create_task 触发，不阻塞返回。"""
    import asyncio

    coord = _build_coordinator(_topology_double())
    coord._execute_workflow_loop = AsyncMock()

    await coord.start_execution("aaaaaaaa-0000-0000-0000-000000000014")
    # 让事件循环调度后台任务
    await asyncio.sleep(0)
    coord._execute_workflow_loop.assert_awaited_once_with(
        "aaaaaaaa-0000-0000-0000-000000000014"
    )
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k coordinator -v
```

期望：`ModuleNotFoundError: No module named 'app.orchestrator.coordinator'`

- [ ] **Step 3: 实现 coordinator.py**

新建 `backend/app/orchestrator/coordinator.py`：

```python
"""M6 编排引擎门面 + 五阶段协议主循环。

DB-pure：不 import db/models。所有 PG 访问委托给 Scheduler。
对 M7 暴露唯一入口 start_execution()，内部 create_task 后台异步流转。
"""
from __future__ import annotations

import asyncio

import redis.asyncio as redis

from app.common.logger import log
from app.orchestrator.event_emitter import EventEmitter
from app.orchestrator.router import AgentRouter
from app.orchestrator.scheduler import Scheduler
from app.protocol import (
    EventType,
    ExecutePayload,
    FinishPayload,
    InitPayload,
    ProtocolEvent,
    ProtocolStage,
    ReceivePayload,
    RoutePayload,
)
from app.services.llm_service import LLMService
from app.state_manager.task_state import TaskStateManager


class Coordinator:
    """编排引擎门面。构造时自建 EventEmitter/TaskStateManager/Router/Scheduler。"""

    def __init__(self, redis_client: redis.Redis, llm_service: LLMService) -> None:
        self._emitter = EventEmitter(redis_client)
        self._task_state = TaskStateManager(redis_client)
        self._router = AgentRouter()
        self._scheduler = Scheduler(llm_service, self._emitter)

    async def start_execution(self, execution_id: str) -> None:
        """唯一对外总入口（M7 调用）。触发后立即返回，不阻塞 HTTP 响应。"""
        log.info("[M6 Coordinator] 收到工作流触发, execution_id=%s", execution_id)
        asyncio.create_task(self._execute_workflow_loop(execution_id))

    async def _execute_workflow_loop(self, execution_id: str) -> None:
        """五阶段协议状态机主循环。任何异常统一收口为 FINISH(success=False)。"""
        last_message = ""
        try:
            ctx = await self._scheduler.load_execution_context(execution_id)

            # 1. INIT
            await self._task_state.create(execution_id, "INIT")
            await self._emit(
                execution_id, ProtocolStage.INIT, EventType.AGENT_SPAWN,
                InitPayload(agent_id="orchestrator", workflow_id=ctx.workflow_id),
            )

            # 2. RECEIVE
            await self._task_state.transition(execution_id, "RECEIVE", "running")
            await self._emit(
                execution_id, ProtocolStage.RECEIVE, EventType.AGENT_CALL,
                ReceivePayload(task_input=ctx.task_input),
            )

            # 3. 路由循环
            current_node: str | None = None
            while True:
                decision = self._router.route_next(current_node, ctx.topology)
                await self._task_state.transition(
                    execution_id, "ROUTE", "running",
                    agent_id=decision.next_agent_id,
                )
                await self._emit(
                    execution_id, ProtocolStage.ROUTE, EventType.AGENT_CALL,
                    RoutePayload(
                        next_agent_id=decision.next_agent_id,
                        routing_reason=decision.reason,
                    ),
                )
                if decision.next_node_id is None:
                    break

                agent = await self._scheduler.load_agent(decision.next_agent_id)
                await self._task_state.transition(
                    execution_id, "EXECUTE", "running",
                    agent_id=decision.next_agent_id,
                )
                payload: ExecutePayload = await agent.run(
                    execution_id, ctx.task_input
                )
                last_message = payload.agent_message
                await self._emit(
                    execution_id, ProtocolStage.EXECUTE,
                    EventType.AGENT_FINISH, payload,
                )
                current_node = decision.next_node_id

            # 4. FINISH（成功）
            output = {"message": last_message}
            await self._task_state.transition(execution_id, "FINISH", "completed")
            await self._emit(
                execution_id, ProtocolStage.FINISH, EventType.AGENT_FINISH,
                FinishPayload(success=True, output=output),
            )
            await self._scheduler.settle_execution(
                execution_id, status="completed", output=output
            )

        except Exception as exc:  # 顶层兜底收口
            error_msg = str(exc)
            log.error(
                "[M6 Coordinator] execution_id=%s 失败结算: %s",
                execution_id, error_msg,
            )
            await self._emit(
                execution_id, ProtocolStage.FINISH, EventType.AGENT_FINISH,
                FinishPayload(success=False, output={"error": error_msg}),
            )
            await self._scheduler.settle_execution(
                execution_id, status="failed", error=error_msg
            )

    async def _emit(self, execution_id, stage, event_type, payload) -> None:
        """封包成 ProtocolEvent 并交 EventEmitter 双写。"""
        await self._emitter.emit_event(
            execution_id,
            ProtocolEvent(
                protocol_stage=stage, event_type=event_type, payload=payload
            ),
        )
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -k coordinator -v
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py::test_start_execution_schedules_background_task -v
```

期望：`5 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/orchestrator/coordinator.py backend/tests/unit/test_orchestrator.py
git commit -m "feat: 新增 M6 Coordinator 五阶段主循环与顶层失败收口"
```

---

## Task 6: 公共 API 导出 + 全套单测通过 + Ruff

**Files:**
- Modify: `backend/app/orchestrator/__init__.py`

- [ ] **Step 1: 更新 `__init__.py` 导出公共 API**

将 `backend/app/orchestrator/__init__.py` 内容替换为：

```python
"""M6 Orchestrator 公共 API。

外部模块（M7）应从此处导入，而非直接引用子模块：
    from app.orchestrator import Coordinator
"""
from app.orchestrator.coordinator import Coordinator

__all__ = ["Coordinator"]
```

- [ ] **Step 2: 跑全套单测**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_orchestrator.py -v
```

期望：全部测试通过（Router 4 + EventEmitter 3 + BaseAgent 4 + Scheduler 6 + Coordinator 5 = **22 passed**）

- [ ] **Step 3: 验证公共 API 可导入**

```bash
cd backend && .venv/Scripts/python.exe -c "from app.orchestrator import Coordinator; print('OK')"
```

期望：输出 `OK`，无报错

- [ ] **Step 4: 跑 Ruff 代码检查**

```bash
cd backend && .venv/Scripts/python.exe -m ruff check app/orchestrator tests/unit/test_orchestrator.py
```

期望：无输出（0 errors, 0 warnings）

- [ ] **Step 5: 提交**

```bash
git add backend/app/orchestrator/__init__.py
git commit -m "feat: 导出 M6 Coordinator 公共 API，全套 22 条单测通过"
```

---

## Task 7: 集成 Smoke Test（DoD 加分项，验证拼接契约）

此任务为 **DoD 加分项**：环境（真实 Redis DB 1 + 测试 PG）就绪时验证三个跨模块拼接契约（§10.3）。若环境未就绪可跳过。

**Files:**
- Create: `backend/tests/integration/test_orchestrator_smoke.py`

- [ ] **Step 1: 写集成测试**

新建 `backend/tests/integration/test_orchestrator_smoke.py`：

```python
"""M6 Orchestrator 集成 smoke test（真实 Redis+PG，mock M5）。

验证三个拼接契约：
1. EventEmitter → PG：to_payload() 铺平的 dict 能否写进 ExecutionEvent.payload JSONB
2. BaseAgent → M5：消费真实结构的 LLMStreamChunk 流
3. 后台协程 session 生命周期：AsyncSessionLocal 在 create_task 协程里能否正常开关

环境要求：
- Redis running on localhost:6379 DB 1
- PostgreSQL 测试库（已迁移）
"""
import uuid

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.event import ExecutionEvent
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.orchestrator import Coordinator
from app.services.llm_schemas import LLMStreamChunk, UsageStats
from app.services.llm_service import LLMService


@pytest.fixture
async def redis_client():
    """真实 Redis DB 1（与开发 DB 0 隔离）。"""
    client = aioredis.from_url(
        "redis://localhost:6379/1", encoding="utf-8", decode_responses=True
    )
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def db_session():
    """真实 PG 测试库，测试后清理相关表。"""
    async with AsyncSessionLocal() as session:
        yield session
        # 清理测试数据
        await session.execute(
            ExecutionEvent.__table__.delete().where(
                ExecutionEvent.execution_id.like("ffffffff-%")
            )
        )
        await session.execute(
            WorkflowExecution.__table__.delete().where(
                WorkflowExecution.id.like("ffffffff-%")
            )
        )
        await session.execute(
            Workflow.__table__.delete().where(Workflow.id.like("ffffffff-%"))
        )
        await session.execute(
            Agent.__table__.delete().where(Agent.id.like("ffffffff-%"))
        )
        await session.commit()


def _fake_llm_stream(*args, **kwargs):
    """Mock M5 流式补全。"""

    async def _gen():
        yield LLMStreamChunk(token="Hello")
        yield LLMStreamChunk(token=" world")
        yield LLMStreamChunk(
            usage=UsageStats(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                model_cost_usd=0.0001,
            )
        )

    return _gen()


async def test_orchestrator_smoke_single_agent(redis_client, db_session):
    """单 Agent 拓扑：跑完整五阶段，验证事件落库 + workflow_executions 结算 + Redis 广播。"""
    # 准备测试数据
    wf_id = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
    agent_id = uuid.UUID("ffffffff-0000-0000-0000-000000000002")
    exec_id = uuid.UUID("ffffffff-0000-0000-0000-000000000003")

    workflow = Workflow(
        id=wf_id,
        name="test-wf",
        topology={
            "nodes": [
                {
                    "id": "node-1",
                    "type": "agent",
                    "data": {"agent_id": str(agent_id)},
                }
            ],
            "edges": [],
        },
    )
    agent = Agent(
        id=agent_id,
        name="test-agent",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
        system_prompt="you are helpful",
    )
    execution = WorkflowExecution(
        id=exec_id,
        workflow_id=wf_id,
        status="pending",
        input={"query": "hi"},
    )
    db_session.add_all([workflow, agent, execution])
    await db_session.commit()

    # Mock LLMService
    llm = LLMService.__new__(LLMService)
    llm.stream_completion = _fake_llm_stream

    # 执行
    coord = Coordinator(redis_client, llm)
    await coord._execute_workflow_loop(str(exec_id))

    # 验证契约 1：execution_events 表真的落了事件
    result = await db_session.execute(
        select(ExecutionEvent).where(ExecutionEvent.execution_id == exec_id)
    )
    events = result.scalars().all()
    assert len(events) == 6  # INIT, RECEIVE, ROUTE, EXECUTE, ROUTE(None), FINISH
    stages = [e.protocol_stage for e in events]
    assert stages == ["INIT", "RECEIVE", "ROUTE", "EXECUTE", "ROUTE", "FINISH"]

    # 验证契约 3：workflow_executions.status 真的变 completed
    await db_session.refresh(execution)
    assert execution.status == "completed"
    assert execution.output is not None
    assert "Hello world" in execution.output.get("message", "")

    # 验证契约 1（Redis）：channel_events 真的收到帧
    # （因为已执行完，无法直接订阅验证；此处确认 Redis publish 正常不抛异常即可）
```

> 若测试 PG 连接未配置或 Redis 未启动，此测试会失败。按 DoD 定义，环境就绪则通过，否则跳过不阻塞。

- [ ] **Step 2: 跑集成测试（环境就绪时）**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_orchestrator_smoke.py -v
```

期望（环境就绪）：`1 passed`

期望（环境未就绪）：跳过或标注为「环境依赖未满足」

- [ ] **Step 3: 提交**

```bash
git add backend/tests/integration/test_orchestrator_smoke.py
git commit -m "test: 新增 M6 集成 smoke test，验证 EventEmitter/BaseAgent/session 三个跨模块拼接契约"
```

---

## 验收检查（DoD）

所有 Task 完成后，逐项确认：

- [ ] 双 Agent 端到端：Task 5 的 `test_coordinator_double_agent_flow` 验证了双 Agent topology 完整五阶段（mock LLM）
- [ ] 事件顺序正确：Task 5 的 `_stage_sequence` 辅助函数验证事件序列严格为 `INIT→RECEIVE→(ROUTE→EXECUTE)*→FINISH`
- [ ] 失败收口：Task 5 的 `test_coordinator_llm_error_settles_failed` / `test_coordinator_unknown_agent_fails_fast` 验证任意异常 → FINISH(success=False)
- [ ] Token 流广播：Task 3 的 `test_base_agent_emits_token_stream` 验证 EXECUTE 阶段 token 高频广播，Task 2 的 `test_emit_token_publishes_only_no_persist` 验证不落库
- [ ] 双写一致：Task 2 的 `test_emit_event_publishes_and_persists` 验证阶段事件同时写 PG + Redis
- [ ] ORM 对齐：Task 2 的 EventEmitter 实现仅填 `protocol_stage`/`event_type`/`payload`（由 `to_payload()` 铺平），与 [event.py](../../../backend/app/models/event.py) 真实列一致
- [ ] 依赖纯净：仅 `event_emitter.py`/`scheduler.py` 依赖 db/models；coordinator/router/base_agent 无 DB 感知（代码审查确认）
- [ ] 单测全绿：Task 6 验证 22 条单测全通过
- [ ] 集成 smoke（加分项）：Task 7 环境就绪时通过，验证 §10.3 三个拼接契约
- [ ] Ruff 通过：Task 6 Step 4 验证无 lint 错误
- [ ] 公共 API 导出：Task 6 Step 3 验证 `from app.orchestrator import Coordinator` 可正常导入

全部 ✅ 后，M6 Orchestrator 核心交付完成。

---

## 前置依赖提示

开工前确认这些模块已就绪：

- ✅ M1 数据模型（Agent / Workflow / WorkflowExecution / ExecutionEvent）
- ✅ M2 五阶段协议（ProtocolEvent / to_payload / 各 Payload）
- ✅ M3 状态管理（TaskStateManager / keys.get_channel_events）
- ✅ M5 LLM 服务（LLMService / LLMStreamChunk / UsageStats / LLMServiceError）
- ✅ Redis 与 PG 在开发环境可连接（集成 smoke test 需要）

M6 完成后，M7 业务服务层可注入 Coordinator 并调用 `start_execution()`，M4 WebSocket 可订阅 `channel_events` 推送前端。







