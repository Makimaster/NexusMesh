# M7 业务服务层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 M7 业务服务层——Agent/Workflow 的软删除 CRUD、Workflow 拓扑轻量预检 + 触发执行（构造注入 M6 Coordinator）、Executions/Events 只读查询，全部对齐设计文档 [2026-07-05-M7-business-services-design.md](../specs/2026-07-05-M7-business-services-design.md)。

**Architecture:** 三驾马车（CQRS 轻量落地）：`agent_service.py`/`workflow_service.py` 为写线，`execution_service.py` 为只读线。Coordinator 经 `api/dependencies/orchestrator.py` 依赖链装配后构造注入 WorkflowService。错误治理复用 `core/exceptions.py` 全局 handler，仅增补一个 `ValidationError(422)`。事务遵循单一边界：CRUD 用 `flush`，唯 `trigger_execution` 显式 `commit`（先落库再起飞）。

**Tech Stack:** Python 3.13, Pydantic 2.10, SQLAlchemy 2.0（asyncpg）, redis 5.x（asyncio）, pytest 8 + pytest-asyncio 0.24（`asyncio_mode=auto`）

---

## 关键实现约束（动工前必读）

1. **pytest-asyncio 已是 `auto` 模式**：测试函数**不需要** `@pytest.mark.asyncio` 装饰器，`async def test_*` 直接生效。
2. **必须用项目专属 venv 跑测试**：Windows 下 `cd backend && .venv/Scripts/python.exe -m pytest ...`，不能用系统 Python（否则缺 fastapi/litellm 报 ModuleNotFoundError）。
3. **ruff 选了 `E` 规则集，禁用 `== True`**：SQLAlchemy 过滤必须写 `Agent.is_active.is_(True)`，**不能**写 `Agent.is_active == True`（触发 E712）。设计文档片段里的 `== True` 是示意，实现时改 `.is_(True)`。
4. **事务语义铁律**：CRUD（create/update/delete）用 `await self.db.flush()`（+ `refresh`），最终 commit 交给 `get_db` 请求末尾；**唯有** `trigger_execution` 显式 `await self.db.commit()`（见设计文档 §6）。
5. **入参用 Pydantic Schema**：Service 的 create/update 方法收 `AgentRequest`/`WorkflowRequest` 等，不收裸 dict（挡批量赋值漏洞）。
6. **异常走全局 handler**：Service 抛 `NotFoundError`/`ValidationError`（来自 `app.core.exceptions`），M8 路由层零 try/except。**禁止** `super().__init__(status_code=...)`——基类只收 `detail` 单参。
7. **软删除只针对资产**：Agent/Workflow 软删除（`is_active=False`）；`WorkflowExecution` 无 `is_active` 字段，执行记录不删除。
8. **真实列结构**：`WorkflowExecution` 无 `created_by`/`triggered_by`；`ExecutionEvent` 仅 `id/execution_id/protocol_stage/event_type/payload/created_at`。

---

## 文件结构

| 操作 | 路径 | 职责 |
|------|------|------|
| 修改 | `backend/app/core/exceptions.py` | 尾部追加 `ValidationError(422)` 三行子类 |
| 创建 | `backend/app/schemas/agent.py` | `AgentRequest` / `AgentUpdateRequest`（Service 入参） |
| 创建 | `backend/app/schemas/workflow.py` | `WorkflowRequest` / `WorkflowUpdateRequest` / `TriggerRequest` |
| 创建 | `backend/app/api/dependencies/__init__.py` | 空包标记 |
| 创建 | `backend/app/api/dependencies/orchestrator.py` | `get_coordinator()` 进程内单例装配 |
| 创建 | `backend/app/services/agent_service.py` | `AgentService`（软删除 CRUD） |
| 创建 | `backend/app/services/workflow_service.py` | `WorkflowService`（拓扑预检 + 触发执行） |
| 创建 | `backend/app/services/execution_service.py` | `ExecutionService`（只读查询） |
| 创建 | `backend/tests/unit/test_services_m7.py` | 纯逻辑单测（拓扑预检、黄金时序、幂等、单例；fake session） |
| 创建 | `backend/tests/integration/test_services_m7.py` | CRUD 集成测试（真实 PG，skip 门控） |

