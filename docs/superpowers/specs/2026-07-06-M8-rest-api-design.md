# M8 REST API 扩展 — 详细设计方案

> 状态：已实现
> 日期：2026-07-06
> 依赖：M7 业务服务层（agent_service / workflow_service / execution_service 已落地）
> 定位：API 网关层，`api/ → services/` 单向依赖的最外层入口

---

## 1. 设计目标与边界

M8 是 NexusMesh 后端的 **HTTP 契约层**，职责单一而清晰：把 M7 已实现的三个业务 Service（三驾马车）以 RESTful 协议暴露为 14 个端点，完成 **鉴权守门、请求校验、视图投影、状态码语义** 四件事，路由体内**零业务逻辑**。

### 1.1 职责归属（谁负责什么）

| 关注点 | 归属 | 说明 |
|--------|------|------|
| 业务规则、事务、拓扑校验 | M7 Service | M8 不碰，只调用 |
| HTTP 路由、状态码、鉴权装配 | M8（本设计） | 路由体只做"调用 + 投影" |
| Request Schema（入参校验） | M7 已建 | `AgentRequest` / `WorkflowRequest` / `TriggerRequest` 等 |
| Response Schema（视图投影） | **M8 新建** | 谁用谁建，List/Detail 双 Schema |
| 全局异常 → HTTP | 已有全局 handler | `NexusMeshException` 子类自动转 HTTP，路由零 try/except |

### 1.2 明确不做（YAGNI 边界）

- 不做分页 `total` 计数（沿用 M7 的 limit/offset，无 count 查询）
- 不暴露 `is_active`（软删记录已被 M7 查询层过滤，值恒为 True，噪音）
- 不暴露 `updated_at`（无明确前端消费方，列入演进路标）
- 不做回收站 / 软删记录管理视图（Phase 3）
- 不做 admin 保留高危操作端点（Phase 2/3）

---

## 2. 五大架构支柱（已锁定决策）

### 支柱一：端点矩阵与 URL 结构（executions 顶级资源）

14 个端点，Agent / Workflow 完全对称，Execution 为只读顶级资源，trigger 为 workflow 下的动作。

### 支柱二：RBAC 三级递进权限

- **viewer**：只读（全部 GET）
- **developer + admin**：读 + 写 + 触发
- **admin**：预留高危操作（Phase 2/3，本期不实现）

### 支柱三：PATCH 部分更新语义

写更新一律 `PATCH`（对齐 M7 `exclude_unset=True` 部分更新），非 `PUT`。

### 支柱四：List/Detail 双 Response Schema + 类继承

列表页剥离重资产字段（system_prompt / config / topology / input / output），详情页继承列表 Schema 追加全量字段。

### 支柱五：202 Accepted 异步触发契约

`POST /workflows/{id}/execute` 返回 `202 Accepted` + 极简 `{execution_id}`，诚实反映 fire-and-forget 语义。

---

## 3. 端点矩阵（14 个）

> 鉴权装配铁律：`require_roles(...)` 自身**已返回 `Depends(_check)`**，直接 `= require_roles(...)` 挂载，**不可**再套 `Depends(...)`（双重包装会报错）。`_check` 返回 `User` 对象，故 create 端点可直接取 `current_user.id` 作 `created_by`。

### 3.1 Agent 资产线

| 方法 | 路径 | 状态码 | 鉴权 | Response | Service 调用 |
|------|------|--------|------|----------|--------------|
| POST | `/agents` | 201 | `require_roles(DEVELOPER, ADMIN)` 保留 user | `AgentResponse` | `create_agent(payload, created_by=user.id)` |
| GET | `/agents` | 200 | `get_current_user` | `list[AgentListItem]` | `list_agents(limit, offset)` |
| GET | `/agents/{id}` | 200 | `get_current_user` | `AgentResponse` | `get_agent_detail(id)` |
| PATCH | `/agents/{id}` | 200 | `require_roles(DEVELOPER, ADMIN)` 丢弃 | `AgentResponse` | `update_agent(id, payload)` |
| DELETE | `/agents/{id}` | 204 | `require_roles(DEVELOPER, ADMIN)` 丢弃 | 无 | `delete_agent(id)` |

### 3.2 Workflow 资产线

