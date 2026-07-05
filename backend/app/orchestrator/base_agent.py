"""M6 单 Agent 执行器。"""

from __future__ import annotations

from typing import Any

from app.orchestrator.event_emitter import EventEmitter
from app.protocol import ExecutePayload
from app.services.llm_schemas import UsageStats
from app.services.llm_service import LLMService


class BaseAgent:
    def __init__(
        self,
        agent_id: str,
        llm_model: str,
        system_prompt: str | None,
        llm_service: LLMService,
        emitter: EventEmitter,
    ) -> None:
        self._agent_id = agent_id
        self._llm_model = llm_model
        self._system_prompt = system_prompt
        self._llm = llm_service
        self._emitter = emitter

    async def run(self, execution_id: str, task_input: dict[str, Any]) -> ExecutePayload:
        messages = self._build_messages(task_input)
        buffer: list[str] = []
        usage = UsageStats()

        async for chunk in self._llm.stream_completion(
            messages=messages,
            model=self._llm_model,
        ):
            if chunk.token:
                buffer.append(chunk.token)
                await self._emitter.emit_token(
                    execution_id,
                    self._agent_id,
                    chunk.token,
                )

            if chunk.reasoning_content:
                await self._emitter.emit_token(
                    execution_id,
                    self._agent_id,
                    chunk.reasoning_content,
                    reasoning=True,
                )

            if chunk.usage is not None:
                usage = chunk.usage

        return ExecutePayload(
            agent_message="".join(buffer),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            model=self._llm_model,
            model_cost_usd=usage.model_cost_usd,
        )

    def _build_messages(self, task_input: dict[str, Any]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": str(task_input.get("query", ""))})
        return messages
