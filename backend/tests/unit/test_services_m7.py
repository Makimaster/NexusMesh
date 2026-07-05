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