| 方法 | 路径 | 状态码 | 鉴权 | Response | Service 调用 |
|------|------|--------|------|----------|--------------|
| POST | `/workflows` | 201 | `require_roles(DEVELOPER, ADMIN)` 保留 user | `WorkflowResponse` | `create_workflow(payload, created_by=user.id)` |
| GET | `/workflows` | 200 | `get_current_user` | `list[WorkflowListItem]` | `list_workflows(limit, offset)` |
| GET | `/workflows/{id}` | 200 | `get_current_user` | `WorkflowResponse` | `get_workflow_detail(id)` |
| PATCH | `/workflows/{id}` | 200 | `require_roles(DEVELOPER, ADMIN)` 丢弃 | `WorkflowResponse` | `update_workflow(id, payload)` |
| DELETE | `/workflows/{id}` | 204 | `require_roles(DEVELOPER, ADMIN)` 丢弃 | 无 | `delete_workflow(id)` |

### 3.3 Execution 运行时线

| 方法 | 路径 | 状态码 | 鉴权 | Response | Service 调用 |
|------|------|--------|------|----------|--------------|
| POST | `/workflows/{id}/execute` | **202** | `require_roles(DEVELOPER, ADMIN)` 丢弃 | `ExecutionAcceptedResponse` | `WorkflowService.trigger_execution(id, payload.task_input)` |
| GET | `/executions` | 200 | `get_current_user` | `list[ExecutionListItem]` | `list_executions(workflow_id, status, limit, offset)` |
| GET | `/executions/{id}` | 200 | `get_current_user` | `ExecutionResponse` | `get_execution_detail(id)` |
| GET | `/executions/{id}/timeline` | 200 | `get_current_user` | `list[TimelineEventResponse]` | `get_execution_timeline(id)` |

---

## 4. Response Schema 设计（字段级对齐真实 ORM）

> 所有字段名 1:1 咬合真实 ORM 列，`model_config = ConfigDict(from_attributes=True)` 自动投影零丢字段。已逐字段核对 `models/agent.py`、`models/workflow.py`、`models/execution.py`、`models/event.py`。

### 4.1 Agent 视图（追加至 `schemas/agent.py`，与现有 `AgentRequest`/`AgentUpdateRequest` 并列）

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class AgentListItem(BaseModel):
    """列表页摘要视图：剥离 system_prompt / config 重字段。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    agent_type: str
    llm_provider: str
    llm_model: str
    created_at: datetime


class AgentResponse(AgentListItem):
    """详情页全量视图：继承摘要，追加重资产字段。"""
    system_prompt: str | None = None
    config: dict
```

### 4.2 Workflow 视图（追加至 `schemas/workflow.py`）

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class WorkflowListItem(BaseModel):
    """列表页摘要：剥离沉重的 topology JSONB。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime


class WorkflowResponse(WorkflowListItem):
    """详情页全量：继承摘要，追加核心有向图拓扑。"""
    topology: dict
```

### 4.3 Execution 视图（新建 `schemas/execution.py`）

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ExecutionListItem(BaseModel):
    """历史执行列表项摘要。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID | None = None   # ORM 列 nullable（ondelete=SET NULL）
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExecutionResponse(ExecutionListItem):
    """执行详情页：继承摘要，追加输入/输出/错误。"""
    input: dict
    output: dict | None = None
    error: str | None = None


class ExecutionAcceptedResponse(BaseModel):
    """HTTP 202 专属响应体：只回执行令牌，逼客户端去 GET /executions/{id} 轮询。"""
    execution_id: uuid.UUID
```

### 4.4 Timeline 事件视图（新建，落点 `schemas/execution.py`）

> 已逐字段核对 `models/event.py` 的 `ExecutionEvent`：`id / execution_id / protocol_stage / event_type / payload / created_at`。
> **关键校准**：`execution_id` 在 ORM 层为 `nullable=True`（`ondelete="SET NULL"`），故 Schema 必须用 `uuid.UUID | None`，否则父执行被 SET NULL 时投影会抛错。`ExecutionEvent` 是仅追加事件流，无 `updated_at`。

```python
class TimelineEventResponse(BaseModel):
    """执行时间线单条事件（ASC 正序）。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID | None = None   # ORM nullable（ondelete=SET NULL）
    protocol_stage: str
    event_type: str
    payload: dict
    created_at: datetime
```

### 4.5 字段裁剪审计表

