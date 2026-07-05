"""M6 Orchestrator 单元测试。"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestrator.base_agent import BaseAgent
from app.orchestrator.router import AgentRouter
from app.protocol import (
    EventType,
    ExecutePayload,
    InitPayload,
    ProtocolEvent,
    ProtocolStage,
    to_payload,
)
from app.services.llm_schemas import LLMStreamChunk, UsageStats
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


def _fake_stream(chunks):
    async def _generator():
        for chunk in chunks:
            yield chunk

    return _generator()


async def test_base_agent_accumulates_tokens_and_usage():
    llm = MagicMock()
    llm.stream_completion = MagicMock(
        return_value=_fake_stream(
            [
                LLMStreamChunk(token="Hello"),
                LLMStreamChunk(token=" world"),
                LLMStreamChunk(
                    usage=UsageStats(
                        prompt_tokens=11,
                        completion_tokens=22,
                        total_tokens=33,
                        model_cost_usd=0.44,
                    )
                ),
            ]
        )
    )
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()
    agent = BaseAgent(
        agent_id="agent-001",
        llm_model="gpt-test",
        system_prompt="You are helpful.",
        llm_service=llm,
        emitter=emitter,
    )

    payload = await agent.run("exec-001", {"query": "Say hi"})

    assert payload == ExecutePayload(
        agent_message="Hello world",
        prompt_tokens=11,
        completion_tokens=22,
        model="gpt-test",
        model_cost_usd=0.44,
    )
    llm.stream_completion.assert_called_once_with(
        messages=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Say hi"},
        ],
        model="gpt-test",
    )


async def test_base_agent_emits_token_stream():
    llm = MagicMock()
    llm.stream_completion = MagicMock(
        return_value=_fake_stream([LLMStreamChunk(token="A"), LLMStreamChunk(token="B")])
    )
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()
    agent = BaseAgent(
        agent_id="agent-001",
        llm_model="gpt-test",
        system_prompt=None,
        llm_service=llm,
        emitter=emitter,
    )

    await agent.run("exec-002", {"query": 123})

    assert emitter.emit_token.await_count == 2
    emitter.emit_token.assert_any_await("exec-002", "agent-001", "A")
    emitter.emit_token.assert_any_await("exec-002", "agent-001", "B")
    llm.stream_completion.assert_called_once_with(
        messages=[{"role": "user", "content": "123"}],
        model="gpt-test",
    )


async def test_base_agent_no_usage_tail_fallback():
    llm = MagicMock()
    llm.stream_completion = MagicMock(
        return_value=_fake_stream([LLMStreamChunk(token="Only text")])
    )
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()
    agent = BaseAgent(
        agent_id="agent-002",
        llm_model="gpt-test",
        system_prompt=None,
        llm_service=llm,
        emitter=emitter,
    )

    payload = await agent.run("exec-003", {})

    assert payload == ExecutePayload(
        agent_message="Only text",
        prompt_tokens=0,
        completion_tokens=0,
        model="gpt-test",
        model_cost_usd=0.0,
    )
    llm.stream_completion.assert_called_once_with(
        messages=[{"role": "user", "content": ""}],
        model="gpt-test",
    )


async def test_base_agent_emits_reasoning_content():
    llm = MagicMock()
    llm.stream_completion = MagicMock(
        return_value=_fake_stream(
            [
                LLMStreamChunk(reasoning_content="thinking"),
                LLMStreamChunk(token="final"),
            ]
        )
    )
    emitter = MagicMock()
    emitter.emit_token = AsyncMock()
    agent = BaseAgent(
        agent_id="agent-003",
        llm_model="gpt-test",
        system_prompt="",
        llm_service=llm,
        emitter=emitter,
    )

    payload = await agent.run("exec-004", {"query": "Q"})

    assert payload.agent_message == "final"
    emitter.emit_token.assert_any_await(
        "exec-004",
        "agent-003",
        "thinking",
        reasoning=True,
    )
    emitter.emit_token.assert_any_await("exec-004", "agent-003", "final")


async def test_scheduler_load_agent_builds_base_agent(monkeypatch):
    from app.orchestrator.event_emitter import EventEmitter
    from app.orchestrator.scheduler import Scheduler
    from app.services.llm_service import LLMService

    agent_id = "550e8400-e29b-41d4-a716-446655440010"
    agent_row = MagicMock(llm_model="gpt-4o-mini", system_prompt="You are scheduler")
    session = MagicMock()
    session.get = AsyncMock(return_value=agent_row)

    @asynccontextmanager
    async def fake_session_local():
        yield session

    monkeypatch.setattr("app.orchestrator.scheduler.AsyncSessionLocal", fake_session_local)

    llm = MagicMock(spec=LLMService)
    emitter = MagicMock(spec=EventEmitter)
    scheduler = Scheduler(llm, emitter)

    agent = await scheduler.load_agent(agent_id)

    assert isinstance(agent, BaseAgent)
    assert agent._agent_id == agent_id
    assert agent._llm_model == "gpt-4o-mini"
    assert agent._system_prompt == "You are scheduler"
    assert agent._llm is llm
    assert agent._emitter is emitter


async def test_scheduler_load_agent_missing_fails_fast(monkeypatch):
    from app.orchestrator.scheduler import Scheduler
    from app.orchestrator.exceptions import OrchestratorError

    agent_id = "550e8400-e29b-41d4-a716-446655440011"
    session = MagicMock()
    session.get = AsyncMock(return_value=None)

    @asynccontextmanager
    async def fake_session_local():
        yield session

    monkeypatch.setattr("app.orchestrator.scheduler.AsyncSessionLocal", fake_session_local)

    scheduler = Scheduler(MagicMock(), MagicMock())

    with pytest.raises(OrchestratorError, match=f"Agent 不存在: {agent_id}"):
        await scheduler.load_agent(agent_id)


async def test_scheduler_load_agent_invalid_uuid_fails_fast():
    from app.orchestrator.scheduler import Scheduler
    from app.orchestrator.exceptions import OrchestratorError

    scheduler = Scheduler(MagicMock(), MagicMock())

    with pytest.raises(OrchestratorError, match="agent_id 非法 UUID: not-a-uuid"):
        await scheduler.load_agent("not-a-uuid")


async def test_scheduler_load_execution_context(monkeypatch):
    from app.orchestrator.scheduler import ExecutionContext, Scheduler

    execution_id = "550e8400-e29b-41d4-a716-446655440020"
    workflow_id = "550e8400-e29b-41d4-a716-446655440021"
    exec_row = MagicMock(workflow_id=workflow_id, input={"query": "hello"})
    wf_row = MagicMock(topology={"nodes": [{"id": "n1"}], "edges": []})
    session = MagicMock()
    session.get = AsyncMock(side_effect=[exec_row, wf_row])

    @asynccontextmanager
    async def fake_session_local():
        yield session

    monkeypatch.setattr("app.orchestrator.scheduler.AsyncSessionLocal", fake_session_local)

    scheduler = Scheduler(MagicMock(), MagicMock())

    context = await scheduler.load_execution_context(execution_id)

    assert context == ExecutionContext(
        workflow_id=workflow_id,
        topology={"nodes": [{"id": "n1"}], "edges": []},
        task_input={"query": "hello"},
    )


async def test_scheduler_load_execution_context_missing_execution(monkeypatch):
    from app.orchestrator.scheduler import Scheduler
    from app.orchestrator.exceptions import OrchestratorError

    execution_id = "550e8400-e29b-41d4-a716-446655440022"
    session = MagicMock()
    session.get = AsyncMock(return_value=None)

    @asynccontextmanager
    async def fake_session_local():
        yield session

    monkeypatch.setattr("app.orchestrator.scheduler.AsyncSessionLocal", fake_session_local)

    scheduler = Scheduler(MagicMock(), MagicMock())

    with pytest.raises(OrchestratorError, match=f"执行实例不存在: {execution_id}"):
        await scheduler.load_execution_context(execution_id)


async def test_scheduler_settle_execution_updates_status(monkeypatch):
    from app.orchestrator.scheduler import Scheduler

    execution_id = "550e8400-e29b-41d4-a716-446655440023"
    exec_row = MagicMock(status="running", output=None, error=None)
    session = MagicMock()
    session.get = AsyncMock(return_value=exec_row)

    @asynccontextmanager
    async def fake_begin():
        yield session

    session.begin.return_value = fake_begin()

    @asynccontextmanager
    async def fake_session_local():
        yield session

    monkeypatch.setattr("app.orchestrator.scheduler.AsyncSessionLocal", fake_session_local)

    scheduler = Scheduler(MagicMock(), MagicMock())

    await scheduler.settle_execution(
        execution_id,
        "succeeded",
        output={"answer": "done"},
        error="",
    )

    assert exec_row.status == "succeeded"
    assert exec_row.output == {"answer": "done"}
    assert exec_row.error == ""
    session.begin.assert_called_once_with()
