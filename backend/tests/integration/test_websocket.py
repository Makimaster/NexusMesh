import threading
import time
import uuid

import pytest
import redis
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.common.redis_client import close_redis
from app.core.security import create_access_token
from app.main import app
from app.state_manager.keys import get_channel_events
from app.websocket.broadcaster import broadcaster


REDIS_URL = "redis://localhost:6379/0"


def _publish_message(channel: str, payload: str) -> None:
    client = redis.Redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        client.publish(channel, payload)
    finally:
        client.close()


@pytest.fixture
def websocket_test_cleanup():
    created_session_keys: set[str] = set()
    yield created_session_keys
    broadcaster._clear_for_test()
    redis_client = redis.Redis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        if created_session_keys:
            redis_client.delete(*created_session_keys)
    finally:
        redis_client.close()


def test_websocket_happy_path_receives_redis_frame(websocket_test_cleanup):
    execution_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    token = create_access_token({"sub": user_id})
    channel = get_channel_events(execution_id)
    payload = '{"event":"task.updated","execution_id":"%s"}' % execution_id

    with TestClient(app) as client:
        redis_client = redis.Redis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            before_keys = set(redis_client.keys("session:*"))
            with client.websocket_connect(
                f"/ws/executions/{execution_id}?token={token}"
            ) as websocket:
                deadline = time.time() + 2
                session_key = None
                while time.time() < deadline:
                    new_keys = set(redis_client.keys("session:*")) - before_keys
                    if new_keys:
                        session_key = new_keys.pop()
                        break
                    time.sleep(0.05)

                assert session_key is not None
                websocket_test_cleanup.add(session_key)

                publisher = threading.Thread(
                    target=_publish_message,
                    args=(channel, payload),
                    daemon=True,
                )
                publisher.start()
                assert websocket.receive_text() == payload
                publisher.join(timeout=1)
        finally:
            redis_client.close()


def test_websocket_auth_failure_invalid_token(websocket_test_cleanup):
    execution_id = str(uuid.uuid4())

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/ws/executions/{execution_id}?token=invalid-token"
            ):
                pass

    assert exc_info.value.code == 1008


def test_websocket_auth_failure_missing_token(websocket_test_cleanup):
    execution_id = str(uuid.uuid4())

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/executions/{execution_id}"):
                pass

    assert exc_info.value.code == 1008


@pytest.fixture(autouse=True)
def _close_shared_redis_after_test():
    yield
    import asyncio

    asyncio.run(close_redis())
