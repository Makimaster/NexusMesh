"""M2 五阶段协议单测。"""
from datetime import datetime, timezone

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
from app.protocol.stages import ProtocolStage


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
