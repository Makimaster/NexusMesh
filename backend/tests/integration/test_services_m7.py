"""M7 业务服务层集成测试（真实 PG）。

前置：PostgreSQL 测试库可连接且已迁移。环境未就绪自动 skip。
"""

import uuid

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.user import User
from app.schemas.agent import AgentRequest
from app.schemas.workflow import WorkflowRequest
from app.services.agent_service import AgentService
from app.services.workflow_service import WorkflowService


async def _pg_available() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


async def _seed_user(session, user_id: uuid.UUID) -> None:
    session.add(
        User(
            id=user_id,
            email=f"{user_id}@example.com",
            username=f"user-{user_id.hex[:12]}",
            hashed_password="integration-test",
            role="developer",
            is_active=True,
        )
    )
    await session.flush()


@pytest.fixture
async def db_session():
    if not await _pg_available():
        pytest.skip("PostgreSQL 未就绪，跳过 M7 集成测试")
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def test_agent_soft_delete_hidden_from_list(db_session):
    creator = uuid.uuid4()
    await _seed_user(db_session, creator)
    service = AgentService(db_session)
    req = AgentRequest(
        name=f"it-agent-{uuid.uuid4()}",
        agent_type="assistant",
        llm_provider="openai",
        llm_model="gpt-4o",
    )
    agent = await service.create_agent(req, created_by=creator)
    await db_session.flush()
    aid = agent.id

    await service.delete_agent(aid)

    with pytest.raises(NotFoundError):
        await service.get_agent_detail(aid)
    raw = await db_session.get(Agent, aid)
    assert raw is not None
    assert raw.is_active is False


async def test_create_workflow_rejects_missing_agent(db_session):
    service = WorkflowService(db_session, coordinator=None)
    ghost = str(uuid.uuid4())
    req = WorkflowRequest(
        name=f"it-wf-{uuid.uuid4()}",
        topology={
            "nodes": [{"id": "n1", "type": "agent", "data": {"agent_id": ghost}}],
            "edges": [],
        },
    )
    with pytest.raises(ValidationError):
        await service.create_workflow(req, created_by=uuid.uuid4())


async def test_create_workflow_happy_path(db_session):
    creator = uuid.uuid4()
    await _seed_user(db_session, creator)
    agent_service = AgentService(db_session)
    agent = await agent_service.create_agent(
        AgentRequest(
            name=f"it-agent-{uuid.uuid4()}",
            agent_type="assistant",
            llm_provider="openai",
            llm_model="gpt-4o",
        ),
        created_by=creator,
    )
    await db_session.flush()

    wf_service = WorkflowService(db_session, coordinator=None)
    req = WorkflowRequest(
        name=f"it-wf-{uuid.uuid4()}",
        topology={
            "nodes": [
                {"id": "n1", "type": "agent", "data": {"agent_id": str(agent.id)}}
            ],
            "edges": [],
        },
    )
    workflow = await wf_service.create_workflow(req, created_by=creator)
    assert workflow.is_active is True
    assert workflow.created_by == creator
