"""M2 五阶段协议单测。"""
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.protocol.events import (
    EventType,
    ExecutePayload,
    FinishPayload,
    InitPayload,
    ProtocolEvent,
    ReceivePayload,
    RoutePayload,
)
from app.protocol.serializer import from_payload, to_payload
from app.protocol.stages import ProtocolStage


def _assert_flat_payload_shape(data):
    assert "protocol_stage" in data
    assert "event_type" in data
    assert "created_at" in data
    assert "payload" not in data


def test_protocol_stage_values():
    assert ProtocolStage.INIT.value == "INIT"
    assert ProtocolStage.RECEIVE.value == "RECEIVE"
    assert ProtocolStage.ROUTE.value == "ROUTE"
    assert ProtocolStage.EXECUTE.value == "EXECUTE"
    assert ProtocolStage.FINISH.value == "FINISH"


def test_protocol_stage_from_string():
    """str 子类特性：可从字符串构造枚举成员。"""
    assert ProtocolStage("EXECUTE") == ProtocolStage.EXECUTE


def test_event_type_values():
    assert EventType.AGENT_SPAWN.value == "agent_spawn"
    assert EventType.AGENT_CALL.value == "agent_call"
    assert EventType.AGENT_FINISH.value == "agent_finish"
    assert EventType.AGENT_REFLECT.value == "agent_reflect"


def test_event_type_from_string():
    assert EventType("agent_spawn") == EventType.AGENT_SPAWN


def test_invalid_event_type_raises():
    with pytest.raises(ValueError):
        EventType("not_a_valid_type")


def test_init_payload_valid():
    p = InitPayload(agent_id="agent-001", workflow_id="wf-001")
    assert p.agent_id == "agent-001"
    assert p.workflow_id == "wf-001"


def test_receive_payload_valid():
    p = ReceivePayload(task_input={"query": "hello world"})
    assert p.task_input["query"] == "hello world"


def test_route_payload_defaults():
    p = RoutePayload()
    assert p.next_agent_id is None
    assert p.routing_reason is None


def test_route_payload_with_values():
    p = RoutePayload(next_agent_id="agent-002", routing_reason="需要专业工具")
    assert p.next_agent_id == "agent-002"


def test_execute_payload_valid():
    p = ExecutePayload(
        agent_message="任务完成",
        prompt_tokens=512,
        completion_tokens=128,
        model="gpt-4o",
        model_cost_usd=0.0032,
    )
    assert p.model == "gpt-4o"
    assert p.prompt_tokens == 512
    assert p.model_cost_usd == 0.0032


def test_execute_payload_missing_required_raises():
    with pytest.raises(ValidationError):
        ExecutePayload(agent_message="缺少 token 字段")


def test_finish_payload_success():
    p = FinishPayload(success=True, output={"result": "完成"})
    assert p.success is True
    assert p.output == {"result": "完成"}


def test_finish_payload_no_output():
    p = FinishPayload(success=False)
    assert p.output is None


def test_protocol_event_valid():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.EXECUTE,
        event_type=EventType.AGENT_FINISH,
        payload=ExecutePayload(
            agent_message="完成",
            prompt_tokens=100,
            completion_tokens=50,
            model="gpt-4o",
            model_cost_usd=0.002,
        ),
    )
    assert event.protocol_stage == ProtocolStage.EXECUTE
    assert event.event_type == EventType.AGENT_FINISH
    assert isinstance(event.created_at, datetime)


def test_protocol_event_created_at_is_utc():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.INIT,
        event_type=EventType.AGENT_SPAWN,
        payload=InitPayload(agent_id="a1", workflow_id="w1"),
    )
    assert event.created_at.tzinfo is not None


def test_wrong_payload_type_raises():
    """INIT stage 但传入 EXECUTE payload → ValidationError。"""
    with pytest.raises(ValidationError):
        ProtocolEvent(
            protocol_stage=ProtocolStage.INIT,
            event_type=EventType.AGENT_SPAWN,
            payload=ExecutePayload(
                agent_message="错误的 payload",
                prompt_tokens=1,
                completion_tokens=1,
                model="gpt-4o",
                model_cost_usd=0.0,
            ),
        )


def test_execute_round_trip():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.EXECUTE,
        event_type=EventType.AGENT_CALL,
        payload=ExecutePayload(
            agent_message="已调用模型",
            prompt_tokens=120,
            completion_tokens=30,
            model="gpt-4o",
            model_cost_usd=0.0012,
        ),
    )

    assert from_payload(to_payload(event)) == event


