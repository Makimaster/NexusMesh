from types import SimpleNamespace

import pytest

from app.config.settings import AppSettings, settings
from app.services.llm_service import LLMService


def test_llm_service_uses_module_settings_outside_fastapi_di() -> None:
    service = LLMService()

    assert service.settings is settings
    assert service.settings.DEFAULT_LLM_MODEL == settings.DEFAULT_LLM_MODEL


@pytest.mark.asyncio
async def test_stream_completion_returns_tokens_and_usage() -> None:
    captured_kwargs: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object):
        captured_kwargs.update(kwargs)

        async def iterator():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="Hello",
                            reasoning_content="step-1",
                        )
                    )
                ]
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=" world",
                            reasoning_content="step-2",
                        )
                    )
                ]
            )
            yield SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=5,
                    completion_tokens=2,
                    total_tokens=7,
                    model_cost_usd=0.01,
                ),
            )

        return iterator()

    pytest.importorskip("litellm")
    import litellm

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    try:
        service = LLMService(
            AppSettings(
                SECRET_KEY="s" * 32,
                JWT_SECRET_KEY="j" * 32,
                DEFAULT_LLM_MODEL="test-model",
            )
        )

        chunks = [
            chunk
            async for chunk in service.stream_completion(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                timeout=15,
            )
        ]
    finally:
        monkeypatch.undo()

    assert captured_kwargs["model"] == "test-model"
    assert captured_kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert captured_kwargs["temperature"] == 0.2
    assert captured_kwargs["stream"] is True
    assert captured_kwargs["stream_options"] == {"include_usage": True}
    assert captured_kwargs["timeout"] == 15

    assert [chunk.token for chunk in chunks] == ["Hello", " world", None]
    assert [chunk.reasoning_content for chunk in chunks] == ["step-1", "step-2", None]
    assert chunks[2].usage is not None
    assert chunks[2].usage.prompt_tokens == 5
    assert chunks[2].usage.completion_tokens == 2
    assert chunks[2].usage.total_tokens == 7
    assert chunks[2].usage.model_cost_usd == 0.01


@pytest.mark.asyncio
async def test_stream_completion_uses_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object):
        captured_kwargs.update(kwargs)

        async def iterator():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="ok", reasoning_content=None)
                    )
                ]
            )

        return iterator()

    pytest.importorskip("litellm")
    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    service = LLMService(
        AppSettings(
            SECRET_KEY="s" * 32,
            JWT_SECRET_KEY="j" * 32,
            DEFAULT_LLM_MODEL="default-model",
        )
    )

    async for _ in service.stream_completion(
        messages=[{"role": "user", "content": "hi"}]
    ):
        pass

    assert captured_kwargs["model"] == "default-model"


@pytest.mark.asyncio
async def test_stream_completion_uses_custom_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object):
        captured_kwargs.update(kwargs)

        async def iterator():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="ok", reasoning_content=None)
                    )
                ]
            )

        return iterator()

    pytest.importorskip("litellm")
    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    service = LLMService(
        AppSettings(
            SECRET_KEY="s" * 32,
            JWT_SECRET_KEY="j" * 32,
            DEFAULT_LLM_MODEL="default-model",
        )
    )

    async for _ in service.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        model="custom-model",
    ):
        pass

    assert captured_kwargs["model"] == "custom-model"
