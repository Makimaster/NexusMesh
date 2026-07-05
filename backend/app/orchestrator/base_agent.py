"""M6 单 Agent 执行器。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.protocol import ExecutePayload

if TYPE_CHECKING:
    from app.orchestrator.event_emitter import EventEmitter
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
        prompt_tokens = 0
        completion_tokens = 0
        model_cost_usd = 0.0

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
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
                model_cost_usd = chunk.usage.model_cost_usd

        return ExecutePayload(
            agent_message="".join(buffer),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=self._llm_model,
            model_cost_usd=model_cost_usd,
        )

    def _build_messages(self, task_input: dict[str, Any]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": str(task_input.get("query", ""))})
        return messages
