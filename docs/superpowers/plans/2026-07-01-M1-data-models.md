# M1 数据模型扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `workflows`、`workflow_executions`、`execution_events` 三张表的 SQLAlchemy 模型与 Alembic 迁移，使数据库结构与设计文档 §8 一致。

**Architecture:** 沿用 Phase 1 已确立的模型风格（UUID 主键、`org_id` 预留、外键 `ON DELETE SET NULL`、`updated_at` 走 `trigger_set_timestamp()` 触发器、枚举用 String 列、无 ORM relationship）。普通索引由模型 `index=True` 声明并交给 autogenerate 管理；两个特殊索引（status 部分索引、created_at DESC 索引）与触发器手写进迁移，并通过 `env.py` 的 `include_object` 过滤器排除出 autogenerate 比对，保证 `alembic check` 干净。

**Tech Stack:** Python 3.13、SQLAlchemy 2.0（异步）、Alembic 1.14、PostgreSQL 17、pytest。

**规格来源:** `docs/superpowers/specs/2026-07-01-module-roadmap.md`（M1 条目）+ 2026-07-01 brainstorming 确认的三项决策（started_at/finished_at、protocol_stage 顶层列、created_at 内联）。

**前置环境:** PostgreSQL 容器已运行（`docker compose up -d postgres`），根目录 `.env` 已存在，当前迁移 head 为 `8f1c2a4b6d7e`。所有命令在 `backend/` 目录执行。

---

## 已知阻塞（Task 1 修复）

现有 `User`/`Agent` 模型未在 `org_id`/`created_by` 上声明 `index=True`，但迁移 `8f1c2a4b6d7e` 已为其建索引。这导致 `alembic check` 持续报告要删除 `ix_users_org_id`、`ix_agents_org_id`、`ix_agents_created_by`。M1 DoD 要求 autogenerate 无残余 diff，故必须先修此漂移。修复仅为模型补声明使其与既有 DB 一致，**不产生新迁移**。

---

## 文件结构

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/app/models/user.py` | 补 `org_id` 索引声明，消除漂移 | 修改 |
| `backend/app/models/agent.py` | 补 `org_id`/`created_by` 索引声明 | 修改 |
| `backend/app/models/workflow.py` | Workflow 模型 | 新建 |
| `backend/app/models/execution.py` | WorkflowExecution 模型 | 新建 |
| `backend/app/models/event.py` | ExecutionEvent 模型（仅追加） | 新建 |
| `backend/app/models/__init__.py` | 注册新模型到 `Base.metadata` | 修改 |
| `backend/migrations/env.py` | `include_object` 过滤手写索引 | 修改 |
| `backend/migrations/versions/<新>.py` | 三表迁移 + 触发器 + 特殊索引 | 新建 |
| `backend/tests/unit/test_models.py` | 模型元数据单测 | 新建 |

---

### Task 1: 修复既有模型索引漂移

**Files:**
- Test: `backend/tests/unit/test_models.py`
- Modify: `backend/app/models/user.py:15`
- Modify: `backend/app/models/agent.py:16-21`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_models.py`：

```python
from app.models.agent import Agent
from app.models.user import User


def _indexed_columns(model) -> set[tuple[str, ...]]:
    return {tuple(c.name for c in idx.columns) for idx in model.__table__.indexes}


def test_user_org_id_indexed() -> None:
    assert ("org_id",) in _indexed_columns(User)


def test_agent_fk_columns_indexed() -> None:
    indexed = _indexed_columns(Agent)
    assert ("org_id",) in indexed
    assert ("created_by",) in indexed
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: FAIL —— 模型未声明 `index=True`，`indexes` 集合为空。

- [ ] **Step 3: 为 User.org_id 补索引声明**

`backend/app/models/user.py` 第 15 行改为：

```python
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
```

- [ ] **Step 4: 为 Agent 的 org_id / created_by 补索引声明**

`backend/app/models/agent.py` 第 16-21 行改为：

```python
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: PASS（2 项）。

- [ ] **Step 6: 验证不产生新迁移（漂移已消除）**

Run: `uv run alembic check`
Expected: `No new upgrade operations detected.`（此前会报 3 个 removed index）。
> 若 `alembic check` 因环境不可用，改用 `uv run alembic revision --autogenerate -m tmp` 后确认生成体为空 `pass`，随后删除该临时文件。

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/user.py backend/app/models/agent.py backend/tests/unit/test_models.py
git commit -m "fix: 为 User/Agent 补齐 org_id 与外键列索引声明，消除迁移漂移"
```

### Task 2: Workflow 模型

**Files:**
- Create: `backend/app/models/workflow.py`
- Test: `backend/tests/unit/test_models.py`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/unit/test_models.py`：

