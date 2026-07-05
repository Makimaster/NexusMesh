"""M6 Scheduler：Agent 工厂、上下文加载与执行结算。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.execution import WorkflowExecution
from app.models.workflow import Workflow
from app.orchestrator.base_agent import BaseAgent
from app.orchestrator.event_emitter import EventEmitter
from app.orchestrator.exceptions import OrchestratorError
from app.services.llm_service import LLMService


@dataclass
class ExecutionContext:
    workflow_id: str
    topology: dict
    task_input: dict


class Scheduler:
    def __init__(self, llm_service: LLMService, emitter: EventEmitter) -> None:
        self._llm = llm_service
        self._emitter = emitter

    async def load_execution_context(self, execution_id: str) -> ExecutionContext:
        exec_uuid = self._to_uuid(execution_id, "execution_id")
        async with AsyncSessionLocal() as session:
            exec_row = await session.get(WorkflowExecution, exec_uuid)
            if exec_row is None:
                raise OrchestratorError(f"执行实例不存在: {execution_id}")

            topology = {}
            if exec_row.workflow_id is not None:
                wf_row = await session.get(Workflow, exec_row.workflow_id)
                if wf_row is not None:
                    topology = wf_row.topology or {}

            return ExecutionContext(
                workflow_id=str(exec_row.workflow_id),
                topology=topology,
                task_input=exec_row.input or {},
            )

    async def load_agent(self, agent_id: str) -> BaseAgent:
        agent_uuid = self._to_uuid(agent_id, "agent_id")
        async with AsyncSessionLocal() as session:
            row = await session.get(Agent, agent_uuid)
            if row is None:
                raise OrchestratorError(f"Agent 不存在: {agent_id}")

            return BaseAgent(
                agent_id=agent_id,
                llm_model=row.llm_model,
                system_prompt=row.system_prompt,
                llm_service=self._llm,
                emitter=self._emitter,
            )

    async def settle_execution(
        self,
        execution_id: str,
        status: str,
        output: dict | None = None,
        error: str | None = None,
    ) -> None:
        exec_uuid = self._to_uuid(execution_id, "execution_id")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                row = await session.get(WorkflowExecution, exec_uuid)
                if row is not None:
                    row.status = status
                    row.output = output
                    row.error = error

    @staticmethod
    def _to_uuid(value: str, field: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as exc:
            raise OrchestratorError(f"{field} 非法 UUID: {value}") from exc
