from app.services.llm_exceptions import LLMServiceError
from app.services.llm_schemas import LLMStreamChunk, UsageStats


def test_usage_stats_instantiation() -> None:
    usage = UsageStats()

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0
    assert usage.model_cost_usd == 0.0


def test_llm_stream_chunk_with_token() -> None:
    chunk = LLMStreamChunk(token="hello", reasoning_content="thinking")

    assert chunk.token == "hello"
    assert chunk.reasoning_content == "thinking"
    assert chunk.usage is None


def test_llm_stream_chunk_with_usage() -> None:
    usage = UsageStats(
        prompt_tokens=20,
        completion_tokens=8,
        total_tokens=28,
        model_cost_usd=0.12,
    )
    chunk = LLMStreamChunk(usage=usage)

    assert chunk.token is None
    assert chunk.reasoning_content is None
    assert chunk.usage == usage
    assert UsageStats.__doc__
    assert LLMStreamChunk.__doc__
    assert LLMServiceError.__doc__
