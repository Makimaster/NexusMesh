"""M7 WorkflowService：负责 Workflow 拓扑预检、CRUD 与执行触发。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.agent import Agent
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.orchestrator.coordinator import Coordinator
from app.schemas.workflow import WorkflowRequest, WorkflowUpdateRequest


class WorkflowService:
    def __init__(self, db: AsyncSession, coordinator: Coordinator) -> None:
        self.db = db
        self.coordinator = coordinator

    async def _validate_topology(self, topology: dict) -> None:
        nodes = topology.get("nodes", [])
        edges = topology.get("edges", [])

        if not nodes:
            raise ValidationError("拓扑非法：画布节点集合为空，无法创建协作链路。")

        target_ids = {e.get("target") for e in edges if e.get("target")}
        entry_nodes = [
            n for n in nodes if n.get("id") and n.get("id") not in target_ids
        ]
        if not entry_nodes:
            raise ValidationError("拓扑非法：未检测到无入边的起始入口节点（闭环死锁）。")
        if len(entry_nodes) > 1:
            raise ValidationError("拓扑非法：存在多个无入边的冲突起始节点，暂不支持多入口调度。")

        for node in nodes:
            if not node.get("data", {}).get("agent_id"):
                raise ValidationError(
                    f"拓扑非法：节点 {node.get('id')} 未绑定 agent_id，违反'全 Agent 节点'契约。"
                )

        raw_agent_ids = {node["data"]["agent_id"] for node in nodes}
        parsed_uuids: list[uuid.UUID] = []
        for raw_id in raw_agent_ids:
            try:
                parsed_uuids.append(uuid.UUID(str(raw_id)))
            except ValueError as exc:
                raise ValidationError(
                    f"拓扑非法：智能体主键格式非法: {raw_id}"
                ) from exc

        stmt = select(Agent.id).where(
            Agent.id.in_(parsed_uuids), Agent.is_active.is_(True)
        )
        result = await self.db.execute(stmt)
        db_active_ids = set(result.scalars().all())
        if len(db_active_ids) != len(parsed_uuids):
            missing = [str(u) for u in parsed_uuids if u not in db_active_ids]
            raise ValidationError(
                f"拓扑非法：引用的智能体不存在或已被清退: {', '.join(missing)}"
            )

    async def create_workflow(
        self, schema: WorkflowRequest, created_by: uuid.UUID
    ) -> Workflow:
        data = schema.model_dump()
        await self._validate_topology(data.get("topology", {}))
        workflow = Workflow(**data, created_by=created_by, is_active=True)
        self.db.add(workflow)
        await self.db.flush()
        await self.db.refresh(workflow)
        return workflow

    async def get_workflow_detail(self, workflow_id: uuid.UUID) -> Workflow:
        workflow = await self.db.get(Workflow, workflow_id)
        if workflow is None or not workflow.is_active:
            raise NotFoundError(f"工作流不存在或已被删除: {workflow_id}")
        return workflow

    async def list_workflows(
        self, limit: int = 20, offset: int = 0
    ) -> list[Workflow]:
        stmt = (
            select(Workflow)
            .where(Workflow.is_active.is_(True))
            .order_by(Workflow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_workflow(
        self, workflow_id: uuid.UUID, schema: WorkflowUpdateRequest
    ) -> Workflow:
        workflow = await self.get_workflow_detail(workflow_id)
        update_data = schema.model_dump(exclude_unset=True)
        update_data.pop("id", None)
        update_data.pop("is_active", None)
        if "topology" in update_data and update_data["topology"] is None:
            raise ValidationError("拓扑非法：topology 不能为空。")
        if "topology" in update_data:
            await self._validate_topology(update_data["topology"])
        for key, value in update_data.items():
            setattr(workflow, key, value)
        await self.db.flush()
        await self.db.refresh(workflow)
        return workflow

    async def delete_workflow(self, workflow_id: uuid.UUID) -> None:
        workflow = await self.db.get(Workflow, workflow_id)
        if workflow is None or not workflow.is_active:
            return
        workflow.is_active = False
        await self.db.flush()

    async def trigger_execution(
        self, workflow_id: uuid.UUID, task_input: dict
    ) -> uuid.UUID:
        await self.get_workflow_detail(workflow_id)
        execution = WorkflowExecution(
            workflow_id=workflow_id, status="pending", input=task_input
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        await self.coordinator.start_execution(str(execution.id))
        return execution.id
