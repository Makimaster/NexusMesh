"""M7 业务服务层单元测试（纯逻辑，fake session / mock coordinator）。"""

from app.core.exceptions import NexusMeshException, ValidationError
from app.schemas.agent import AgentRequest, AgentUpdateRequest
from app.schemas.workflow import TriggerRequest, WorkflowRequest, WorkflowUpdateRequest


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