```python
def test_workflow_table_shape() -> None:
    from app.models.workflow import Workflow

    cols = Workflow.__table__.columns
    assert cols["created_by"].foreign_keys  # FK -> users.id
    assert ("created_by",) in _indexed_columns(Workflow)
    assert ("org_id",) in _indexed_columns(Workflow)
    assert cols["topology"].nullable is False
    assert {"id", "org_id", "created_by", "name", "description",
            "topology", "is_active", "created_at", "updated_at"} <= set(cols.keys())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_models.py::test_workflow_table_shape -v`
Expected: FAIL —— `ModuleNotFoundError: app.models.workflow`。

- [ ] **Step 3: 创建模型**

`backend/app/models/workflow.py`：

```python
import uuid

from sqlalchemy import UUID, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    topology: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Workflow {self.name}>"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_models.py::test_workflow_table_shape -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/workflow.py backend/tests/unit/test_models.py
git commit -m "feat: 新增 Workflow 模型（工作流定义与拓扑快照）"
```

### Task 3: WorkflowExecution 模型

**Files:**
- Create: `backend/app/models/execution.py`
- Test: `backend/tests/unit/test_models.py`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/unit/test_models.py`：

```python
def test_workflow_execution_table_shape() -> None:
    from app.models.execution import WorkflowExecution

    cols = WorkflowExecution.__table__.columns
    assert cols["workflow_id"].foreign_keys  # FK -> workflows.id
    assert ("workflow_id",) in _indexed_columns(WorkflowExecution)
    assert cols["status"].nullable is False
    assert cols["input"].nullable is False
    assert cols["output"].nullable is True
    assert cols["started_at"].nullable is True
    assert cols["finished_at"].nullable is True
    assert {"id", "org_id", "workflow_id", "status", "input", "output",
            "error", "started_at", "finished_at", "created_at",
            "updated_at"} <= set(cols.keys())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_models.py::test_workflow_execution_table_shape -v`
Expected: FAIL —— `ModuleNotFoundError: app.models.execution`。

- [ ] **Step 3: 创建模型**

`backend/app/models/execution.py`：

```python
import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WorkflowExecution(Base, TimestampMixin):
    __tablename__ = "workflow_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending / running / completed / failed
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<WorkflowExecution {self.id} [{self.status}]>"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_models.py::test_workflow_execution_table_shape -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/execution.py backend/tests/unit/test_models.py
git commit -m "feat: 新增 WorkflowExecution 模型（单次执行实例）"
```

### Task 4: ExecutionEvent 模型（仅追加）

**Files:**
- Create: `backend/app/models/event.py`
- Test: `backend/tests/unit/test_models.py`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/unit/test_models.py`：

```python
def test_execution_event_is_append_only() -> None:
    from app.models.event import ExecutionEvent

    cols = ExecutionEvent.__table__.columns
    assert cols["execution_id"].foreign_keys  # FK -> workflow_executions.id
    assert ("execution_id",) in _indexed_columns(ExecutionEvent)
    assert "created_at" in cols
    assert "updated_at" not in cols  # 仅追加，无 updated_at
    assert cols["protocol_stage"].nullable is False
    assert {"id", "execution_id", "protocol_stage", "event_type",
            "payload", "created_at"} == set(cols.keys())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_models.py::test_execution_event_is_append_only -v`
Expected: FAIL —— `ModuleNotFoundError: app.models.event`。

- [ ] **Step 3: 创建模型**

`backend/app/models/event.py`。注意：**不继承 `TimestampMixin`**（无 updated_at），`created_at` 内联单列。

```python
import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExecutionEvent(Base):
    """五阶段协议事件流，仅追加，无 updated_at。"""

    __tablename__ = "execution_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    protocol_stage: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False
    )  # INIT / RECEIVE / ROUTE / EXECUTE / FINISH
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # agent_spawn / agent_call / agent_finish / agent_reflect
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ExecutionEvent {self.event_type} [{self.protocol_stage}]>"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_models.py::test_execution_event_is_append_only -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/event.py backend/tests/unit/test_models.py
git commit -m "feat: 新增 ExecutionEvent 模型（仅追加的五阶段事件流）"
```

