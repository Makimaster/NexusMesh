"""M7 业务服务层单元测试（纯逻辑，fake session / mock coordinator）。"""

import uuid
from unittest.mock import AsyncMock

import pytest

import app.services.workflow_service as workflow_service_module
from app.core.exceptions import NexusMeshException, NotFoundError, ValidationError
from app.models.agent import Agent
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.schemas.agent import AgentRequest, AgentUpdateRequest
from app.schemas.workflow import TriggerRequest, WorkflowRequest, WorkflowUpdateRequest
from app.services.execution_service import ExecutionService
from app.services.agent_service import AgentService
from app.services.workflow_service import WorkflowService


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


def test_workflow_update_request_all_optional():
    req = WorkflowUpdateRequest(name="renamed")
    dumped = req.model_dump(exclude_unset=True)
    assert dumped == {"name": "renamed"}


def test_trigger_request_defaults_task_input():
    req = TriggerRequest()
    assert req.task_input == {}


async def test_get_coordinator_returns_singleton():
    import app.api.dependencies.orchestrator as dep
    from app.orchestrator.coordinator import Coordinator

    dep._coordinator = None  # 重置模块级单例，隔离测试
    dep._coordinator_redis = None
    fake_redis = object()

    try:
        first = await dep.get_coordinator(redis_client=fake_redis)
        second = await dep.get_coordinator(redis_client=fake_redis)

        assert isinstance(first, Coordinator)
        assert first is second  # 同一进程复用单例
    finally:
        dep._coordinator = None  # 清理，避免污染其他测试
        dep._coordinator_redis = None


async def test_get_coordinator_rebuilds_for_new_redis_and_wires_dependencies(
    monkeypatch,
):
    import app.api.dependencies.orchestrator as dep

    created_llm_services = []
    created_coordinators = []

    class FakeLLMService:
        def __init__(self):
            created_llm_services.append(self)

    class FakeCoordinator:
        def __init__(self, redis_client, llm_service):
            self.redis_client = redis_client
            self.llm_service = llm_service
            created_coordinators.append(self)

    monkeypatch.setattr(dep, "LLMService", FakeLLMService)
    monkeypatch.setattr(dep, "Coordinator", FakeCoordinator)
    dep._coordinator = None
    dep._coordinator_redis = None

    try:
        first_redis = object()
        second_redis = object()

        first = await dep.get_coordinator(redis_client=first_redis)
        second = await dep.get_coordinator(redis_client=first_redis)
        third = await dep.get_coordinator(redis_client=second_redis)

        assert first is second
        assert first is not third
        assert first.redis_client is first_redis
        assert third.redis_client is second_redis
        assert isinstance(first.llm_service, FakeLLMService)
        assert isinstance(third.llm_service, FakeLLMService)
        assert len(created_llm_services) == 2
        assert len(created_coordinators) == 2
    finally:
        dep._coordinator = None
        dep._coordinator_redis = None


class _FakeSession:
    """最小 fake AsyncSession：支持 get / add / flush / refresh。"""

    def __init__(self, store: dict | None = None) -> None:
        self._store = store or {}
        self.added: list = []
        self.flushed = 0
        self.committed = 0
        self.execute_rows: list = []
        self.last_statement = None

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

    async def execute(self, statement):
        self.last_statement = statement

        class _FakeScalarResult:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        class _FakeExecuteResult:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return _FakeScalarResult(self._rows)

        return _FakeExecuteResult(self.execute_rows)


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
    assert session.committed == 0


async def test_get_agent_detail_missing_raises_404():
    service = AgentService(_FakeSession())
    with pytest.raises(NotFoundError):
        await service.get_agent_detail(uuid.uuid4())


async def test_get_agent_detail_soft_deleted_raises_404():
    aid = uuid.uuid4()
    agent = Agent(
        id=aid,
        name="x",
        agent_type="a",
        llm_provider="p",
        llm_model="m",
        is_active=False,
    )
    service = AgentService(_FakeSession({aid: agent}))
    with pytest.raises(NotFoundError):
        await service.get_agent_detail(aid)


