"""五阶段协议事件类型枚举与分阶段 payload 模型。"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.protocol.stages import ProtocolStage


class EventType(str, Enum):
    """标准 Agent 事件类型。继承 str 以支持 JSON 序列化。"""

    AGENT_SPAWN = "agent_spawn"
    AGENT_CALL = "agent_call"
    AGENT_FINISH = "agent_finish"
    AGENT_REFLECT = "agent_reflect"


class InitPayload(BaseModel):
    """INIT 阶段：建立 Agent 上下文。"""

    agent_id: str
    workflow_id: str


class ReceivePayload(BaseModel):
    """RECEIVE 阶段：接收任务输入。"""

    task_input: dict


class RoutePayload(BaseModel):
    """ROUTE 阶段：多跳路由决策。"""

    next_agent_id: str | None = None
    routing_reason: str | None = None


class ExecutePayload(BaseModel):
    """EXECUTE 阶段：LLM 调用结果，对齐设计文档 §8.3。"""

    agent_message: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    model_cost_usd: float


class FinishPayload(BaseModel):
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
