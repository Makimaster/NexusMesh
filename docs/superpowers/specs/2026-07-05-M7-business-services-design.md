# M7 业务服务层 — 设计文档

**版本**：1.0.0
**日期**：2026-07-05
**状态**：已确认，待实现
**上游文档**：[模块路线图](./2026-07-01-module-roadmap.md) §M7

---

## 1. 职责定位

M7 业务服务层是 NexusMesh 的**业务用例编排层（Application Service）**，位于 `api → services → models` 依赖链中段。它对上游 M8 提供 Agent/Workflow 的 CRUD 与执行生命周期支撑，对下游复用 M1 的 ORM 模型与 M6 的编排触发能力。

**职责边界**：
- ✅ Agent 资产的软删除 CRUD（`is_active` 标志位）
- ✅ Workflow 拓扑的轻量预检 CRUD + 触发执行（构造注入 M6 Coordinator）
- ✅ Executions/Events 的只读多维查询（面向 M8 列表页与 M12 Timeline）
- ❌ **不做**：HTTP 路由与 RBAC（M8）、执行状态写入（M6 独占）、实时 token 流（M4 WebSocket）、topology 图论完整性校验（环检测/可达性，YAGNI）

---

## 2. 五大架构支柱（决策锁定）

本设计经完整头脑风暴对齐，五个核心决策已锁死：

| # | 支柱 | 决策 | 一句话理由 |
|---|---|---|---|
| 1 | 删除策略 | **纯软删除（`is_active=False`），严禁物理 `DELETE`** | 死守全链路可观测性（M12 历史回溯）不丢，资产实体永久留存 |
| 2 | 触发装配 | **选项 A：`api/dependencies/` 依赖链装配 + 构造注入 Coordinator** | 依赖显式、可 mock 单测，Web 框架污染不下漏引擎层 |
| 3 | 拓扑校验 | **选项 B：轻量结构预检（非空 + 单入口 + 跨表 Agent 存在性），不做图论完整性** | 防呆前移到写入期，同时不陷入环检测/可达性的过度工程 |
| 4 | 读写分离 | **三驾马车：agent/workflow（写线）+ execution（只读线，CQRS 轻量落地）** | 定义与运行时生命周期不同，独立 service 保持高内聚 |
| 5 | 错误治理 | **复用 `core/exceptions.py` 全局 handler，撤销新建 `services/exceptions.py`** | 单一异常声明中心，M8 路由层零 try/except |

---

## 3. 文件矩阵

```
backend/app/services/
├── auth_service.py        # Phase 1 留存，不动
├── agent_service.py       # 【新增】Agent CRUD：纯软删除，查询默认过滤 is_active
├── workflow_service.py    # 【新增】Workflow CRUD：轻量拓扑预检 + 构造注入 M6 触发
└── execution_service.py   # 【新增】Executions/Events 只读：物理分页 + Timeline 聚合

backend/app/api/dependencies/
└── orchestrator.py        # 【新增】get_coordinator() — 进程内 Coordinator 单例装配

backend/app/schemas/
├── agent.py               # 【新增】AgentRequest / AgentUpdateRequest（Service 入参）
└── workflow.py            # 【新增】WorkflowRequest / WorkflowUpdateRequest / TriggerRequest

backend/app/core/
└── exceptions.py          # 【增补】追加三行 ValidationError(422) 子类
```

**注**：响应 Schema（`AgentResponse`/`WorkflowResponse`/`ExecutionResponse` 等）归 M8 创建（谁用谁建，M7 Service 只返回 ORM 实体，用不到响应 Schema）。

---

## 4. 依赖纯净性与合规

```
services/agent_service.py      → models/                    （纯 CRUD）
services/workflow_service.py   → models/ + orchestrator/    （触发执行，合法向 M6 引用）
services/execution_service.py  → models/                    （纯只读）
api/dependencies/orchestrator  → orchestrator/ + services/  （装配层，属 api/）
```

全部顺依赖链方向，无反向依赖。`WorkflowService → orchestrator/` 是路线图 §M7 明示的合法依赖。

