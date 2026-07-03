from __future__ import annotations

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)

from app.common.redis_client import get_redis_instance
from app.core.security import verify_token
from app.state_manager.session import SessionManager
from app.websocket.handlers import on_connect, on_disconnect

router = APIRouter()


@router.websocket("/ws/executions/{execution_id}")
async def websocket_endpoint(websocket: WebSocket, execution_id: str) -> None:
    token = websocket.query_params.get("token")
    try:
        payload = verify_token(token)
        if payload.get("type") != "access":
            raise ValueError("invalid token type")
    except Exception as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid websocket token",
        ) from exc

    user_id = payload["sub"]
    await _handle_connection(websocket, execution_id, user_id)


async def _handle_connection(
    websocket: WebSocket, execution_id: str, user_id: str
) -> None:
    redis = await get_redis_instance()
    session_mgr = SessionManager(redis)
    session_id = await on_connect(websocket, execution_id, user_id, session_mgr)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await on_disconnect(session_id, execution_id, websocket, session_mgr)