async def test_delete_agent_soft_deletes():
    aid = uuid.uuid4()
    agent = Agent(
        id=aid,
        name="x",
        agent_type="a",
        llm_provider="p",
        llm_model="m",
        is_active=True,
    )
    service = AgentService(_FakeSession({aid: agent}))

    await service.delete_agent(aid)

    assert agent.is_active is False


async def test_delete_agent_idempotent_when_missing():
    service = AgentService(_FakeSession())
    await service.delete_agent(uuid.uuid4())


async def test_list_agents_returns_rows_and_builds_active_desc_query():
    first = Agent(
        id=uuid.uuid4(),
        name="first",
        agent_type="a",
        llm_provider="p",
        llm_model="m",
        is_active=True,
    )
    second = Agent(
        id=uuid.uuid4(),
        name="second",
        agent_type="a",
        llm_provider="p",
        llm_model="m",
        is_active=True,
    )
    session = _FakeSession()
    session.execute_rows = [first, second]
    service = AgentService(session)

    rows = await service.list_agents(limit=5, offset=2)

    assert rows == [first, second]
    stmt_text = str(session.last_statement)
    assert "WHERE agents.is_active IS true" in stmt_text
    assert "ORDER BY agents.created_at DESC" in stmt_text
    assert "LIMIT :param_1" in stmt_text
    assert "OFFSET :param_2" in stmt_text


async def test_delete_agent_idempotent_when_soft_deleted():
    aid = uuid.uuid4()
    agent = Agent(
        id=aid,
        name="x",
        agent_type="a",
        llm_provider="p",
        llm_model="m",
        is_active=False,
    )
    session = _FakeSession({aid: agent})
    service = AgentService(session)

    await service.delete_agent(aid)

    assert session.flushed == 0


async def test_update_agent_pops_dirty_fields(monkeypatch):
    aid = uuid.uuid4()
    agent = Agent(
        id=aid,
        name="x",
        agent_type="a",
        llm_provider="p",
        llm_model="m",
        is_active=True,
    )
    service = AgentService(_FakeSession({aid: agent}))
    req = AgentUpdateRequest(name="renamed")
    dirty_id = uuid.uuid4()

    def fake_model_dump(self, *args, **kwargs):
        return {"name": "renamed", "id": dirty_id, "is_active": False}

    monkeypatch.setattr(AgentUpdateRequest, "model_dump", fake_model_dump)

    updated = await service.update_agent(aid, req)

    assert updated.name == "renamed"
    assert updated.is_active is True
    assert updated.id == aid


class _AgentQuerySession:
    """fake session：execute(select(Agent.id)...) 返回预置的存活 id 集合。"""

    def __init__(self, active_ids: set[uuid.UUID]) -> None:
        self._active_ids = active_ids
        self.last_statement = None
        self.execute_calls = 0

    async def execute(self, stmt):
        self.last_statement = stmt
        self.execute_calls += 1

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
    with pytest.raises(ValidationError, match="画布节点集合为空"):
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
    with pytest.raises(ValidationError, match="未检测到无入边的起始入口节点"):
        await service._validate_topology(topo)


async def test_validate_topology_multi_entry_rejected():
    a1 = uuid.uuid4()
    topo = {
        "nodes": [_node("node-1", str(a1)), _node("node-2", str(a1))],
        "edges": [],  # 两个都无入边 → 双入口
    }
    service = WorkflowService(_AgentQuerySession({a1}), coordinator=None)
    with pytest.raises(ValidationError, match="存在多个无入边的冲突起始节点"):
        await service._validate_topology(topo)


async def test_validate_topology_node_without_agent_id_rejected():
    topo = {
        "nodes": [_node("node-1", None)],  # 未绑 agent_id，违反全 Agent 节点契约
        "edges": [],
    }
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError, match="未绑定 agent_id"):
        await service._validate_topology(topo)