**`get_coordinator` 归属决策**：放 `api/dependencies/orchestrator.py`，**不放** `orchestrator/__init__.py`（防 FastAPI 污染下漏引擎层，保引擎平台无关）或 `common/`（防沦为架构垃圾场）。此目录随 Phase 演进为 API 层的 IoC 配置中心。

---

## 5. 依赖装配（`api/dependencies/orchestrator.py`）

```python
from fastapi import Depends
from redis.asyncio import Redis

from app.common.redis_client import get_redis
from app.orchestrator.coordinator import Coordinator
from app.services.llm_service import LLMService

_coordinator: Coordinator | None = None


async def get_coordinator(redis: Redis = Depends(get_redis)) -> Coordinator:
    """进程内 Coordinator 单例装配：LLMService + Coordinator。"""
    global _coordinator
    if _coordinator is None:
        _coordinator = Coordinator(redis_client=redis, llm_service=LLMService())
    return _coordinator
```

M8 端点 `Depends(get_coordinator)` 拿到实例，构造 `WorkflowService(db, coordinator)` 时注入。`AgentService(db)` / `ExecutionService(db)` 保持单一 `db` 构造。

---

## 6. 事务边界铁律（贯穿全 M7）

对齐现有 [auth_service.py](../../backend/app/services/auth_service.py) 的**单一事务边界**原则：一个 HTTP 请求 = 一个事务，由 [get_db](../../backend/app/db/session.py) 依赖在请求末尾统一 `commit`。

| 方法类型 | 提交语义 | 理由 |
|---|---|---|
| 普通 CRUD（create/update/delete） | `await self.db.flush()` + `refresh` | 沿用 AuthService 风格，最终 commit 交给 `get_db` 请求末尾 |
| **`trigger_execution`（唯一例外）** | **显式 `await self.db.commit()`** | 跨越「请求事务 → M6 后台协程独立事务」边界，必须先落盘 |

**为什么 `trigger_execution` 必须显式 commit**：`Coordinator.start_execution()` 内部 `asyncio.create_task` 拉起的后台协程，用**独立的 `AsyncSessionLocal` 短事务**（见 [scheduler.py](../../backend/app/orchestrator/scheduler.py) `load_execution_context`）反查 PG。若不显式 commit，后台协程看不到未提交的执行实例，M6 立刻抛 `OrchestratorError("执行实例不存在")` 失败收口。

**黄金时序**：先落库提交（DB Write-Ahead），再异步起飞（start_execution），防御 Race Condition。

---

## 7. 错误治理（增补 `core/exceptions.py`）

复用现有 `NexusMeshException` 全局 handler 体系（已在 [main.py](../../backend/app/main.py) 注册）。M7 仅做**外科手术式增补**：追加一个三行 `ValidationError`，走**类属性**声明状态码（与 `NotFoundError`/`ConflictError` 同构，不自定义 `__init__`）。

```python
# core/exceptions.py 尾部追加
class ValidationError(NexusMeshException):
    status_code = 422
    detail = "Validation failed"
```

⚠️ **实现禁忌**：**不得**写 `super().__init__(status_code=..., detail=...)`——基类 `__init__` 只接受 `detail` 单参，`status_code` 是类属性，传关键字会 `TypeError`。

M7 抛异常语义映射：

| 场景 | 异常 | HTTP |
|---|---|---|
| Agent/Workflow/Execution 不存在或已软删除 | `NotFoundError` | 404 |
| 拓扑预检失败（三铁律任一不过） | `ValidationError` | 422 |

M8 路由层**零 try/except**，全交全局 handler 熔断。

---

## 8. AgentService 接口契约

`AgentService(db)`，单一 db 构造，不感知 Coordinator。入参统一用 Pydantic Schema（挡批量赋值漏洞）。

| 方法 | 签名 | 语义 |
|---|---|---|
| `create_agent` | `(schema: AgentRequest, created_by: UUID) -> Agent` | 写 `created_by`；`is_active=True`；`flush`+`refresh` |
| `get_agent_detail` | `(agent_id: UUID) -> Agent` | 防御软删除，无/已删抛 `NotFoundError` |
| `list_agents` | `(limit=20, offset=0) -> list[Agent]` | 默认 `where(is_active==True)`，`created_at DESC` 物理分页 |
| `update_agent` | `(agent_id, schema: AgentUpdateRequest) -> Agent` | 复用 `get_agent_detail` 校验；`flush` |
| `delete_agent` | `(agent_id: UUID) -> None` | 软删除（`is_active=False`）；幂等静默 |

