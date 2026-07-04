from pydantic import BaseModel


class UsageStats(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LLMStreamChunk(BaseModel):
    token: str | None = None
    usage: UsageStats | None = None
