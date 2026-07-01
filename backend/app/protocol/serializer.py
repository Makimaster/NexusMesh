"""五阶段协议事件的扁平 payload 序列化器。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.protocol.events import _PAYLOAD_CLS_MAP, EventType, ProtocolEvent
from app.protocol.stages import ProtocolStage

_ENVELOPE_KEYS = frozenset({"protocol_stage", "event_type", "created_at"})


def to_payload(event: ProtocolEvent) -> dict[str, Any]:
    """将协议事件序列化为协议传输用的扁平 dict。"""
    return {
        "protocol_stage": event.protocol_stage.value,
        "event_type": event.event_type.value,
        "created_at": event.created_at.isoformat(),
        **event.payload.model_dump(),
    }


def from_payload(data: dict[str, Any]) -> ProtocolEvent:
    """从协议传输 payload 还原协议事件。"""
    stage = ProtocolStage(data["protocol_stage"])
    event_type = EventType(data["event_type"])
    created_at = datetime.fromisoformat(data["created_at"])
    payload_cls = _PAYLOAD_CLS_MAP[stage]
    payload_data = {
        key: value for key, value in data.items() if key not in _ENVELOPE_KEYS
    }
    payload = payload_cls(**payload_data)

    return ProtocolEvent(
        protocol_stage=stage,
        event_type=event_type,
        payload=payload,
        created_at=created_at,
    )