**关键设计**：
- **创建者追踪**：`create_agent` 接收 `created_by: UUID`（M8 从 `current_user.id` 注入），写入 `agents.created_by`。
- **软删除**：`delete_agent` 仅置 `is_active=False`，**绝不** `session.delete()`。
- **幂等**：`delete_agent` 遇不存在/已删除直接 `return`（静默成功），防前端连点崩溃。
- **脏字段防御**：`update_agent` 迭代赋值前 `pop("id")` + `pop("is_active")`，防批量赋值越权。
- **返回类型**：统一 `list[Agent]` 显式 `list(result.scalars().all())`（对齐 M6 风格）。
- **核心红利**：`list/detail` 对软删除隐形；M6 `Scheduler.load_agent` 用 `session.get` 绕过 `is_active`，进行中工作流与历史回溯照跑。

---

## 9. WorkflowService 接口契约

`WorkflowService(db, coordinator)`，构造注入 M6 Coordinator。

| 方法 | 签名 | 语义 |
|---|---|---|
| `create_workflow` | `(schema: WorkflowRequest, created_by: UUID) -> Workflow` | 先 `_validate_topology`，写 `created_by`，再 `is_active=True`；`flush` |
| `get_workflow_detail` | `(workflow_id: UUID) -> Workflow` | 防御软删除，无/已删抛 `NotFoundError` |
| `update_workflow` | `(workflow_id, schema: WorkflowUpdateRequest) -> Workflow` | 复用 detail 校验；带 topology 变更则重跑预检；`pop id/is_active`；`flush` |
| `trigger_execution` | `(workflow_id: UUID, task_input: dict) -> UUID` | 见 §6 黄金时序；**唯一显式 commit** |
| `delete_workflow` | `(workflow_id: UUID) -> None` | 软删除；幂等静默 |

### 9.1 `trigger_execution` 黄金时序

```python
workflow = await self.get_workflow_detail(workflow_id)   # 1. 反查，防御软删除 → 404
execution = WorkflowExecution(
    workflow_id=workflow_id, status="pending", input=task_input
)
self.db.add(execution)
await self.db.commit()                                    # 2. 🔒 显式落盘（唯一例外）
await self.db.refresh(execution)                          # 3. 拿 DB 生成的 id
await self.coordinator.start_execution(str(execution.id)) # 4. 🚀 起飞（Fire-and-Forget）
return execution.id
```

> **注**：`trigger_execution` 不接收 `user_id`——`workflow_executions` 表无 `triggered_by`/`created_by` 字段（M1 现状）。补触发者追踪需越界改 M1 模型 + 迁移，超出 M7 范围，列入 §11 演进路标。

### 9.2 `_validate_topology` 三铁律预检

**与 M6 [router.py](../../backend/app/orchestrator/router.py) 运行时严格对齐**。上游契约：**MVP 规定所有节点皆为 Agent 节点**（无 start/end/input 虚拟节点，每节点必绑 `data.agent_id`）。

**铁律一 · 节点非空**：`nodes` 空 → `ValidationError`。

**铁律二 · 单入口判定（M7 增强约束，非 M6 镜像）**：
- 入口 = 不被任何 `edge.target` 指向的节点（**对齐 M6 `_find_entry_node`，只看无入边，不看 node.type**）。
- 无入口（闭环死锁）→ `ValidationError`。
- 入口 > 1 → `ValidationError`。⚠️ **此唯一性拦截是 M7 主动施加的增强防呆，M6 运行时采用「懒惰模式」只取第一个无入边节点，不校验唯一性。**

**铁律三 A · 全 Agent 节点契约强制**：
```python
for node in nodes:
    if not node.get("data", {}).get("agent_id"):
        raise ValidationError(f"节点 {node.get('id')} 未绑定 agent_id，违反'全 Agent 节点'契约。")
```
⚠️ **必须主动强制**，不能靠「恰好没绑就跳过」的静默过滤——否则 M7 会放行 M6 跑起来 `load_agent(None)` 立刻 failed 的拓扑，违背防呆初衷。

