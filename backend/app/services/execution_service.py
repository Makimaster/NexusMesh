"""M7 ExecutionService：执行实例与事件流只读查询。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.event import ExecutionEvent
from app.models.execution import WorkflowExecution


class ExecutionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_execution_detail(
        self, execution_id: uuid.UUID
    ) -> WorkflowExecution:
        execution = await self.db.get(WorkflowExecution, execution_id)
        if execution is None:
            raise NotFoundError(f"执行实例不存在: {execution_id}")
        return execution

    async def list_executions(
        self,
        workflow_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[WorkflowExecution]:
        stmt = select(WorkflowExecution)
        if workflow_id is not None:
            stmt = stmt.where(WorkflowExecution.workflow_id == workflow_id)
        if status is not None:
            stmt = stmt.where(WorkflowExecution.status == status)
        stmt = (
            stmt.order_by(WorkflowExecution.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_execution_timeline(
        self, execution_id: uuid.UUID
    ) -> list[ExecutionEvent]:
        await self.get_execution_detail(execution_id)
        stmt = (
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