### Task 5: 注册模型并配置 autogenerate 过滤器

模型必须被 `models/__init__.py` 导入，`Base.metadata` 才认得它们（`env.py` 里 `from app.models import Base`，靠 `__init__` 的 import 触发建表映射）。同时给 `env.py` 加 `include_object`，让手写的两个特殊索引（status 部分索引、created_at DESC 索引）不被 autogenerate 视为“多余对象”而反复要求删除。

**Files:**
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/migrations/env.py:20`
- Test: `backend/tests/unit/test_models.py`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/unit/test_models.py`：

```python
def test_all_tables_registered_on_metadata() -> None:
    from app.models import Base

    assert {
        "users", "agents", "workflows",
        "workflow_executions", "execution_events",
    } <= set(Base.metadata.tables.keys())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_models.py::test_all_tables_registered_on_metadata -v`
Expected: FAIL —— 新三表未导入，不在 `Base.metadata.tables`。

- [ ] **Step 3: 注册新模型**

`backend/app/models/__init__.py` 全文替换为：

```python
from app.models.agent import Agent
from app.models.base import Base
from app.models.event import ExecutionEvent
from app.models.execution import WorkflowExecution
from app.models.user import User
from app.models.workflow import Workflow

__all__ = [
    "Agent",
    "Base",
    "ExecutionEvent",
    "User",
    "Workflow",
    "WorkflowExecution",
]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_models.py::test_all_tables_registered_on_metadata -v`
Expected: PASS。

- [ ] **Step 5: 给 env.py 加 include_object 过滤器**

`backend/migrations/env.py` 第 20 行 `target_metadata = Base.metadata` 之后插入：

```python


# 手写管理的索引名单：autogenerate 无法表达（部分索引、DESC 排序），
# 由迁移手工维护，故从自动比对中排除，避免 alembic check 反复要求删除。
_MANUAL_INDEXES = {
    "ix_workflow_executions_active_status",
    "ix_execution_events_created_at_desc",
}


# alembic 回调，签名由框架固定（object/name/type_/reflected/compare_to）。
def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "index" and name in _MANUAL_INDEXES:
        return False
    return True
```

> 项目 ruff 仅启用 `E/F/I/UP`（见 `pyproject.toml`），未启用 annotations 规则，故此回调无需类型标注即可通过检查。

- [ ] **Step 6: 在两个 context.configure 里挂上过滤器**

`backend/migrations/env.py` 的 `run_migrations_offline()` 中，`context.configure(...)` 调用补参数：

```python
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
```

同一文件的 `do_run_migrations()` 中：

```python
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()
```

- [ ] **Step 7: ruff 检查 env.py**

Run: `uv run ruff check migrations/env.py`
Expected: All checks passed（项目 ruff 仅启用 E/F/I/UP，回调无需类型标注）。

- [ ] **Step 8: 提交**

```bash
git add backend/app/models/__init__.py backend/migrations/env.py backend/tests/unit/test_models.py
git commit -m "feat: 注册新模型并配置 autogenerate 手写索引过滤器"
```

### Task 6: 生成并补全迁移

策略：用 autogenerate 生成三张表及其普通索引（与模型 `index=True` 一致），再手工追加两个特殊索引与两个触发器。`downgrade` 保持纯 autogenerate —— PostgreSQL `DROP TABLE` 会级联删除该表上的索引与触发器，无需手动补，符合最小化原则。触发器函数 `trigger_set_timestamp()` 由前置迁移 `8f1c2a4b6d7e` 保证存在，不重复定义。

**Files:**
- Create: `backend/migrations/versions/<autogenerate 生成的随机ID>_add_workflows_executions_events.py`

- [ ] **Step 1: 运行 autogenerate 生成迁移**

Run: `uv run alembic revision --autogenerate -m "add workflows executions events"`
Expected: 生成一个新迁移文件，`down_revision = "8f1c2a4b6d7e"`，`upgrade()` 中含三张表的 `op.create_table` 与普通 `op.create_index`（`ix_workflows_org_id`、`ix_workflows_created_by`、`ix_workflow_executions_org_id`、`ix_workflow_executions_workflow_id`、`ix_execution_events_execution_id`、`ix_execution_events_protocol_stage`），无任何 `drop_*` 操作。

- [ ] **Step 2: 核对生成体无杂项**

打开新生成的迁移文件，确认 `upgrade()` 只创建三张新表及上述普通索引，`downgrade()` 只删除它们。若出现对 `users`/`agents` 既有索引的 `drop_index`，说明 Task 1 未生效，回到 Task 1 修复后删除本文件重来。