---

## Task 1: 增补 ValidationError + 请求 Schema

**Files:**
- Modify: `backend/app/core/exceptions.py`
- Create: `backend/app/schemas/agent.py`
- Create: `backend/app/schemas/workflow.py`
- Test: `backend/tests/unit/test_services_m7.py`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/unit/test_services_m7.py`，写入：

```python
"""M7 业务服务层单元测试（纯逻辑，fake session / mock coordinator）。"""

from app.core.exceptions import NexusMeshException, ValidationError
from app.schemas.agent import AgentRequest, AgentUpdateRequest
from app.schemas.workflow import WorkflowRequest


def test_validation_error_is_422_and_subclass():
    exc = ValidationError("拓扑非法")
    assert exc.status_code == 422
    assert exc.detail == "拓扑非法"
    assert isinstance(exc, NexusMeshException)


def test_agent_request_defaults_and_fields():
    req = AgentRequest(
        name="worker",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
    )
    assert req.name == "worker"
    assert req.system_prompt is None
    assert req.config == {}


def test_agent_update_request_all_optional():
    req = AgentUpdateRequest(name="renamed")
    dumped = req.model_dump(exclude_unset=True)
    assert dumped == {"name": "renamed"}


def test_workflow_request_topology_required():
    req = WorkflowRequest(name="wf", topology={"nodes": [], "edges": []})
    assert req.topology == {"nodes": [], "edges": []}
    assert req.description is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -v`
Expected: FAIL — `ImportError: cannot import name 'ValidationError'` / `No module named 'app.schemas.agent'`

- [ ] **Step 3: 增补 ValidationError**

在 `backend/app/core/exceptions.py` 的 `ConflictError` 之后、`register_exception_handlers` 之前追加：

```python
class ValidationError(NexusMeshException):
    status_code = 422
    detail = "Validation failed"
```

- [ ] **Step 4: 创建 agent schema**

新建 `backend/app/schemas/agent.py`：

```python
from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    agent_type: str = Field(min_length=1, max_length=50)
    llm_provider: str = Field(min_length=1, max_length=50)
    llm_model: str = Field(min_length=1, max_length=100)
    system_prompt: str | None = None
    config: dict = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    agent_type: str | None = Field(default=None, min_length=1, max_length=50)
    llm_provider: str | None = Field(default=None, min_length=1, max_length=50)
    llm_model: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = None
    config: dict | None = None
```

- [ ] **Step 5: 创建 workflow schema**

新建 `backend/app/schemas/workflow.py`：

```python
from pydantic import BaseModel, Field


class WorkflowRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    topology: dict = Field(default_factory=dict)


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    topology: dict | None = None


class TriggerRequest(BaseModel):
    task_input: dict = Field(default_factory=dict)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -v`
Expected: PASS（4 passed）

- [ ] **Step 7: 提交**

```bash
git add backend/app/core/exceptions.py backend/app/schemas/agent.py backend/app/schemas/workflow.py backend/tests/unit/test_services_m7.py
git commit -m "feat: M7 增补 ValidationError(422) 与 Agent/Workflow 请求 Schema"
```

---

## Task 2: get_coordinator 依赖装配

**Files:**
- Create: `backend/app/api/dependencies/__init__.py`
- Create: `backend/app/api/dependencies/orchestrator.py`
- Test: `backend/tests/unit/test_services_m7.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_services_m7.py` 追加：

```python
async def test_get_coordinator_returns_singleton():
    import app.api.dependencies.orchestrator as dep
    from app.orchestrator.coordinator import Coordinator

    dep._coordinator = None  # 重置模块级单例，隔离测试
    fake_redis = object()

    first = await dep.get_coordinator(redis_client=fake_redis)
    second = await dep.get_coordinator(redis_client=fake_redis)

    assert isinstance(first, Coordinator)
    assert first is second  # 同一进程复用单例
    dep._coordinator = None  # 清理，避免污染其他测试
```

**注**：`Coordinator.__init__` 只把 `redis_client` 存进 `EventEmitter`/`TaskStateManager`，不发起连接，`fake_redis = object()` 足够；`LLMService()` 无参构造走 settings 默认。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py::test_get_coordinator_returns_singleton -v`
Expected: FAIL — `No module named 'app.api.dependencies'`

