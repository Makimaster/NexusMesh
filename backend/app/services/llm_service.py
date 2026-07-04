"""LiteLLM 流式调用服务。"""

from typing import Any

import litellm
from fastapi import Depends
from fastapi.params import Depends as DependsParam
from litellm.exceptions import (
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    ServiceUnavailableError,
)

from app.common.logger import log
from app.config.settings import AppSettings, settings
from app.services.llm_exceptions import LLMServiceError
from app.services.llm_schemas import LLMStreamChunk, UsageStats


class LLMService:
    """封装 LiteLLM 流式补全调用。"""

    def __init__(self, app_settings: AppSettings = Depends(lambda: settings)) -> None:
        self.settings = settings if isinstance(app_settings, DependsParam) else app_settings
        litellm.telemetry = False

    async def stream_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ):
        try:
            stream = await litellm.acompletion(
                model=model or self.settings.DEFAULT_LLM_MODEL,
                messages=messages,
                temperature=temperature,
                stream=True,
                stream_options={"include_usage": True},
                **kwargs,
            )

            async for chunk in stream:
                token = self._extract_delta_value(chunk, "content")
                reasoning_content = self._extract_delta_value(
                    chunk, "reasoning_content"
                )
                usage = self._extract_usage(chunk)

                if token is None and reasoning_content is None and usage is None:
                    continue

                yield LLMStreamChunk(
                    token=token,
                    reasoning_content=reasoning_content,
                    usage=usage,
                )
        except (
            AuthenticationError,
            BadRequestError,
            RateLimitError,
            ServiceUnavailableError,
        ) as exc:
            log.error("LiteLLM stream completion failed: %s", exc)
            raise LLMServiceError(str(exc)) from exc
        except Exception as exc:
            log.critical("Unexpected LiteLLM stream completion failure: %s", exc)
            raise LLMServiceError(str(exc)) from exc

    @staticmethod
    def _extract_delta_value(chunk: Any, field: str) -> str | None:
        choices = LLMService._read_value(chunk, "choices")
        if not choices:
            return None

        delta = LLMService._read_value(choices[0], "delta")
        value = LLMService._read_value(delta, field)
        return value if isinstance(value, str) else None

    @staticmethod
    def _extract_usage(chunk: Any) -> UsageStats | None:
        usage = LLMService._read_value(chunk, "usage")
        if usage is None:
            return None

        return UsageStats(
            prompt_tokens=LLMService._read_int(usage, "prompt_tokens"),
            completion_tokens=LLMService._read_int(usage, "completion_tokens"),
            total_tokens=LLMService._read_int(usage, "total_tokens"),
            model_cost_usd=LLMService._read_float(usage, "model_cost_usd"),
        )

    @staticmethod
    def _read_value(source: Any, key: str) -> Any:
        if source is None:
            return None
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    @staticmethod
    def _read_int(source: Any, key: str) -> int:
        value = LLMService._read_value(source, key)
        return value if isinstance(value, int) else 0

    @staticmethod
    def _read_float(source: Any, key: str) -> float:
        value = LLMService._read_value(source, key)
        return float(value) if isinstance(value, int | float) else 0.0
