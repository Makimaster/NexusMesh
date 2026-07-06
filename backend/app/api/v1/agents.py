import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRole, get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.agent import (
    AgentListItem,
    AgentRequest,
    AgentResponse,
    AgentUpdateRequest,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentResponse)
async def create_agent(
    schema: AgentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> AgentResponse:
    agent = await AgentService(db).create_agent(schema, created_by=current_user.id)
    return AgentResponse.model_validate(agent)


@router.get("", response_model=list[AgentListItem])
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[AgentListItem]:
    agents = await AgentService(db).list_agents(limit=limit, offset=offset)
    return [AgentListItem.model_validate(agent) for agent in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent_detail(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AgentResponse:
    agent = await AgentService(db).get_agent_detail(agent_id)
    return AgentResponse.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    schema: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> AgentResponse:
    agent = await AgentService(db).update_agent(agent_id, schema)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> None:
    await AgentService(db).delete_agent(agent_id)
