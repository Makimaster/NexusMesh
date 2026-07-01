"""五阶段协议公共 API。

外部模块应从此处导入，而非直接引用子模块：
    from app.protocol import ProtocolEvent, ProtocolStage, EventType, to_payload, from_payload
"""
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

__all__ = [
    "EventType",
    "ExecutePayload",
    "FinishPayload",
    "from_payload",
    "InitPayload",
    "ProtocolEvent",
    "ProtocolStage",
    "ReceivePayload",
    "RoutePayload",
    "to_payload",
]
