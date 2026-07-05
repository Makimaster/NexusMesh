"""M7 AgentService：Agent 资产软删除 CRUD。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.agent import Agent
from app.schemas.agent import AgentRequest, AgentUpdateRequest


class AgentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_agent(
        self, schema: AgentRequest, created_by: uuid.UUID
    ) -> Agent:
        agent = Agent(**schema.model_dump(), created_by=created_by, is_active=True)
        self.db.add(agent)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def get_agent_detail(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or not agent.is_active:
            raise NotFoundError(f"Agent 不存在或已被删除: {agent_id}")
        return agent

    async def list_agents(self, limit: int = 20, offset: int = 0) -> list[Agent]:
        stmt = (
            select(Agent)
            .where(Agent.is_active.is_(True))
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_agent(
        self, agent_id: uuid.UUID, schema: AgentUpdateRequest
    ) -> Agent:
        agent = await self.get_agent_detail(agent_id)
        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("id", None)
        update_data.pop("is_active", None)
        for key, value in update_data.items():
            setattr(agent, key, value)
        await self.db.flush()
        await self.db.refresh(agent)
        return agent

    async def delete_agent(self, agent_id: uuid.UUID) -> None:
        agent = await self.db.get(Agent, agent_id)
        if agent is None or not agent.is_active:
            return
        agent.is_active = False
        await self.db.flush()
