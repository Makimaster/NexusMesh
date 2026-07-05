"""M6 编排引擎门面 + 五阶段协议主循环。"""

from __future__ import annotations

import asyncio

import redis.asyncio as redis

from app.common.logger import log
from app.orchestrator.event_emitter import EventEmitter
from app.orchestrator.exceptions import OrchestratorError
from app.orchestrator.router import AgentRouter
from app.orchestrator.scheduler import Scheduler
from app.protocol import (
    EventType,
    ExecutePayload,
    FinishPayload,
    InitPayload,
    ProtocolEvent,
    ProtocolStage,
    ReceivePayload,
    RoutePayload,
)
from app.services.llm_exceptions import LLMServiceError
from app.services.llm_service import LLMService
from app.state_manager.task_state import TaskStateManager


class Coordinator:
    """M6 编排引擎门面。"""

    def __init__(self, redis_client: redis.Redis, llm_service: LLMService) -> None:
        self._emitter = EventEmitter(redis_client)
        self._task_state = TaskStateManager(redis_client)
        self._router = AgentRouter()
        self._scheduler = Scheduler(llm_service, self._emitter)

    async def start_execution(self, execution_id: str) -> None:
        log.info("[M6 Coordinator] 收到工作流触发, execution_id=%s", execution_id)
        asyncio.create_task(self._execute_workflow_loop(execution_id))

    async def _execute_workflow_loop(self, execution_id: str) -> None:
        last_message = ""
        try:
            ctx = await self._scheduler.load_execution_context(execution_id)

            await self._task_state.create(execution_id, "INIT")
            await self._emit(
                execution_id,
                ProtocolStage.INIT,
                EventType.AGENT_SPAWN,
                InitPayload(agent_id="orchestrator", workflow_id=ctx.workflow_id),
            )

            await self._task_state.transition(execution_id, "RECEIVE", "running")
            await self._emit(
                execution_id,
                ProtocolStage.RECEIVE,
                EventType.AGENT_CALL,
                ReceivePayload(task_input=ctx.task_input),
            )

            current_node: str | None = None
            while True:
                decision = self._router.route_next(current_node, ctx.topology)
                await self._task_state.transition(
                    execution_id,
                    "ROUTE",
                    "running",
                    agent_id=decision.next_agent_id,
                )
                await self._emit(
                    execution_id,
                    ProtocolStage.ROUTE,
                    EventType.AGENT_CALL,
                    RoutePayload(
                        next_agent_id=decision.next_agent_id,
                        routing_reason=decision.reason,
                    ),
                )
                if decision.next_node_id is None:
                    break

                agent = await self._scheduler.load_agent(decision.next_agent_id)
                await self._task_state.transition(
                    execution_id,
                    "EXECUTE",
                    "running",
                    agent_id=decision.next_agent_id,
                )
                payload: ExecutePayload = await agent.run(execution_id, ctx.task_input)
                last_message = payload.agent_message
                await self._emit(
                    execution_id,
                    ProtocolStage.EXECUTE,
                    EventType.AGENT_FINISH,
                    payload,
                )
                current_node = decision.next_node_id

            output = {"message": last_message}
            await self._task_state.transition(execution_id, "FINISH", "completed")
            await self._emit(
                execution_id,
                ProtocolStage.FINISH,
                EventType.AGENT_FINISH,
                FinishPayload(success=True, output=output),
            )
            await self._scheduler.settle_execution(
                execution_id,
                status="completed",
                output=output,
            )
        except (LLMServiceError, OrchestratorError, Exception) as exc:
            error_msg = str(exc)
            log.error(
                "[M6 Coordinator] execution_id=%s 失败结算: %s",
                execution_id,
                error_msg,
            )
            await self._emit(
                execution_id,
                ProtocolStage.FINISH,
                EventType.AGENT_FINISH,
                FinishPayload(success=False, output={"error": error_msg}),
            )
            await self._scheduler.settle_execution(
                execution_id,
                status="failed",
                error=error_msg,
            )

    async def _emit(
        self,
        execution_id: str,
        stage: ProtocolStage,
        event_type: EventType,
        payload: InitPayload | ReceivePayload | RoutePayload | ExecutePayload | FinishPayload,
    ) -> None:
        await self._emitter.emit_event(
            execution_id,
            ProtocolEvent(
                protocol_stage=stage,
                event_type=event_type,
                payload=payload,
            ),
        )
