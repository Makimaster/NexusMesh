import uuid
from datetime import UTC, datetime
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
    return datetime.now(UTC)


def test_agent_list_item_strips_heavy_fields() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        name="a1",
        description="desc",
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
    assert dumped["description"] == "desc"
    assert dumped["llm_model"] == "gpt-4o"


def test_agent_response_includes_heavy_fields() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        name="a1",
        description="desc",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
        system_prompt="secret",
        config={"k": "v"},
        created_at=_now(),
    )
    resp = AgentResponse.model_validate(orm)
    assert resp.description == "desc"
    assert resp.system_prompt == "secret"
    assert resp.config == {"k": "v"}


def test_execution_list_item_strips_detail_fields() -> None:
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        status="succeeded",
        created_at=_now(),
        started_at=_now(),
        finished_at=_now(),
        input={"q": 1},
        output={"answer": 2},
        error="ignored",
    )
    item = ExecutionListItem.model_validate(orm)
    dumped = item.model_dump()
    assert "input" not in dumped
    assert "output" not in dumped
    assert "error" not in dumped


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
