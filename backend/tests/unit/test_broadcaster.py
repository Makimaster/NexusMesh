import asyncio

import pytest


class _DummyTask:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None

        return _done().__await__()


class _DummyPubSub:
    def __init__(self, messages=None) -> None:
        self.messages = messages or []
        self.psubscribe_calls = []
        self.punsubscribe_calls = 0

    async def psubscribe(self, pattern: str) -> None:
        self.psubscribe_calls.append(pattern)

    async def punsubscribe(self) -> None:
        self.punsubscribe_calls += 1

    async def listen(self):
        for message in self.messages:
            yield message


class _DummyRedis:
    def __init__(self, pubsubs) -> None:
        self.pubsubs = list(pubsubs)
        self.pubsub_calls = 0

    def pubsub(self):
        pubsub = self.pubsubs[self.pubsub_calls]
        self.pubsub_calls += 1
        return pubsub


class _DummyWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent = []

    async def send_text(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(text)


def test_get_redis_instance_importable():
    from app.common.redis_client import get_redis_instance

    assert callable(get_redis_instance)


def test_extract_valid_channel():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:execution:exec-123:events") == "exec-123"


def test_extract_uuid_channel():
    from app.websocket.broadcaster import broadcaster

    assert (
        broadcaster._extract_execution_id(
            "channel:execution:550e8400-e29b-41d4-a716-446655440000:events"
        )
        == "550e8400-e29b-41d4-a716-446655440000"
    )


def test_extract_empty_execution_id_returns_none():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:execution::events") is None


def test_extract_bad_format_returns_none():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:wrong:exec-123:events") is None


def test_extract_too_many_parts_returns_none():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:execution:exec-123:events:extra") is None


@pytest.mark.asyncio
async def test_start_when_already_started_does_not_replace_resources(monkeypatch):
    from app.websocket.broadcaster import Broadcaster

    first_pubsub = _DummyPubSub()
    second_pubsub = _DummyPubSub()
    redis = _DummyRedis([first_pubsub, second_pubsub])
    created_tasks = []

    def fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    broadcaster = Broadcaster()
    await broadcaster.start(redis)
    first_task = broadcaster._task

    await broadcaster.start(redis)

    assert redis.pubsub_calls == 1
    assert broadcaster._pubsub is first_pubsub
    assert broadcaster._task is first_task
    assert len(created_tasks) == 1


@pytest.mark.asyncio
async def test_listen_loop_removes_websocket_after_send_failure():
    from app.websocket.broadcaster import Broadcaster

    channel = "channel:execution:exec-123:events"
    pubsub = _DummyPubSub(
        [{"type": "pmessage", "channel": channel, "data": "payload"}]
    )
    broadcaster = Broadcaster()
    broadcaster._pubsub = pubsub
    bad_ws = _DummyWebSocket(fail=True)

    await broadcaster.subscribe(channel, bad_ws)
    await broadcaster._listen_loop()

    assert channel not in broadcaster._channels or bad_ws not in broadcaster._channels[channel]