| 字段 | 是否暴露 | 理由 |
|------|----------|------|
| `is_active` | ❌ | M7 查询层已过滤软删记录，值恒 True，噪音 |
| `updated_at` | ❌ | 无明确前端消费方，YAGNI，列入路标 |
| `org_id` | ❌ | 多租户内部字段，本期单租户不暴露 |
| `created_by` | ❌ | 创建者审计字段，本期无展示需求，列入路标 |
| Agent `system_prompt`/`config` | 仅 Detail | 重资产，列表剥离 |
| Workflow `topology` | 仅 Detail | 重 JSONB，列表剥离 |
| Execution `input`/`output`/`error` | 仅 Detail | 运行时重字段，列表剥离 |

---

## 5. 文件落点矩阵

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/schemas/agent.py` | **追加** | 新增 `AgentListItem` + `AgentResponse`，与现有 `AgentRequest`/`AgentUpdateRequest` 并列 |
| `backend/app/schemas/workflow.py` | **追加** | 新增 `WorkflowListItem` + `WorkflowResponse`，与现有 `WorkflowRequest`/`WorkflowUpdateRequest`/`TriggerRequest` 并列 |
| `backend/app/schemas/execution.py` | **新建** | `ExecutionListItem` + `ExecutionResponse` + `ExecutionAcceptedResponse` + `TimelineEventResponse` |
| `backend/app/api/v1/agents.py` | **新建** | Agent 5 端点路由 |
| `backend/app/api/v1/workflows.py` | **新建** | Workflow 5 端点 + trigger 端点（共 6 个） |
| `backend/app/api/v1/executions.py` | **新建** | Execution 3 端点路由 |
| `backend/app/api/v1/__init__.py` | **修改** | 挂载三个新 router |

---

## 6. 路由层代码规范（参考范式）

> 路由体三步式：**守门 → 调 Service → 投影返回**，零业务逻辑，零 try/except。

### 6.1 鉴权装配两种模式

```python
# 模式 A：读端点（只需身份认证，三种角色天然可读）
current_user: User = Depends(get_current_user)

# 模式 B：写端点，不需要 user 对象（PATCH/DELETE/trigger）
_: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN)

# 模式 C：写端点，需要 user.id 落库（create）
current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN)
```

> **装配铁律**：`require_roles(...)` 自身已返回 `Depends(_check)` 包装对象，直接 `= require_roles(...)` 赋值，**不可**再套 `Depends(require_roles(...))`（双重包装，FastAPI 报错）。

### 6.2 Agent 路由示例（完整五端点）

```python
# backend/app/api/v1/agents.py
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRole, get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.agent import AgentListItem, AgentRequest, AgentResponse, AgentUpdateRequest
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    payload: AgentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> AgentResponse:
    agent = await AgentService(db).create_agent(payload, created_by=current_user.id)
    return AgentResponse.model_validate(agent)


