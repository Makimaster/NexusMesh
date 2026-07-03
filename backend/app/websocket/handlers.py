from __future__ import annotations

import uuid

from fastapi import WebSocket

from app.state_manager.keys import get_channel_events
from app.state_manager.session import SessionManager
from app.websocket.broadcaster import broadcaster


async def on_connect(
    ws: WebSocket,
    execution_id: str,
    user_id: str,
    session_mgr: SessionManager,
) -> str:
    await ws.accept()
    session_id = str(uuid.uuid4())
    channel = get_channel_events(execution_id)
    await session_mgr.create(session_id, user_id, execution_id)
    await broadcaster.subscribe(channel, ws)
    return session_id


async def on_disconnect(
    session_id: str,
    execution_id: str,
    ws: WebSocket,
    session_mgr: SessionManager,
) -> None:
    channel = get_channel_events(execution_id)
    await broadcaster.unsubscribe(channel, ws)
    await session_mgr.delete(session_id)