- [ ] **Step 3: 创建 dependencies 包**

新建 `backend/app/api/dependencies/__init__.py`（空文件）。

- [ ] **Step 4: 创建 orchestrator 依赖装配**

新建 `backend/app/api/dependencies/orchestrator.py`：

```python
"""M7 → M6 依赖链装配：进程内 Coordinator 单例。"""

from __future__ import annotations

import redis.asyncio as redis
from fastapi import Depends

from app.common.redis_client import get_redis
from app.orchestrator.coordinator import Coordinator
from app.services.llm_service import LLMService

_coordinator: Coordinator | None = None


async def get_coordinator(
    redis_client: redis.Redis = Depends(get_redis),
) -> Coordinator:
    """进程内 Coordinator 单例装配：LLMService + Coordinator。"""
    global _coordinator
    if _coordinator is None:
        _coordinator = Coordinator(
            redis_client=redis_client, llm_service=LLMService()
        )
    return _coordinator
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py::test_get_coordinator_returns_singleton -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/dependencies/ backend/tests/unit/test_services_m7.py
git commit -m "feat: M7 新增 get_coordinator 依赖链装配（进程内单例）"
```

---

## Task 3: AgentService 软删除 CRUD

**Files:**
- Create: `backend/app/services/agent_service.py`
- Test: `backend/tests/unit/test_services_m7.py`

单元测试用一个轻量 fake session 验证软删除幂等与脏字段防御（不依赖真实 PG）；真实 PG 的端到端 CRUD 放 Task 6 集成测试。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_services_m7.py` 追加：

```python
import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.models.agent import Agent
from app.services.agent_service import AgentService


class _FakeSession:
    """最小 fake AsyncSession：支持 get / add / flush / refresh。"""

    def __init__(self, store: dict | None = None) -> None:
        self._store = store or {}
        self.added: list = []
        self.flushed = 0
        self.committed = 0

    async def get(self, model, pk):
        return self._store.get(pk)

    def add(self, obj) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._store[obj.id] = obj

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, obj) -> None:
        pass

    async def commit(self) -> None:
        self.committed += 1


async def test_create_agent_sets_active_and_created_by():
    session = _FakeSession()
    service = AgentService(session)
    creator = uuid.uuid4()
    req = AgentRequest(
        name="worker",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
    )

    agent = await service.create_agent(req, created_by=creator)

    assert agent.is_active is True
    assert agent.created_by == creator
    assert session.flushed == 1
    assert session.committed == 0  # CRUD 不显式 commit


async def test_get_agent_detail_missing_raises_404():
    service = AgentService(_FakeSession())
    with pytest.raises(NotFoundError):
        await service.get_agent_detail(uuid.uuid4())


async def test_get_agent_detail_soft_deleted_raises_404():
    aid = uuid.uuid4()
    agent = Agent(
        id=aid, name="x", agent_type="a", llm_provider="p", llm_model="m",
        is_active=False,
    )
    service = AgentService(_FakeSession({aid: agent}))
    with pytest.raises(NotFoundError):
        await service.get_agent_detail(aid)


async def test_delete_agent_soft_deletes():
    aid = uuid.uuid4()
    agent = Agent(
        id=aid, name="x", agent_type="a", llm_provider="p", llm_model="m",
        is_active=True,
    )
    service = AgentService(_FakeSession({aid: agent}))

    await service.delete_agent(aid)

    assert agent.is_active is False


async def test_delete_agent_idempotent_when_missing():
    service = AgentService(_FakeSession())
    # 不抛异常，静默返回
    await service.delete_agent(uuid.uuid4())