@router.get("", response_model=list[AgentListItem])
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AgentListItem]:
    agents = await AgentService(db).list_agents(limit=limit, offset=offset)
    return [AgentListItem.model_validate(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AgentResponse:
    agent = await AgentService(db).get_agent_detail(agent_id)
    return AgentResponse.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> AgentResponse:
    agent = await AgentService(db).update_agent(agent_id, payload)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> None:
    await AgentService(db).delete_agent(agent_id)
```

### 6.3 Workflow 路由关键端点（trigger 完整示例）

```python
# backend/app/api/v1/workflows.py（trigger 端点）
from app.schemas.workflow import TriggerRequest
from app.schemas.execution import ExecutionAcceptedResponse
from app.api.dependencies.orchestrator import get_coordinator
from app.orchestrator.coordinator import Coordinator
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/{workflow_id}/execute", response_model=ExecutionAcceptedResponse, status_code=202)
async def trigger_workflow(
    workflow_id: uuid.UUID,
    payload: TriggerRequest,                                          # 使用 M7 已建 TriggerRequest
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    _: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),    # 守门，不需要 user 对象
) -> ExecutionAcceptedResponse:
    service = WorkflowService(db=db, coordinator=coordinator)
    execution_id = await service.trigger_execution(
        workflow_id=workflow_id, task_input=payload.task_input
    )
    return ExecutionAcceptedResponse(execution_id=execution_id)
```

> **`TriggerRequest` 复用铁律**：`schemas/workflow.py` 中已建 `TriggerRequest { task_input: dict }`，trigger 端点必须用它作 request body，不得使用裸 `task_input: dict`（否则 OpenAPI 文档会退化成无名 body，破坏 API 可读性）。

### 6.4 Execution 路由示例

```python
# backend/app/api/v1/executions.py
router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("", response_model=list[ExecutionListItem])
async def list_executions(
    workflow_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ExecutionListItem]:
    executions = await ExecutionService(db).list_executions(
        workflow_id=workflow_id, status=status, limit=limit, offset=offset
    )
    return [ExecutionListItem.model_validate(e) for e in executions]


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = await ExecutionService(db).get_execution_detail(execution_id)
    return ExecutionResponse.model_validate(execution)


@router.get("/{execution_id}/timeline", response_model=list[TimelineEventResponse])
async def get_execution_timeline(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TimelineEventResponse]:
    events = await ExecutionService(db).get_execution_timeline(execution_id)
    return [TimelineEventResponse.model_validate(e) for e in events]
```

---

## 7. Router 挂载（`api/v1/__init__.py` 修改）

现有文件只挂了 `auth_router` 和 `health_router`，M8 追加三个：

```python
# backend/app/api/v1/__init__.py
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.agents import router as agents_router
from app.api.v1.workflows import router as workflows_router
from app.api.v1.executions import router as executions_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(agents_router)
api_router.include_router(workflows_router)
api_router.include_router(executions_router)
```

---

## 8. 全局异常处理：路由层零 try/except

M7 的 `NotFoundError`(404) / `ConflictError`(409) / `ValidationError`(422) 均继承自 `NexusMeshException`，已有全局 handler 自动转换为对应 HTTP 响应。M8 路由层**不写任何 try/except**，所有异常由全局 handler 统一处理。

状态码映射：

| 异常类 | HTTP 状态码 | 场景 |
|--------|-------------|------|
| `NotFoundError` | 404 | Agent/Workflow/Execution 不存在或已软删 |
| `ValidationError` | 422 | 拓扑非法、参数格式错误（M7 业务校验） |
| `ConflictError` | 409 | 资源冲突（预留，本期 M7 未直接使用） |
| Pydantic `RequestValidationError` | 422 | Request body 字段校验失败（FastAPI 内建） |
| `HTTPException` 403 | 403 | RBAC 守门（`require_roles` 内部抛出） |
| `HTTPException` 401 | 401 | JWT 校验失败（`get_current_user` 内部抛出） |

---

## 9. 演进路标（Phase 2/3，本期不实现）

| 功能 | 阶段 | 说明 |
|------|------|------|
| `updated_at` 暴露至 Response | Phase 2 | 当前端有"最后修改时间"展示需求时追加 |
| `created_by` 暴露至 Response | Phase 2 | 需要展示创建者信息时追加 |
| 回收站管理视图（软删资产） | Phase 3 | 独立 Admin Schema，带 `is_active` 字段 |
| Admin 高危操作端点 | Phase 2/3 | `require_roles(UserRole.ADMIN)` 独占权限 |
| 分页 `total` 计数 | Phase 2 | 引入 `count(*)` 子查询，`PaginatedResponse` 包装 |
| Execution WebSocket 实时推送 | Phase 3 | M9 或独立 WS 模块，替代轮询 |
| `GET /executions` 状态码过滤枚举化 | Phase 2 | 将 `status: str` 替换为 `ExecutionStatus` 枚举 |

---

## 10. 设计自审清单

> **签名对齐**：所有 Service 调用签名已逐一核对真实代码（`agent_service.py` / `workflow_service.py` / `execution_service.py`）——无幻觉方法名、无幻觉参数。

| 检查项 | 结论 |
|--------|------|
| Response Schema 字段 1:1 咬合 ORM 列 | ✅ 逐字段核对 4 个 model 文件 |
| `execution_id` nullable（ondelete=SET NULL）已反映到 Schema | ✅ `uuid.UUID \| None` |
| `workflow_id` nullable（ondelete=SET NULL）已反映到 Schema | ✅ `uuid.UUID \| None` |
| `require_roles` 不重复套 `Depends(...)` | ✅ 直接 `= require_roles(...)` |
| create 端点用 `current_user.id` 作 `created_by` | ✅ 模式 C 装配 |
| trigger 端点用 `TriggerRequest` 而非裸 `dict` | ✅ 复用 M7 已建 Schema |
| trigger 返回 `202 Accepted`，非 `201` | ✅ `status_code=202` |
| 全局异常 handler，路由零 try/except | ✅ auth.py 路由风格一致 |
| Workflow 路由同时依赖 `get_db` + `get_coordinator` | ✅ 对齐 M7 `WorkflowService(db, coordinator)` |
| `DELETE` 端点返回 `204`，无 response body | ✅ `status_code=204`，无 `response_model` |
| Ruff E712（`.is_(True)` 不用 `== True`） | ✅ 路由层无布尔比较，Service 已落地 |
