import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas.agent import AgentListItem, AgentResponse
from app.schemas.execution import (
    ExecutionAcceptedResponse,
    ExecutionListItem,
    ExecutionResponse,
    TimelineEventResponse,
)
from app.schemas.workflow import WorkflowListItem, WorkflowResponse


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_agent_list_item_strips_heavy_fields() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        name="a1",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
        system_prompt="secret",
        config={"k": "v"},
        created_at=_now(),
        is_active=True,
    )
    item = AgentListItem.model_validate(orm)
    dumped = item.model_dump()
    assert "system_prompt" not in dumped
    assert "config" not in dumped
    assert "is_active" not in dumped
    assert dumped["llm_model"] == "gpt-4o"


def test_agent_response_includes_heavy_fields() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        name="a1",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
        system_prompt="secret",
        config={"k": "v"},
        created_at=_now(),
    )
    resp = AgentResponse.model_validate(orm)
    assert resp.system_prompt == "secret"
    assert resp.config == {"k": "v"}


def test_workflow_list_item_strips_topology() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        name="w1",
        description=None,
        topology={"nodes": [1, 2, 3]},
        created_at=_now(),
    )
    item = WorkflowListItem.model_validate(orm)
    assert "topology" not in item.model_dump()


def test_workflow_response_includes_topology() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        name="w1",
        description="d",
        topology={"nodes": []},
        created_at=_now(),
    )
    resp = WorkflowResponse.model_validate(orm)
    assert resp.topology == {"nodes": []}


def test_execution_response_and_nullable_workflow_id() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_id=None,
        status="running",
        created_at=_now(),
        started_at=None,
        finished_at=None,
        input={"q": 1},
        output=None,
        error=None,
    )
    resp = ExecutionResponse.model_validate(orm)
    assert resp.workflow_id is None
    assert resp.input == {"q": 1}


def test_execution_accepted_response_only_id() -> None:
    eid = uuid.uuid4()
    resp = ExecutionAcceptedResponse(execution_id=eid)
    assert resp.model_dump() == {"execution_id": eid}


def test_timeline_event_nullable_execution_id() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        execution_id=None,
        protocol_stage="INIT",
        event_type="created",
        payload={},
        created_at=_now(),
    )
    ev = TimelineEventResponse.model_validate(orm)
    assert ev.execution_id is None
    assert ev.protocol_stage == "INIT"
