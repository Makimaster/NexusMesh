import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.execution import (
    ExecutionListItem,
    ExecutionResponse,
    TimelineEventResponse,
)
from app.services.execution_service import ExecutionService

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("", response_model=list[ExecutionListItem])
async def list_executions(
    workflow_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[ExecutionListItem]:
    executions = await ExecutionService(db).list_executions(
        workflow_id=workflow_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [ExecutionListItem.model_validate(execution) for execution in executions]


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution_detail(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ExecutionResponse:
    execution = await ExecutionService(db).get_execution_detail(execution_id)
    return ExecutionResponse.model_validate(execution)


@router.get("/{execution_id}/timeline", response_model=list[TimelineEventResponse])
async def get_execution_timeline(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[TimelineEventResponse]:
    events = await ExecutionService(db).get_execution_timeline(execution_id)
    return [TimelineEventResponse.model_validate(event) for event in events]
