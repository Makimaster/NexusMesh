"""M2 五阶段协议单测。"""
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
