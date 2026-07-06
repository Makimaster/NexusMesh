import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.orchestrator import get_coordinator
from app.core.auth import UserRole, get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.orchestrator.coordinator import Coordinator
from app.schemas.execution import ExecutionAcceptedResponse
from app.schemas.workflow import (
    TriggerRequest,
    WorkflowListItem,
    WorkflowRequest,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", status_code=201, response_model=WorkflowResponse)
async def create_workflow(
    payload: WorkflowRequest,
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> WorkflowResponse:
    workflow = await WorkflowService(db=db, coordinator=coordinator).create_workflow(
        payload, created_by=current_user.id
    )
    return WorkflowResponse.model_validate(workflow)


@router.get("", response_model=list[WorkflowListItem])
async def list_workflows(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    _current_user: User = Depends(get_current_user),
) -> list[WorkflowListItem]:
    workflows = await WorkflowService(db=db, coordinator=coordinator).list_workflows(
        limit=limit, offset=offset
    )
    return [WorkflowListItem.model_validate(workflow) for workflow in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_detail(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    _current_user: User = Depends(get_current_user),
) -> WorkflowResponse:
    workflow = await WorkflowService(
        db=db, coordinator=coordinator
    ).get_workflow_detail(workflow_id)
    return WorkflowResponse.model_validate(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowUpdateRequest,
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    _current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> WorkflowResponse:
    workflow = await WorkflowService(db=db, coordinator=coordinator).update_workflow(
        workflow_id, payload
    )
    return WorkflowResponse.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    _current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> None:
    await WorkflowService(db=db, coordinator=coordinator).delete_workflow(workflow_id)


@router.post(
    "/{workflow_id}/execute",
    status_code=202,
    response_model=ExecutionAcceptedResponse,
)
async def trigger_workflow_execution(
    workflow_id: uuid.UUID,
    payload: TriggerRequest,
    db: AsyncSession = Depends(get_db),
    coordinator: Coordinator = Depends(get_coordinator),
    _current_user: User = require_roles(UserRole.DEVELOPER, UserRole.ADMIN),
) -> ExecutionAcceptedResponse:
    execution_id = await WorkflowService(
        db=db, coordinator=coordinator
    ).trigger_execution(
        workflow_id=workflow_id,
        task_input=payload.task_input,
    )
    return ExecutionAcceptedResponse(execution_id=execution_id)
