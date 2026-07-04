"""LLM 服务共享 Schema 定义。"""

from pydantic import BaseModel


class UsageStats(BaseModel):
    """LLM 调用用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_cost_usd: float = 0.0


class LLMStreamChunk(BaseModel):
    """LLM 流式输出分片。"""

    token: str | None = None
    reasoning_content: str | None = None
    usage: UsageStats | None = None
