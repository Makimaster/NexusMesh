"""Redis 键名与 Pub/Sub channel 参数化函数。

M3 内部和 M4 WebSocket 网关均从此处 import，
杜绝跨模块字符串漂移。
"""


def get_agent_context_key(execution_id: str, agent_id: str) -> str:
    return f"agent_context:{execution_id}:{agent_id}"


def get_session_key(session_id: str) -> str:
    return f"session:{session_id}"


def get_task_state_key(execution_id: str) -> str:
    return f"task_state:{execution_id}"


def get_channel_status(execution_id: str) -> str:
    return f"channel:execution:{execution_id}:status"


def get_channel_events(execution_id: str) -> str:
    return f"channel:execution:{execution_id}:events"