def test_init_round_trip():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.INIT,
        event_type=EventType.AGENT_SPAWN,
        payload=InitPayload(agent_id="agent-001", workflow_id="wf-001"),
    )

    data = to_payload(event)

    _assert_flat_payload_shape(data)
    assert data["agent_id"] == "agent-001"
    assert data["workflow_id"] == "wf-001"
    assert from_payload(data) == event


def test_to_payload_execute_shape():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.EXECUTE,
        event_type=EventType.AGENT_FINISH,
        payload=ExecutePayload(
            agent_message="执行完成",
            prompt_tokens=300,
            completion_tokens=80,
            model="gpt-4o",
            model_cost_usd=0.004,
        ),
    )

    data = to_payload(event)

    assert data == {
        "protocol_stage": "EXECUTE",
        "event_type": "agent_finish",
        "created_at": event.created_at.isoformat(),
        "agent_message": "执行完成",
        "prompt_tokens": 300,
        "completion_tokens": 80,
        "model": "gpt-4o",
        "model_cost_usd": 0.004,
    }


def test_from_payload_invalid_execute_missing_field():
    data = {
        "protocol_stage": "EXECUTE",
        "event_type": "agent_call",
        "created_at": datetime.now(UTC).isoformat(),
        "agent_message": "缺少必填字段",
    }

    with pytest.raises(ValidationError):
        from_payload(data)


def test_from_payload_rejects_naive_created_at():
    data = {
        "protocol_stage": "INIT",
        "event_type": "agent_spawn",
        "created_at": "2026-07-01T12:00:00",
        "agent_id": "agent-001",
        "workflow_id": "wf-001",
    }

    with pytest.raises(ValueError, match="created_at"):
        from_payload(data)


def test_from_payload_normalizes_created_at_to_utc():
    event = from_payload(
        {
            "protocol_stage": "INIT",
            "event_type": "agent_spawn",
            "created_at": "2026-07-01T20:00:00+08:00",
            "agent_id": "agent-001",
            "workflow_id": "wf-001",
        }
    )

    assert event.created_at.tzinfo is UTC
    assert event.created_at == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_protocol_package_exports_public_api():
    from app.protocol import (
        EventType as PackageEventType,
    )
    from app.protocol import (
        ProtocolEvent as PackageProtocolEvent,
    )
    from app.protocol import (
        ProtocolStage as PackageProtocolStage,
    )
    from app.protocol import (
        from_payload as package_from_payload,
    )
    from app.protocol import (
        to_payload as package_to_payload,
    )

    assert PackageProtocolEvent is ProtocolEvent
    assert PackageProtocolStage is ProtocolStage
    assert PackageEventType is EventType
    assert callable(package_to_payload)
    assert callable(package_from_payload)


def test_receive_round_trip():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.RECEIVE,
        event_type=EventType.AGENT_CALL,
        payload=ReceivePayload(task_input={"query": "hello", "priority": "high"}),
    )

    data = to_payload(event)

    _assert_flat_payload_shape(data)
    assert data["task_input"] == {"query": "hello", "priority": "high"}
    assert from_payload(data) == event


def test_route_round_trip():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.ROUTE,
        event_type=EventType.AGENT_REFLECT,
        payload=RoutePayload(
            next_agent_id="agent-002",
            routing_reason="需要交给检索 Agent",
        ),
    )

    data = to_payload(event)

    _assert_flat_payload_shape(data)
    assert data["next_agent_id"] == "agent-002"
    assert data["routing_reason"] == "需要交给检索 Agent"
    assert from_payload(data) == event


def test_finish_round_trip():
    event = ProtocolEvent(
        protocol_stage=ProtocolStage.FINISH,
        event_type=EventType.AGENT_FINISH,
        payload=FinishPayload(success=True, output={"result": "完成"}),
    )

    data = to_payload(event)

    _assert_flat_payload_shape(data)
    assert data["success"] is True
    assert data["output"] == {"result": "完成"}
    assert from_payload(data) == event


def test_from_payload_invalid_stage():
    data = {
        "protocol_stage": "UNKNOWN",
        "event_type": "agent_call",
        "created_at": datetime.now(UTC).isoformat(),
    }

    with pytest.raises(ValueError):
        from_payload(data)