- [ ] **Step 3: 在 upgrade() 末尾追加特殊索引与触发器**

在 `upgrade()` 函数体的 `# ### end Alembic commands ###` 之前追加：

```python
    # 部分索引：仅索引进行中的执行（设计文档 §8.4）
    op.create_index(
        "ix_workflow_executions_active_status",
        "workflow_executions",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    # 时间线倒序查询索引（设计文档 §8.4）
    op.create_index(
        "ix_execution_events_created_at_desc",
        "execution_events",
        [sa.text("created_at DESC")],
    )
    # updated_at 自动更新触发器（execution_events 仅追加，不挂触发器）
    for _table in ("workflows", "workflow_executions"):
        op.execute(
            f"CREATE TRIGGER set_timestamp_{_table} "
            f"BEFORE UPDATE ON {_table} "
            f"FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();"
        )
```

> `downgrade()` 无需改动：这两个索引与两个触发器均挂在被 `drop_table` 删除的表上，`DROP TABLE` 会自动级联清除。

- [ ] **Step 4: 应用迁移**

Run: `uv run alembic upgrade head`
Expected: `Running upgrade 8f1c2a4b6d7e -> <新ID>, add workflows executions events`，无报错。

- [ ] **Step 5: ruff 检查迁移文件**

Run: `uv run ruff check migrations`
Expected: All checks passed。

- [ ] **Step 6: 提交**

```bash
git add backend/migrations/versions/
git commit -m "feat: 新增 workflows/executions/events 三表迁移及触发器与特殊索引"
```

### Task 7: M1 完成标准（DoD）端到端验证

无代码改动，作为 M1 的验收闸门。任一检查失败则回到对应 Task 修复。

**Files:** 无（验证任务）

- [ ] **Step 1: autogenerate 无残余 diff**

Run: `uv run alembic check`
Expected: `No new upgrade operations detected.`
> 证明模型与迁移完全一致；手写索引已由 `include_object` 排除，触发器不在 autogenerate 比对范围。

- [ ] **Step 2: 迁移双向可逆**

```bash
uv run alembic downgrade base
uv run alembic upgrade head
```
Expected: 两条命令均无报错；downgrade 依次回滚至 base，upgrade 重新建至最新。

- [ ] **Step 3: 触发器实测（跨事务）**

```bash
docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -c \
  "INSERT INTO workflows (id, name, is_active) VALUES (gen_random_uuid(), 'trig-test', true);"
docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -c \
  "UPDATE workflows SET name='trig-test-2' WHERE name='trig-test';"
docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -t -c \
  "SELECT updated_at > created_at FROM workflows WHERE name='trig-test-2';"
```
Expected: 最后一条返回 `t`（触发器已刷新 updated_at）。
清理：`docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -c "DELETE FROM workflows WHERE name='trig-test-2';"`

- [ ] **Step 4: 特殊索引与触发器确实存在**

```bash
docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -t -c \
  "SELECT indexname FROM pg_indexes WHERE indexname IN ('ix_workflow_executions_active_status','ix_execution_events_created_at_desc') ORDER BY 1;"
docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -t -c \
  "SELECT tgname FROM pg_trigger WHERE tgname IN ('set_timestamp_workflows','set_timestamp_workflow_executions') ORDER BY 1;"
```
Expected: 第一条列出 2 个索引；第二条列出 2 个触发器。

- [ ] **Step 5: 部分索引条件正确**

```bash
docker exec nexusmesh-postgres psql -U nexusmesh -d nexusmesh_db -t -c \
  "SELECT indexdef FROM pg_indexes WHERE indexname='ix_workflow_executions_active_status';"
```
Expected: 输出含 `WHERE (status = ANY (ARRAY['pending'::..., 'running'::...]))` 或等价的 `status IN ('pending','running')` 谓词。

- [ ] **Step 6: 全量 lint 与测试**

```bash
uv run ruff check app tests migrations
uv run pytest tests -q
```
Expected: ruff `All checks passed!`；pytest 全部通过（含 Task 1-5 新增的模型测试与 Phase 1 既有测试）。

- [ ] **Step 7: 更新 MEMORY.md 记录本模块结论**

若实施中出现值得跨会话记住的陷阱（如 autogenerate 与手写索引的协作方式），在 `.claude/MEMORY.md` 的「已知陷阱」下追加一行。无新发现则跳过。




