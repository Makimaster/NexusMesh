"""五阶段协议事件类型枚举与分阶段 payload 模型。"""
from __future__ import annotations

from datetime import UTC, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.protocol.stages import ProtocolStage


class EventType(str, Enum):
    """标准 Agent 事件类型。继承 str 以支持 JSON 序列化。"""

    AGENT_SPAWN = "agent_spawn"
    AGENT_CALL = "agent_call"
    AGENT_FINISH = "agent_finish"
    AGENT_REFLECT = "agent_reflect"


class _ProtocolPayload(BaseModel):
    """协议 payload 基类：拒绝未知字段，避免静默吞掉协议漂移。"""

    model_config = ConfigDict(extra="forbid")


class InitPayload(_ProtocolPayload):
    """INIT 阶段：建立 Agent 上下文。"""

    agent_id: str
    workflow_id: str


class ReceivePayload(_ProtocolPayload):
    """RECEIVE 阶段：接收任务输入。"""

    task_input: dict


class RoutePayload(_ProtocolPayload):
    """ROUTE 阶段：多跳路由决策。"""

    next_agent_id: str | None = None
    routing_reason: str | None = None


class ExecutePayload(_ProtocolPayload):
    """EXECUTE 阶段：LLM 调用结果，对齐设计文档 §8.3。"""

    agent_message: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    model_cost_usd: float


class FinishPayload(_ProtocolPayload):
    """FINISH 阶段：写入执行记录。"""

    success: bool
    output: dict | None = None


_PAYLOAD_CLS_MAP: dict[ProtocolStage, type[BaseModel]] = {
    ProtocolStage.INIT: InitPayload,
    ProtocolStage.RECEIVE: ReceivePayload,
    ProtocolStage.ROUTE: RoutePayload,
    ProtocolStage.EXECUTE: ExecutePayload,
    ProtocolStage.FINISH: FinishPayload,
}


class ProtocolEvent(BaseModel):
    """五阶段协议统一信封。

    payload 必须是与 protocol_stage 匹配的具体 payload 模型实例；
    传错类型时 model_validator 抛 ValidationError，Fail-Fast。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    protocol_stage: ProtocolStage
    event_type: EventType
    payload: Any
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)  # noqa: UP017
    )

    @field_validator("created_at", mode="after")
    @classmethod
    def _normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check_payload_matches_stage(self) -> ProtocolEvent:
        expected_cls = _PAYLOAD_CLS_MAP[self.protocol_stage]
        if not isinstance(self.payload, expected_cls):
            raise ValueError(
                f"stage {self.protocol_stage.value} 的 payload 必须是"
                f" {expected_cls.__name__}，实际传入 {type(self.payload).__name__}"
            )
        return self