**铁律三 B · 跨表 Agent 存在性批量预检**：
- 抽取全部 `data.agent_id` 去重；逐个 `uuid.UUID()` 校验格式，非法 → `ValidationError`。
- 一条 `select(Agent.id).where(Agent.id.in_(uuids), Agent.is_active == True)` **批量查询**（避免 N+1）。
- `len(db_active_ids) != len(parsed_uuids)` → 揪出缺失 ID 列表，`ValidationError`。**写入期从严：不许引用已软删除 Agent**（与 M6 运行期从宽互补——见 §9.3）。

### 9.3 M7/M6 纵深防御契约（校准版）

| 层 | 关卡 | 拦截对象 | 对软删除 Agent 态度 |
|---|---|---|---|
| M7 前置守门员 | create/update 时 `is_active==True` 批量查表 | 引用**不存在或已软删除** Agent 的**新配置** | ❌ 拒绝写入 |
| M6 运行时安全网 | `load_agent` 的 `is None` | **幽灵 UUID**（物理不存在） | ✅ 放行（软删照跑，红利兑现） |

⚠️ **纠正常见误解**：M6 的 `if row is None` **不能**拦"运行中被软删除"的 Agent——`session.get()` 按主键直取，软删除行物理存在，返回非 None。软删除 Agent **正常放行**（第 1 支柱红利）。M6 该分支真正拦的是幽灵 UUID（物理不存在）。**写入期从严，运行期从宽**，两层不重叠。

---

## 10. ExecutionService 只读契约

`ExecutionService(db)`，100% Read-Only，单一 db 构造，不注入 Coordinator。

| 方法 | 签名 | 语义 |
|---|---|---|
| `get_execution_detail` | `(execution_id: UUID) -> WorkflowExecution` | 不存在抛 `NotFoundError`（**无软删除过滤**） |
| `list_executions` | `(workflow_id=None, status=None, limit=20, offset=0) -> list[WorkflowExecution]` | 按 workflow/status 过滤，`created_at DESC` 物理分页 |
| `get_execution_timeline` | `(execution_id: UUID) -> list[ExecutionEvent]` | 先校验执行存在（404），再按 `created_at ASC` 捞全量事件 |

**关键设计**：
- **执行记录不软删除**：`WorkflowExecution` 无 `is_active` 字段——执行是不可变历史事实（只有 status 生命周期），永不删除。软删除只针对**资产**（Agent/Workflow）。
- **Timeline 用 ASC**：单次执行事件按 INIT→…→FINISH 正序回溯；区别于 `list_executions` 的 DESC（最新执行在前）。两个不同查询意图。
- **Timeline 先击穿 404**：先 `get_execution_detail` 触发 404，消除"200 OK 但空数组"的语义含糊（区分「执行不存在」vs「存在但暂无事件」）。
- **不加 stage 过滤**（YAGNI）：单次执行事件仅十余条，前端拿全量后客户端 `.filter()` 即可；M12 未开工，等确需再补。
- **分页不加 total**（YAGNI）：避免 `COUNT(*)` 全表扫描的 P99 退化；用「上一页/下一页」交互。演进路标：单 workflow 执行破万且翻页卡顿 → 迁移 `(created_at, id)` 复合游标。

---

## 11. 演进路标（ADR）

| 维度 | 当前决策 | 触发升级信号 | 升级方向 |
|---|---|---|---|
| 删除策略 | 纯软删除 | —（永久策略，M12 依赖） | 不升级 |
| 触发时序 | 先落库 commit 再起飞 | —（架构铁律） | 不升级 |
| 拓扑校验 | 轻量三铁律预检 | 出现环/复杂 DAG 可达性需求 | 补图论完整性校验（选项 C） |
| 分页 | `limit/offset` 无 total | 单 workflow 执行破万 + 翻页卡顿 | `(created_at, id)` 复合游标 tie-breaker |
| Timeline 过滤 | 无 stage 过滤 | M12 明确需要后端过滤 | 补 `stage` 参数 |
| 执行触发者追踪 | 不追踪（表无字段） | 多租户/审计启用 | M1 加 `workflow_executions.triggered_by` + 迁移 |


