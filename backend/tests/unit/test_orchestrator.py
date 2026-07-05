"""M6 Orchestrator 单元测试。"""

import json

from app.orchestrator.router import AgentRouter
from app.protocol import (
    EventType,
    InitPayload,
    ProtocolEvent,
    ProtocolStage,
    to_payload,
)
from app.state_manager.keys import get_channel_events


def _topology_double():
    return {
        "nodes": [
            {"id": "node-1", "type": "agent", "data": {"agent_id": "aaaaaaaa-0000-0000-0000-000000000001"}},
            {"id": "node-2", "type": "agent", "data": {"agent_id": "aaaaaaaa-0000-0000-0000-000000000002"}},
        ],
        "edges": [
            {"id": "edge-1", "source": "node-1", "target": "node-2", "data": {"condition": "default"}},
        ],
    }


def test_router_entry_node():
    router = AgentRouter()

    decision = router.route_next(None, _topology_double())

    assert decision.next_node_id == "node-1"
    assert decision.next_agent_id == "aaaaaaaa-0000-0000-0000-000000000001"


def test_router_static_next_node():
    router = AgentRouter()

    decision = router.route_next("node-1", _topology_double())

    assert decision.next_node_id == "node-2"
    assert decision.next_agent_id == "aaaaaaaa-0000-0000-0000-000000000002"


def test_router_leaf_returns_none():
    router = AgentRouter()

    decision = router.route_next("node-2", _topology_double())

    assert decision.next_node_id is None
    assert decision.next_agent_id is None


def test_router_single_node_entry_then_leaf():
    topo = {
        "nodes": [{"id": "solo", "type": "agent", "data": {"agent_id": "bbbbbbbb-0000-0000-0000-000000000001"}}],
        "edges": [],
    }
    router = AgentRouter()

    entry = router.route_next(None, topo)
    leaf = router.route_next("solo", topo)

    assert entry.next_node_id == "solo"
    assert entry.next_agent_id == "bbbbbbbb-0000-0000-0000-000000000001"
    assert leaf.next_node_id is None
    assert leaf.next_agent_id is None


class _DummyRedisPublisher:
    def __init__(self) -> None:
        self.calls = []

    async def publish(self, channel: str, data: str) -> None:
        self.calls.append((channel, data))


class _DummySession:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0
        self.begin_calls = 0
        self.begin_entries = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        session = self

        class _BeginContext:
            async def __aenter__(self_inner):
                session.begin_entries += 1
                return session

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        self.begin_calls += 1
        return _BeginContext()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _make_init_event() -> ProtocolEvent:
    return ProtocolEvent(
        protocol_stage=ProtocolStage.INIT,
        event_type=EventType.AGENT_SPAWN,
        payload=InitPayload(agent_id="agent-001", workflow_id="wf-001"),
    )


async def test_emit_event_publishes_and_persists(monkeypatch):
    from app.orchestrator.event_emitter import EventEmitter

    execution_id = "550e8400-e29b-41d4-a716-446655440000"
    event = _make_init_event()
    redis = _DummyRedisPublisher()
    session = _DummySession()

    monkeypatch.setattr(
        "app.orchestrator.event_emitter.AsyncSessionLocal",
        lambda: session,
    )

    emitter = EventEmitter(redis)

    await emitter.emit_event(execution_id, event)

    payload = to_payload(event)
    assert redis.calls == [
        (get_channel_events(execution_id), json.dumps(payload))
    ]
    assert len(session.added) == 1
    saved = session.added[0]
    assert str(saved.execution_id) == execution_id
    assert saved.protocol_stage == event.protocol_stage.value
    assert saved.event_type == event.event_type.value
    assert saved.payload == payload
    assert session.begin_calls == 1
    assert session.begin_entries == 1
    assert session.commits == 0


async def test_emit_token_publishes_only_no_persist(monkeypatch):
    from app.orchestrator.event_emitter import EventEmitter

    execution_id = "550e8400-e29b-41d4-a716-446655440000"
    redis = _DummyRedisPublisher()
    emitter = EventEmitter(redis)
    persist_calls = 0

    async def fake_persist(*args, **kwargs):
        nonlocal persist_calls
        persist_calls += 1

    monkeypatch.setattr(emitter, "_persist", fake_persist)

    await emitter.emit_token(execution_id, "agent-001", "hello", reasoning=True)

    assert persist_calls == 0
    assert redis.calls == [
        (
            get_channel_events(execution_id),
            json.dumps(
                {
                    "event_type": "agent_chunk_stream",
                    "agent_id": "agent-001",
                    "text": "hello",
                    "reasoning": True,
                }
            ),
        )
    ]


async def test_emit_event_persist_failsafe(monkeypatch):
    from app.orchestrator.event_emitter import EventEmitter

    execution_id = "550e8400-e29b-41d4-a716-446655440000"
    event = _make_init_event()
    redis = _DummyRedisPublisher()
    emitter = EventEmitter(redis)
    critical_calls = []

    async def fake_persist(*args, **kwargs):
        raise RuntimeError("db down")

    def fake_critical(message, *args):
        critical_calls.append(message % args)

    monkeypatch.setattr(emitter, "_persist", fake_persist)
    monkeypatch.setattr("app.orchestrator.event_emitter.log.critical", fake_critical)

    await emitter.emit_event(execution_id, event)

    assert redis.calls == [
        (get_channel_events(execution_id), json.dumps(to_payload(event)))
    ]
    assert len(critical_calls) == 1
    assert "db down" in critical_calls[0]
