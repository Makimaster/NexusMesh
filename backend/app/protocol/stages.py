"""五阶段协议阶段枚举。"""
from enum import Enum


class ProtocolStage(str, Enum):
    """Agent 间通信协议的五个阶段。继承 str 以支持 JSON 序列化。"""

    INIT = "INIT"
    RECEIVE = "RECEIVE"
    ROUTE = "ROUTE"
    EXECUTE = "EXECUTE"
    FINISH = "FINISH"