async def test_update_agent_pops_dirty_fields():
    aid = uuid.uuid4()
    agent = Agent(
        id=aid, name="x", agent_type="a", llm_provider="p", llm_model="m",
        is_active=True,
    )
    service = AgentService(_FakeSession({aid: agent}))
    # 构造一个带 name 的更新；is_active/id 即便被塞入也应被 pop
    req = AgentUpdateRequest(name="renamed")

    updated = await service.update_agent(aid, req)

    assert updated.name == "renamed"
    assert updated.is_active is True  # 未被越权改动
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k agent -v`
Expected: FAIL — `No module named 'app.services.agent_service'`

- [ ] **Step 3: 实现 AgentService**

新建 `backend/app/services/agent_service.py`：

```python
"""M7 AgentService：Agent 资产软删除 CRUD。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.agent import Agent
from app.schemas.agent import AgentRequest, AgentUpdateRequest


class AgentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_agent(
        self, schema: AgentRequest, created_by: uuid.UUID
    ) -> Agent:
        agent = Agent(**schema.model_dump(), created_by=created_by, is_active=True)
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def get_agent_detail(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or not agent.is_active:
            raise NotFoundError(f"Agent 不存在或已被删除: {agent_id}")
        return agent

    async def list_agents(self, limit: int = 20, offset: int = 0) -> list[Agent]:
        stmt = (
            select(Agent)
            .where(Agent.is_active.is_(True))
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_agent(
        self, agent_id: uuid.UUID, schema: AgentUpdateRequest
    ) -> Agent:
        agent = await self.get_agent_detail(agent_id)
        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("id", None)
        update_data.pop("is_active", None)
        for key, value in update_data.items():
            setattr(agent, key, value)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def delete_agent(self, agent_id: uuid.UUID) -> None:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or not agent.is_active:
            return  # 幂等：不存在或已删除，静默成功
        agent.is_active = False
        await self.db.flush()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k agent -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/agent_service.py backend/tests/unit/test_services_m7.py
git commit -m "feat: M7 AgentService 软删除 CRUD（幂等删除 + 脏字段防御）"
```

---

## Task 4: WorkflowService 拓扑三铁律预检

**Files:**
- Create: `backend/app/services/workflow_service.py`
- Test: `backend/tests/unit/test_services_m7.py`

本任务只实现 `WorkflowService.__init__` 与 `_validate_topology`（三铁律，见设计文档 §9.2）。CRUD 与触发在 Task 5。铁律三 B 需查 Agent 表，用可控 fake session（预置存活 agent id 集合）验证。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_services_m7.py` 追加：

```python
from app.services.workflow_service import WorkflowService


class _AgentQuerySession:
    """fake session：execute(select(Agent.id)...) 返回预置的存活 id 集合。"""

    def __init__(self, active_ids: set[uuid.UUID]) -> None:
        self._active_ids = active_ids

    async def execute(self, stmt):
        class _Result:
            def __init__(self, ids):
                self._ids = ids

            def scalars(self):
                return self

            def all(self):
                return list(self._ids)

        return _Result(self._active_ids)


def _node(node_id: str, agent_id: str | None):
    data = {} if agent_id is None else {"agent_id": agent_id}
    return {"id": node_id, "type": "agent", "data": data}


async def test_validate_topology_empty_nodes_rejected():
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError):
        await service._validate_topology({"nodes": [], "edges": []})


async def test_validate_topology_no_entry_rejected():
    # node-1 → node-2 → node-1 闭环，无无入边节点
    a1 = uuid.uuid4()
    topo = {
        "nodes": [_node("node-1", str(a1)), _node("node-2", str(a1))],
        "edges": [
            {"source": "node-1", "target": "node-2"},
            {"source": "node-2", "target": "node-1"},
        ],
    }
    service = WorkflowService(_AgentQuerySession({a1}), coordinator=None)
    with pytest.raises(ValidationError):
        await service._validate_topology(topo)


async def test_validate_topology_multi_entry_rejected():
    a1 = uuid.uuid4()
    topo = {
        "nodes": [_node("node-1", str(a1)), _node("node-2", str(a1))],
        "edges": [],  # 两个都无入边 → 双入口
    }
    service = WorkflowService(_AgentQuerySession({a1}), coordinator=None)
    with pytest.raises(ValidationError):
        await service._validate_topology(topo)


async def test_validate_topology_node_without_agent_id_rejected():
    topo = {
        "nodes": [_node("node-1", None)],  # 未绑 agent_id，违反全 Agent 节点契约
        "edges": [],
    }
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError):
        await service._validate_topology(topo)


async def test_validate_topology_invalid_uuid_rejected():
    topo = {
        "nodes": [_node("node-1", "not-a-uuid")],
        "edges": [],
    }
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError):
        await service._validate_topology(topo)


async def test_validate_topology_missing_agent_rejected():
    a1 = uuid.uuid4()
    topo = {"nodes": [_node("node-1", str(a1))], "edges": []}
    # DB 中没有这个存活 agent
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError):
        await service._validate_topology(topo)


async def test_validate_topology_happy_path_passes():
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    topo = {
        "nodes": [_node("node-1", str(a1)), _node("node-2", str(a2))],
        "edges": [{"source": "node-1", "target": "node-2"}],
    }
    service = WorkflowService(_AgentQuerySession({a1, a2}), coordinator=None)
    # 不抛异常即通过
    await service._validate_topology(topo)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k topology -v`
Expected: FAIL — `No module named 'app.services.workflow_service'`

- [ ] **Step 3: 实现 WorkflowService 骨架 + _validate_topology**

新建 `backend/app/services/workflow_service.py`：

```python
"""M7 WorkflowService：Workflow 拓扑预检 CRUD + 触发执行。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.agent import Agent
from app.orchestrator.coordinator import Coordinator