async def test_validate_topology_invalid_uuid_rejected():
    topo = {
        "nodes": [_node("node-1", "not-a-uuid")],
        "edges": [],
    }
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError, match="智能体主键格式非法"):
        await service._validate_topology(topo)


async def test_validate_topology_missing_agent_rejected():
    a1 = uuid.uuid4()
    topo = {"nodes": [_node("node-1", str(a1))], "edges": []}
    service = WorkflowService(_AgentQuerySession(set()), coordinator=None)
    with pytest.raises(ValidationError, match="引用的智能体不存在或已被清退"):
        await service._validate_topology(topo)


async def test_validate_topology_happy_path_passes():
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    session = _AgentQuerySession({a1, a2})
    topo = {
        "nodes": [_node("node-1", str(a1)), _node("node-2", str(a2))],
        "edges": [{"source": "node-1", "target": "node-2"}],
    }
    service = WorkflowService(session, coordinator=None)
    await service._validate_topology(topo)

    assert session.execute_calls == 1
    stmt_text = str(session.last_statement)
    assert "SELECT agents.id" in stmt_text
    assert "agents.id IN" in stmt_text
    assert "agents.is_active IS true" in stmt_text


def test_workflow_service_module_docstring_matches_scope():
    assert workflow_service_module.__doc__ == (
        "M7 WorkflowService：负责 Workflow 拓扑预检、CRUD 与执行触发。"
    )


async def test_create_workflow_sets_active_created_by_and_validates_topology():
    session = _FakeSession()
    service = WorkflowService(session, coordinator=None)
    creator = uuid.uuid4()
    topology = {"nodes": [{"id": "n1"}], "edges": []}
    req = WorkflowRequest(name="wf", topology=topology)
    service._validate_topology = AsyncMock()

    workflow = await service.create_workflow(req, created_by=creator)

    service._validate_topology.assert_awaited_once_with(topology)
    assert workflow.is_active is True
    assert workflow.created_by == creator
    assert session.flushed == 1
    assert session.committed == 0


async def test_get_workflow_detail_missing_raises_404():
    service = WorkflowService(_FakeSession(), coordinator=None)
    with pytest.raises(NotFoundError):
        await service.get_workflow_detail(uuid.uuid4())


async def test_get_workflow_detail_soft_deleted_raises_404():
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=False)
    service = WorkflowService(_FakeSession({wid: workflow}), coordinator=None)

    with pytest.raises(NotFoundError):
        await service.get_workflow_detail(wid)


async def test_list_workflows_returns_rows_and_builds_active_desc_query():
    first = Workflow(id=uuid.uuid4(), name="first", topology={}, is_active=True)
    second = Workflow(id=uuid.uuid4(), name="second", topology={}, is_active=True)
    session = _FakeSession()
    session.execute_rows = [first, second]
    service = WorkflowService(session, coordinator=None)

    rows = await service.list_workflows(limit=5, offset=2)

    assert rows == [first, second]
    stmt_text = str(session.last_statement)
    assert "WHERE workflows.is_active IS true" in stmt_text
    assert "ORDER BY workflows.created_at DESC" in stmt_text
    assert "LIMIT :param_1" in stmt_text
    assert "OFFSET :param_2" in stmt_text


async def test_update_workflow_revalidates_topology_and_pops_dirty_fields(
    monkeypatch,
):
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=True)
    service = WorkflowService(_FakeSession({wid: workflow}), coordinator=None)
    req = WorkflowUpdateRequest(name="renamed")
    dirty_id = uuid.uuid4()
    new_topology = {"nodes": [{"id": "n1"}], "edges": []}
    service._validate_topology = AsyncMock()

    def fake_model_dump(self, *args, **kwargs):
        return {
            "name": "renamed",
            "topology": new_topology,
            "id": dirty_id,
            "is_active": False,
        }

    monkeypatch.setattr(WorkflowUpdateRequest, "model_dump", fake_model_dump)

    updated = await service.update_workflow(wid, req)

    service._validate_topology.assert_awaited_once_with(new_topology)
    assert updated.name == "renamed"
    assert updated.topology == new_topology
    assert updated.is_active is True
    assert updated.id == wid


