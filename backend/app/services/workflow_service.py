"""M7 WorkflowService：仅负责 Workflow 拓扑预检。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.agent import Agent
from app.orchestrator.coordinator import Coordinator


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