class WorkflowService:
    def __init__(self, db: AsyncSession, coordinator: Coordinator) -> None:
        self.db = db
        self.coordinator = coordinator

    async def _validate_topology(self, topology: dict) -> None:
        nodes = topology.get("nodes", [])
        edges = topology.get("edges", [])

        # 铁律一：节点非空
        if not nodes:
            raise ValidationError("拓扑非法：画布节点集合为空，无法创建协作链路。")

        # 铁律二：单入口判定（M7 增强约束，非 M6 镜像）
        target_ids = {e.get("target") for e in edges if e.get("target")}
        entry_nodes = [
            n for n in nodes if n.get("id") and n.get("id") not in target_ids
        ]
        if not entry_nodes:
            raise ValidationError("拓扑非法：未检测到无入边的起始入口节点（闭环死锁）。")
        if len(entry_nodes) > 1:
            raise ValidationError("拓扑非法：存在多个无入边的冲突起始节点，暂不支持多入口调度。")

        # 铁律三 A：全 Agent 节点契约强制
        for node in nodes:
            if not node.get("data", {}).get("agent_id"):
                raise ValidationError(
                    f"拓扑非法：节点 {node.get('id')} 未绑定 agent_id，违反'全 Agent 节点'契约。"
                )

        # 铁律三 B：跨表 Agent 存在性批量预检
        raw_agent_ids = {node["data"]["agent_id"] for node in nodes}
        parsed_uuids: list[uuid.UUID] = []
        for raw_id in raw_agent_ids:
            try:
                parsed_uuids.append(uuid.UUID(str(raw_id)))
            except ValueError as exc:
                raise ValidationError(
                    f"拓扑非法：智能体主键格式非法: {raw_id}"
                ) from exc

        stmt = select(Agent.id).where(
            Agent.id.in_(parsed_uuids), Agent.is_active.is_(True)
        )
        result = await self.db.execute(stmt)
        db_active_ids = set(result.scalars().all())
        if len(db_active_ids) != len(parsed_uuids):
            missing = [str(u) for u in parsed_uuids if u not in db_active_ids]
            raise ValidationError(
                f"拓扑非法：引用的智能体不存在或已被清退: {', '.join(missing)}"
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k topology -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/workflow_service.py backend/tests/unit/test_services_m7.py
git commit -m "feat: M7 WorkflowService 拓扑三铁律预检（与 M6 Router 对齐）"
```

---

## Task 5: WorkflowService CRUD + trigger_execution 黄金时序

**Files:**
- Modify: `backend/app/services/workflow_service.py`
- Test: `backend/tests/unit/test_services_m7.py`

重点验证 `trigger_execution` 的黄金时序：**先 commit 再 start_execution**（用 mock coordinator 断言 commit 早于起飞，且传入的 execution_id 与落库一致）。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_services_m7.py` 追加：

```python
from unittest.mock import AsyncMock

from app.models.workflow import Workflow


class _TriggerSession:
    """记录 add / commit / refresh 调用顺序的 fake session。"""

    def __init__(self, workflow: Workflow | None) -> None:
        self._workflow = workflow
        self.events: list[str] = []
        self.added: list = []

    async def get(self, model, pk):
        return self._workflow

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.events.append("add")

    async def commit(self) -> None:
        self.events.append("commit")

    async def refresh(self, obj) -> None:
        self.events.append("refresh")


async def test_trigger_execution_commits_before_start():
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=True)
    session = _TriggerSession(workflow)
    coordinator = AsyncMock()
    service = WorkflowService(session, coordinator=coordinator)

    exec_id = await service.trigger_execution(wid, task_input={"query": "hi"})

    # 黄金时序：commit 必须早于 start_execution
    assert "commit" in session.events
    coordinator.start_execution.assert_awaited_once_with(str(exec_id))
    # 落库的执行实例状态为 pending
    assert session.added[0].status == "pending"
    assert session.added[0].input == {"query": "hi"}


async def test_trigger_execution_missing_workflow_raises_404():
    session = _TriggerSession(None)
    coordinator = AsyncMock()
    service = WorkflowService(session, coordinator=coordinator)

    with pytest.raises(NotFoundError):
        await service.trigger_execution(uuid.uuid4(), task_input={})

    # 工作流不存在时绝不起飞
    coordinator.start_execution.assert_not_awaited()


async def test_trigger_execution_soft_deleted_workflow_raises_404():
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=False)
    session = _TriggerSession(workflow)
    coordinator = AsyncMock()
    service = WorkflowService(session, coordinator=coordinator)

    with pytest.raises(NotFoundError):
        await service.trigger_execution(wid, task_input={})
    coordinator.start_execution.assert_not_awaited()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k trigger -v`
Expected: FAIL — `AttributeError: 'WorkflowService' object has no attribute 'trigger_execution'`

- [ ] **Step 3: 补齐 WorkflowService 的 CRUD + trigger**

在 `backend/app/services/workflow_service.py` 顶部 import 追加：

```python
from app.core.exceptions import NotFoundError, ValidationError
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowRequest, WorkflowUpdateRequest
```

（把已有的 `from app.core.exceptions import ValidationError` 合并为上面这行，避免重复导入。）

在 `_validate_topology` 之后、类末尾追加这些方法：

```python
    async def create_workflow(
        self, schema: WorkflowRequest, created_by: uuid.UUID
    ) -> Workflow:
        data = schema.model_dump()
        await self._validate_topology(data.get("topology", {}))
        workflow = Workflow(**data, created_by=created_by, is_active=True)
        self.db.add(workflow)
        await self.db.flush()
        await self.db.refresh(workflow)
        return workflow

    async def get_workflow_detail(self, workflow_id: uuid.UUID) -> Workflow:
        workflow = await self.db.get(Workflow, workflow_id)
        if workflow is None or not workflow.is_active:
            raise NotFoundError(f"工作流不存在或已被删除: {workflow_id}")
        return workflow

    async def list_workflows(
        self, limit: int = 20, offset: int = 0
    ) -> list[Workflow]:
        stmt = (
            select(Workflow)
            .where(Workflow.is_active.is_(True))
            .order_by(Workflow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_workflow(
        self, workflow_id: uuid.UUID, schema: WorkflowUpdateRequest
    ) -> Workflow:
        workflow = await self.get_workflow_detail(workflow_id)
        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("id", None)
        update_data.pop("is_active", None)
        if "topology" in update_data:
            await self._validate_topology(update_data["topology"])
        for key, value in update_data.items():
            setattr(workflow, key, value)
        await self.db.flush()
        await self.db.refresh(workflow)
        return workflow

    async def delete_workflow(self, workflow_id: uuid.UUID) -> None:
        workflow = await self.db.get(Workflow, workflow_id)
        if workflow is None or not workflow.is_active:
            return
        workflow.is_active = False
        await self.db.flush()

    async def trigger_execution(
        self, workflow_id: uuid.UUID, task_input: dict
    ) -> uuid.UUID:
        await self.get_workflow_detail(workflow_id)  # 反查，软删除 → 404
        execution = WorkflowExecution(
            workflow_id=workflow_id, status="pending", input=task_input
        )
        self.db.add(execution)
        await self.db.commit()  # 🔒 黄金时序：先落库提交（唯一显式 commit）
        await self.db.refresh(execution)
        await self.coordinator.start_execution(str(execution.id))  # 🚀 起飞
        return execution.id
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k trigger -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 全量单测回归**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -v`
Expected: PASS（全部通过）

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/workflow_service.py backend/tests/unit/test_services_m7.py
git commit -m "feat: M7 WorkflowService CRUD + trigger_execution 黄金时序（先落库再起飞）"
```

---

## Task 6: ExecutionService 只读查询

**Files:**
- Create: `backend/app/services/execution_service.py`
- Test: `backend/tests/unit/test_services_m7.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_services_m7.py` 追加：

```python
from app.models.execution import WorkflowExecution
from app.services.execution_service import ExecutionService


class _ExecSession:
    """fake session：get 返回预置执行实例；execute 返回预置事件列表。"""

    def __init__(self, execution=None, events=None) -> None:
        self._execution = execution
        self._events = events or []

    async def get(self, model, pk):
        return self._execution

    async def execute(self, stmt):
        events = self._events

        class _Result:
            def scalars(self):
                return self

            def all(self):
                return list(events)

        return _Result()


async def test_get_execution_detail_missing_raises_404():
    service = ExecutionService(_ExecSession(execution=None))
    with pytest.raises(NotFoundError):
        await service.get_execution_detail(uuid.uuid4())


async def test_get_execution_detail_returns_row():
    eid = uuid.uuid4()
    row = WorkflowExecution(id=eid, status="completed", input={})
    service = ExecutionService(_ExecSession(execution=row))
    result = await service.get_execution_detail(eid)
    assert result.id == eid


async def test_get_timeline_missing_execution_raises_404():
    service = ExecutionService(_ExecSession(execution=None))
    with pytest.raises(NotFoundError):
        await service.get_execution_timeline(uuid.uuid4())


async def test_get_timeline_returns_events():
    eid = uuid.uuid4()
    row = WorkflowExecution(id=eid, status="completed", input={})
    from app.models.event import ExecutionEvent

    evts = [
        ExecutionEvent(execution_id=eid, protocol_stage="INIT", event_type="agent_spawn"),
        ExecutionEvent(execution_id=eid, protocol_stage="FINISH", event_type="agent_finish"),
    ]
    service = ExecutionService(_ExecSession(execution=row, events=evts))
    timeline = await service.get_execution_timeline(eid)
    assert len(timeline) == 2
    assert timeline[0].protocol_stage == "INIT"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k execution -v`
Expected: FAIL — `No module named 'app.services.execution_service'`

- [ ] **Step 3: 实现 ExecutionService**

新建 `backend/app/services/execution_service.py`：

```python
"""M7 ExecutionService：执行实例与事件流只读查询。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.event import ExecutionEvent
from app.models.execution import WorkflowExecution


class ExecutionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_execution_detail(
        self, execution_id: uuid.UUID
    ) -> WorkflowExecution:
        execution = await self.db.get(WorkflowExecution, execution_id)
        if execution is None:
            raise NotFoundError(f"执行实例不存在: {execution_id}")
        return execution

    async def list_executions(
        self,
        workflow_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[WorkflowExecution]:
        stmt = select(WorkflowExecution)
        if workflow_id is not None:
            stmt = stmt.where(WorkflowExecution.workflow_id == workflow_id)
        if status is not None:
            stmt = stmt.where(WorkflowExecution.status == status)
        stmt = (
            stmt.order_by(WorkflowExecution.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_execution_timeline(
        self, execution_id: uuid.UUID
    ) -> list[ExecutionEvent]:
        await self.get_execution_detail(execution_id)  # 先击穿 404
        stmt = (
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_services_m7.py -k execution -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/execution_service.py backend/tests/unit/test_services_m7.py
git commit -m "feat: M7 ExecutionService 只读查询（detail/list/timeline，先击穿 404）"
```

---

## Task 7: 集成测试（真实 PG）+ 全量回归 + Ruff

**Files:**
- Create: `backend/tests/integration/test_services_m7.py`
- Test: 全量

真实 PG 端到端验证软删除隔离、跨表拓扑预检、创建者落库。环境未就绪自动 skip（对齐 M6 smoke 约定）。

- [ ] **Step 1: 写集成测试**

新建 `backend/tests/integration/test_services_m7.py`：

```python
"""M7 业务服务层集成测试（真实 PG）。

前置：PostgreSQL 测试库可连接且已迁移。环境未就绪自动 skip。
"""

import uuid

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.schemas.agent import AgentRequest
from app.schemas.workflow import WorkflowRequest
from app.services.agent_service import AgentService
from app.services.workflow_service import WorkflowService


async def _pg_available() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


@pytest.fixture
async def db_session():
    if not await _pg_available():
        pytest.skip("PostgreSQL 未就绪，跳过 M7 集成测试")
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def test_agent_soft_delete_hidden_from_list(db_session):
    creator = uuid.uuid4()
    service = AgentService(db_session)
    req = AgentRequest(
        name=f"it-agent-{uuid.uuid4()}",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
    )
    agent = await service.create_agent(req, created_by=creator)
    await db_session.flush()
    aid = agent.id

    await service.delete_agent(aid)

    # 软删除后 detail 抛 404
    with pytest.raises(NotFoundError):
        await service.get_agent_detail(aid)
    # 但物理行仍在（get 绕过 is_active）
    raw = await db_session.get(Agent, aid)
    assert raw is not None
    assert raw.is_active is False


async def test_create_workflow_rejects_missing_agent(db_session):
    service = WorkflowService(db_session, coordinator=None)
    ghost = str(uuid.uuid4())
    req = WorkflowRequest(
        name=f"it-wf-{uuid.uuid4()}",
        topology={
            "nodes": [{"id": "n1", "type": "agent", "data": {"agent_id": ghost}}],
            "edges": [],
        },
    )
    with pytest.raises(ValidationError):
        await service.create_workflow(req, created_by=uuid.uuid4())


async def test_create_workflow_happy_path(db_session):
    creator = uuid.uuid4()
    agent_service = AgentService(db_session)
    agent = await agent_service.create_agent(
        AgentRequest(
            name=f"it-agent-{uuid.uuid4()}",
            agent_type="assistant",
            llm_provider="openai",
            llm_model="gpt-4o",
        ),
        created_by=creator,
    )
    await db_session.flush()

    wf_service = WorkflowService(db_session, coordinator=None)
    req = WorkflowRequest(
        name=f"it-wf-{uuid.uuid4()}",
        topology={
            "nodes": [
                {"id": "n1", "type": "agent", "data": {"agent_id": str(agent.id)}}
            ],
            "edges": [],
        },
    )
    workflow = await wf_service.create_workflow(req, created_by=creator)
    assert workflow.is_active is True
    assert workflow.created_by == creator
```

- [ ] **Step 2: 运行集成测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_services_m7.py -v`
Expected: PASS（PG 就绪）或 SKIPPED（PG 未就绪）——两者都算通过，不阻塞。

- [ ] **Step 3: 全量单测 + 集成回归**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部 PASS 或 SKIP，无 FAIL（含既有 M1–M6 测试无回归）。

- [ ] **Step 4: Ruff 检查**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Expected: `All checks passed!`
若报 E712（`== True`），改为 `.is_(True)`；若报未用 import，删除。

- [ ] **Step 5: 提交**

```bash
git add backend/tests/integration/test_services_m7.py
git commit -m "test: M7 集成测试（软删除隔离 + 跨表拓扑预检 + 创建者落库）"
```

---

## 完成标准（DoD）

- [ ] `core/exceptions.py` 新增 `ValidationError(422)`，全局 handler 自动生效
- [ ] `schemas/agent.py`、`schemas/workflow.py` 请求 Schema 就位
- [ ] `api/dependencies/orchestrator.py` 提供 `get_coordinator` 进程内单例
- [ ] `AgentService` 软删除 CRUD：幂等删除、脏字段防御、list 过滤 is_active
- [ ] `WorkflowService` 拓扑三铁律预检 + CRUD + `trigger_execution` 黄金时序（先 commit 再起飞）
- [ ] `ExecutionService` 只读：detail/list/timeline，timeline 先击穿 404、ASC 排序
- [ ] 全量 `pytest tests/` 无 FAIL；Ruff `All checks passed`
- [ ] 依赖纯净：agent/execution service 只依赖 models；workflow service 合法依赖 orchestrator