async def test_update_workflow_rejects_explicit_null_topology(monkeypatch):
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=True)
    service = WorkflowService(_FakeSession({wid: workflow}), coordinator=None)
    req = WorkflowUpdateRequest(name="renamed")

    def fake_model_dump(self, *args, **kwargs):
        return {"topology": None}

    monkeypatch.setattr(WorkflowUpdateRequest, "model_dump", fake_model_dump)

    with pytest.raises(ValidationError, match="拓扑非法"):
        await service.update_workflow(wid, req)


async def test_delete_workflow_soft_deletes():
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=True)
    session = _FakeSession({wid: workflow})
    service = WorkflowService(session, coordinator=None)

    await service.delete_workflow(wid)

    assert workflow.is_active is False
    assert session.flushed == 1


async def test_delete_workflow_idempotent_when_missing():
    service = WorkflowService(_FakeSession(), coordinator=None)

    await service.delete_workflow(uuid.uuid4())


async def test_delete_workflow_idempotent_when_soft_deleted():
    wid = uuid.uuid4()
    workflow = Workflow(id=wid, name="wf", topology={}, is_active=False)
    session = _FakeSession({wid: workflow})
    service = WorkflowService(session, coordinator=None)

    await service.delete_workflow(wid)

    assert session.flushed == 0


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
    coordinator.start_execution.side_effect = (
        lambda _execution_id: session.events.append("start_execution")
    )
    service = WorkflowService(session, coordinator=coordinator)

    exec_id = await service.trigger_execution(wid, task_input={"query": "hi"})

    assert session.events.index("commit") < session.events.index("start_execution")
    coordinator.start_execution.assert_awaited_once_with(str(exec_id))
    assert session.added[0].status == "pending"
    assert session.added[0].input == {"query": "hi"}


async def test_trigger_execution_missing_workflow_raises_404():
    session = _TriggerSession(None)
    coordinator = AsyncMock()
    service = WorkflowService(session, coordinator=coordinator)

    with pytest.raises(NotFoundError):
        await service.trigger_execution(uuid.uuid4(), task_input={})

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


class _ExecSession:
    """fake session：get 返回预置执行实例；execute 返回预置事件列表。"""

    def __init__(self, execution=None, events=None, rows=None) -> None:
        self._execution = execution
        self._events = events or []
        self._rows = rows if rows is not None else self._events
        self.last_statement = None

    async def get(self, model, pk):
        return self._execution

    async def execute(self, stmt):
        self.last_statement = stmt
        rows = self._rows

        class _Result:
            def scalars(self):
                return self

            def all(self):
                return list(rows)

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


async def test_list_executions_returns_rows_and_builds_filtered_query():
    workflow_id = uuid.uuid4()
    first = WorkflowExecution(id=uuid.uuid4(), workflow_id=workflow_id, status="running", input={})
    second = WorkflowExecution(id=uuid.uuid4(), workflow_id=workflow_id, status="completed", input={})
    session = _ExecSession(rows=[first, second])
    service = ExecutionService(session)

    rows = await service.list_executions(workflow_id=workflow_id, status="completed", limit=5, offset=2)

    assert rows == [first, second]
    stmt_text = str(session.last_statement)
    assert "WHERE workflow_executions.workflow_id =" in stmt_text
    assert "workflow_executions.status =" in stmt_text
    assert "ORDER BY workflow_executions.created_at DESC" in stmt_text
    assert "LIMIT :param_1" in stmt_text
    assert "OFFSET :param_2" in stmt_text


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
    stmt_text = str(service.db.last_statement)
    assert "execution_events" in stmt_text
    assert "execution_events.execution_id =" in stmt_text
    assert "ORDER BY execution_events.created_at ASC" in stmt_text
