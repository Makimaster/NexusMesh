from app.services.llm_schemas import LLMStreamChunk, UsageStats


def test_usage_stats_instantiation() -> None:
    usage = UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15


def test_llm_stream_chunk_with_token() -> None:
    chunk = LLMStreamChunk(token="hello")

    assert chunk.token == "hello"
    assert chunk.usage is None


def test_llm_stream_chunk_with_usage() -> None:
    usage = UsageStats(prompt_tokens=20, completion_tokens=8, total_tokens=28)
    chunk = LLMStreamChunk(usage=usage)

    assert chunk.token is None
    assert chunk.usage == usage
