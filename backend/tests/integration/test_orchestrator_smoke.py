"""M6 Orchestrator 集成 smoke test（真实 Redis + PG，mock M5）。

验证三个跨模块拼接契约（设计文档 §10.3）：
1. EventEmitter → PG：to_payload() 铺平的 dict 能否写进 ExecutionEvent.payload JSONB
2. BaseAgent → M5：消费贴近真实结构的 LLMStreamChunk 流
3. 后台协程 session 生命周期：AsyncSessionLocal 在非请求作用域下能否正常开关

前置条件（DoD 加分项）：
- Redis 在 localhost:6379 可访问（使用 DB 1，与开发 DB 0 隔离）
- PostgreSQL 测试库可连接且已迁移
环境未就绪时整个模块自动 skip，不阻塞主流程。
"""

import uuid

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.event import ExecutionEvent
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.orchestrator import Coordinator
from app.services.llm_schemas import LLMStreamChunk, UsageStats
from app.services.llm_service import LLMService

# 固定测试 UUID（便于精确清理）
WF_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
AGENT_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000002")
EXEC_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000003")


async def _pg_available() -> bool:
    try:
        async with engine.connect() as conn:  # noqa: F841
            return True
    except Exception:
        return False


async def _redis_available(url: str) -> bool:
    client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()


@pytest.fixture
async def redis_client():
    """真实 Redis DB 1（与开发 DB 0 隔离）。环境未就绪则 skip。"""
    url = "redis://localhost:6379/1"
    if not await _redis_available(url):
        pytest.skip("Redis 未就绪，跳过 M6 集成 smoke test")
    client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


async def _cleanup() -> None:
    """按固定 UUID 精确删除测试数据（UUID 列不能用 like）。"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                ExecutionEvent.__table__.delete().where(
                    ExecutionEvent.execution_id == EXEC_ID
                )
            )
            await session.execute(
                WorkflowExecution.__table__.delete().where(
                    WorkflowExecution.id == EXEC_ID
                )
            )
            await session.execute(
                Workflow.__table__.delete().where(Workflow.id == WF_ID)
            )
            await session.execute(Agent.__table__.delete().where(Agent.id == AGENT_ID))


@pytest.fixture
async def seeded_db():
    """在真实 PG 播种单 Agent 工作流数据；环境未就绪则 skip。测试后清理。"""
    if not await _pg_available():
        pytest.skip("PostgreSQL 未就绪，跳过 M6 集成 smoke test")

    await _cleanup()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add_all(
                [
                    Workflow(
                        id=WF_ID,
                        name="smoke-wf",
                        topology={
                            "nodes": [
                                {
                                    "id": "node-1",
                                    "type": "agent",
                                    "data": {"agent_id": str(AGENT_ID)},
                                }
                            ],
                            "edges": [],
                        },
                    ),
                    Agent(
                        id=AGENT_ID,
                        name="smoke-agent",
                        agent_type="assistant",
                        llm_provider="openai",
                        llm_model="gpt-4o",
                        system_prompt="you are helpful",
                    ),
                    WorkflowExecution(
                        id=EXEC_ID,
                        workflow_id=WF_ID,
                        status="pending",
                        input={"query": "hi"},
                    ),
                ]
            )
    yield
    await _cleanup()


def _fake_stream_completion(*args, **kwargs):
    """Mock M5：贴近真实的流式帧（token 帧 + 尾帧 usage）。"""

    async def _gen():
        yield LLMStreamChunk(token="Hello")
        yield LLMStreamChunk(token=" world")
        yield LLMStreamChunk(
            usage=UsageStats(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                model_cost_usd=0.0001,
            )
        )

    return _gen()


async def test_orchestrator_smoke_single_agent(redis_client, seeded_db):
    """单 Agent 拓扑跑完整五阶段，验证三个拼接契约。"""
    # mock LLMService，绕过 __init__（不触发 litellm 副作用）
    llm = LLMService.__new__(LLMService)
    llm.stream_completion = _fake_stream_completion

    coord = Coordinator(redis_client, llm)
    await coord._execute_workflow_loop(str(EXEC_ID))

    async with AsyncSessionLocal() as session:
        # 契约 1：EventEmitter → PG，事件按序落库
        result = await session.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == EXEC_ID)
            .order_by(ExecutionEvent.created_at)
        )
        events = result.scalars().all()
        stages = [e.protocol_stage for e in events]
        assert stages == ["INIT", "RECEIVE", "ROUTE", "EXECUTE", "ROUTE", "FINISH"]

        # payload JSONB 可读回，且铺平字段存在
        execute_event = next(e for e in events if e.protocol_stage == "EXECUTE")
        assert execute_event.payload["model"] == "gpt-4o"
        assert execute_event.payload["prompt_tokens"] == 10
        assert execute_event.payload["completion_tokens"] == 5

        # 契约 3：后台 session 结算 workflow_executions
        exec_row = await session.get(WorkflowExecution, EXEC_ID)
        assert exec_row.status == "completed"
        assert exec_row.output is not None
        # 契约 2：BaseAgent 消费流并累积 token
        assert "Hello world" in exec_row.output.get("message", "")
