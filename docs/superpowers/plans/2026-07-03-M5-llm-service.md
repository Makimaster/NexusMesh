# M5 LLM 服务层 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 封装 LiteLLM 多厂商调用，提供统一的类型化流式接口（token + 用量统计）并屏蔽底层异常

**Architecture:** 3个文件分离关注点 —— `llm_exceptions.py`（统一异常）、`llm_schemas.py`（Pydantic模型）、`llm_service.py`（服务类）。`LLMService.stream_completion()` 调用 `litellm.acompletion(stream=True, stream_options={"include_usage": True})`，将 chunk 封装为 `LLMStreamChunk`，最后一帧携带 `UsageStats`。所有 litellm 异常转换为 `LLMServiceError`。

**Tech Stack:** Python 3.13, Pydantic 2.10, LiteLLM 1.50.x, pytest + unittest.mock

---

## 文件结构概览

| 文件 | 职责 | 行数估算 |
|---|---|---|
| `backend/app/services/llm_exceptions.py` | `LLMServiceError` 统一异常 | ~5 |
| `backend/app/services/llm_schemas.py` | `UsageStats` + `LLMStreamChunk` Pydantic 模型 | ~20 |
| `backend/app/services/llm_service.py` | `LLMService` 服务类，`stream_completion()` 方法 | ~80 |
| `backend/tests/unit/test_llm_service.py` | 5 个单元测试（mock litellm） | ~150 |
| `backend/app/services/__init__.py` | 导出公共 API | +3行 |

---

## Task 1: 定义基础 Schema 与异常

**Files:**
- Create: `backend/app/services/llm_exceptions.py`
- Create: `backend/app/services/llm_schemas.py`
- Create: `backend/tests/unit/test_llm_schemas.py`

### Step 1.1: 创建 LLMServiceError 异常类

- [ ] **创建 `backend/app/services/llm_exceptions.py`**

```python
"""LLM 服务统一异常，屏蔽底层厂商细节。"""


class LLMServiceError(RuntimeError):
    """LLM 服务调用失败统一异常。"""

    pass
```

### Step 1.2: 创建 Pydantic Schema 模型

- [ ] **创建 `backend/app/services/llm_schemas.py`**

```python
"""LLM 流式响应的 Pydantic 数据模型。"""

from pydantic import BaseModel


class UsageStats(BaseModel):
    """权威用量统计，由 LiteLLM 从厂商响应中提取。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_cost_usd: float = 0.0


class LLMStreamChunk(BaseModel):
    """流式帧承载体。三字段均可为 None，尾帧 usage 非 None。"""

    token: str | None = None
    reasoning_content: str | None = None  # 兼容思维链模型（如 DeepSeek-R1）
    usage: UsageStats | None = None  # 仅最后一帧非 None
```

### Step 1.3: 编写 Schema 基础测试

- [ ] **创建 `backend/tests/unit/test_llm_schemas.py`**

```python
"""测试 LLM Schema 模型的实例化与序列化。"""

from app.services.llm_schemas import LLMStreamChunk, UsageStats


def test_usage_stats_instantiation():
    usage = UsageStats(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        model_cost_usd=0.0001,
    )
    assert usage.prompt_tokens == 10
    assert usage.total_tokens == 15


def test_llm_stream_chunk_with_token():
    chunk = LLMStreamChunk(token="Hello")
    assert chunk.token == "Hello"
    assert chunk.usage is None


def test_llm_stream_chunk_with_usage():
    usage = UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    chunk = LLMStreamChunk(usage=usage)
    assert chunk.token is None
    assert chunk.usage.total_tokens == 15
```

### Step 1.4: 运行 Schema 测试

- [ ] **运行测试**

```bash
cd backend
pytest tests/unit/test_llm_schemas.py -v
```

**Expected:** 3 passed

### Step 1.5: 提交基础结构

- [ ] **提交**

```bash
git add backend/app/services/llm_exceptions.py backend/app/services/llm_schemas.py backend/tests/unit/test_llm_schemas.py
git commit -m "feat: 新增 LLM Schema 模型与统一异常（M5 基础）"
```

---

## Task 2: LLMService 核心实现 + 主流程测试

**Files:**
- Create: `backend/app/services/llm_service.py`
- Create: `backend/tests/unit/test_llm_service.py`

### Step 2.1: 编写主流程失败测试

- [ ] **创建 `backend/tests/unit/test_llm_service.py`**

```python
"""LLMService 单元测试（mock litellm）。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_schemas import LLMStreamChunk
from app.services.llm_service import LLMService


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.DEFAULT_LLM_MODEL = "gpt-4o"
    settings.LITELLM_API_BASE = None
    return settings


@pytest.mark.asyncio
async def test_stream_completion_returns_tokens_and_usage(mock_settings):
    """测试流式返回 token + 尾帧 usage。"""
    # Mock LiteLLM 响应
    mock_chunk1 = MagicMock(
        choices=[MagicMock(delta=MagicMock(content="Hello", reasoning_content=None))]
    )
    mock_chunk2 = MagicMock(
        choices=[MagicMock(delta=MagicMock(content=" world", reasoning_content=None))]
    )
    # 尾帧：通常无 choices，只有 usage
    mock_chunk3 = MagicMock(spec=[])
    mock_chunk3.usage = MagicMock(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        model_cost_usd=0.0001,
    )

    mock_response = AsyncMock()
    mock_response.__aiter__.return_value = [mock_chunk1, mock_chunk2, mock_chunk3]

    with patch("litellm.acompletion", return_value=mock_response):
        service = LLMService(mock_settings)
        chunks = [c async for c in service.stream_completion(messages=[])]

    assert len(chunks) == 3
    assert chunks[0].token == "Hello"
    assert chunks[1].token == " world"
    assert chunks[2].token is None
    assert chunks[2].usage.total_tokens == 15
    assert chunks[2].usage.model_cost_usd == pytest.approx(0.0001)
```

### Step 2.2: 运行测试确认失败

- [ ] **运行测试**

```bash
cd backend
pytest tests/unit/test_llm_service.py::test_stream_completion_returns_tokens_and_usage -v
```

**Expected:** FAIL (ModuleNotFoundError: No module named 'app.services.llm_service')

### Step 2.3: 实现 LLMService 完整逻辑

- [ ] **创建 `backend/app/services/llm_service.py`**

```python
"""LLM 服务层：封装 LiteLLM 多厂商调用。"""

from typing import Any, AsyncGenerator

import litellm
from fastapi import Depends

from app.common.logger import log
from app.config.settings import AppSettings, settings
from app.services.llm_exceptions import LLMServiceError
from app.services.llm_schemas import LLMStreamChunk, UsageStats


class LLMService:
    """LLM 统一服务类。"""

    def __init__(
        self, app_settings: AppSettings = Depends(lambda: settings)
    ) -> None:
        """
        通过 FastAPI Depends 默认注入全局 settings 单例。
        在非 FastAPI 环境（如 M6 独立脚本）中，可手动传入：LLMService(settings)
        """
        self.settings = app_settings

        # 关闭 LiteLLM 全局遥测，确保企业级数据隐私
        litellm.telemetry = False

    async def stream_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        全链路异步流式大模型调用接口。

        Args:
            messages: OpenAI 格式的消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称，None 时回落到 settings.DEFAULT_LLM_MODEL
            temperature: 温度参数，默认 0.7
            **kwargs: 透传给 LiteLLM 的额外参数（max_tokens、top_p 等）

        Yields:
            LLMStreamChunk: 流式帧，最后一帧包含 usage 统计

        Raises:
            LLMServiceError: 任何底层调用失败均转换为此异常
        """
        target_model = model or self.settings.DEFAULT_LLM_MODEL
        api_base = self.settings.LITELLM_API_BASE

        # 组装 LiteLLM 参数
        litellm_kwargs: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},  # 强制尾帧携带 usage
            **kwargs,
        }
        if api_base:
            litellm_kwargs["api_base"] = api_base

        try:
            response = await litellm.acompletion(**litellm_kwargs)

            async for chunk in response:
                # 提取 token
                choices = getattr(chunk, "choices", [])
                delta = choices[0].delta if choices else None
                token = getattr(delta, "content", None) if delta else None
                reasoning_content = (
                    getattr(delta, "reasoning_content", None) if delta else None
                )

                # 提取用量统计
                usage = None
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = UsageStats(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                        model_cost_usd=getattr(chunk.usage, "model_cost_usd", 0.0),
                    )

                # 发射类型化帧
                if token or reasoning_content or usage:
                    yield LLMStreamChunk(
                        token=token, reasoning_content=reasoning_content, usage=usage
                    )

        except (
            litellm.AuthenticationError,
            litellm.BadRequestError,
            litellm.RateLimitError,
            litellm.ServiceUnavailableError,
        ) as e:
            # 就地记录详细上下文，避免 M6 捕获后信息丢失
            log.error(f"[LLMService] LLM调用失败: {e} | model={target_model}")
            raise LLMServiceError(f"LLM调用异常: {str(e)}") from e

        except Exception as e:
            # 兜底：未知网络断开、asyncio 超时等
            log.critical(f"[LLMService] 未知异常: {e}")
            raise LLMServiceError(f"LLM网络异常: {str(e)}") from e
```

### Step 2.4: 运行测试确认通过

- [ ] **运行测试**

```bash
cd backend
pytest tests/unit/test_llm_service.py::test_stream_completion_returns_tokens_and_usage -v
```

**Expected:** 1 passed

### Step 2.5: 提交核心实现

- [ ] **提交**

```bash
git add backend/app/services/llm_service.py backend/tests/unit/test_llm_service.py
git commit -m "feat: 实现 LLMService.stream_completion 流式调用与 usage 统计"
```

---

## Task 3: 模型参数传递测试

**Files:**
- Modify: `backend/tests/unit/test_llm_service.py`

### Step 3.1: 补充两个模型参数测试

- [ ] **在 `backend/tests/unit/test_llm_service.py` 末尾追加**

```python
@pytest.mark.asyncio
async def test_stream_completion_uses_default_model(mock_settings):
    """model=None 时应回落到 settings.DEFAULT_LLM_MODEL。"""
    mock_settings.DEFAULT_LLM_MODEL = "gpt-4o"
    empty_response = AsyncMock()
    empty_response.__aiter__.return_value = []

    with patch("litellm.acompletion", return_value=empty_response) as mock_call:
        service = LLMService(mock_settings)
        # 消费生成器
        [c async for c in service.stream_completion(messages=[])]

    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_stream_completion_uses_custom_model(mock_settings):
    """显式传入 model 时应透传给 litellm，不被 settings 覆盖。"""
    empty_response = AsyncMock()
    empty_response.__aiter__.return_value = []

    with patch("litellm.acompletion", return_value=empty_response) as mock_call:
        service = LLMService(mock_settings)
        [c async for c in service.stream_completion(messages=[], model="claude-opus-4-8")]

    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-4-8"
```

### Step 3.2: 运行新增测试

- [ ] **运行测试**

```bash
cd backend
pytest tests/unit/test_llm_service.py::test_stream_completion_uses_default_model tests/unit/test_llm_service.py::test_stream_completion_uses_custom_model -v
```

**Expected:** 2 passed

### Step 3.3: 提交

- [ ] **提交**

```bash
git add backend/tests/unit/test_llm_service.py
git commit -m "test: 补充 LLMService 默认模型回落与自定义模型透传测试"
```

---

## Task 4: 异常处理测试

**Files:**
- Modify: `backend/tests/unit/test_llm_service.py`

### Step 4.1: 补充异常测试

- [ ] **在 `backend/tests/unit/test_llm_service.py` 末尾追加**

```python
@pytest.mark.asyncio
async def test_stream_completion_raises_on_auth_error(mock_settings):
    """litellm.AuthenticationError 应被转换为 LLMServiceError。"""
    import litellm as _litellm

    from app.services.llm_exceptions import LLMServiceError

    with patch(
        "litellm.acompletion",
        side_effect=_litellm.AuthenticationError(
            message="Invalid API key", llm_provider="openai", model="gpt-4o"
        ),
    ):
        service = LLMService(mock_settings)
        with pytest.raises(LLMServiceError, match="LLM调用异常"):
            [c async for c in service.stream_completion(messages=[])]


@pytest.mark.asyncio
async def test_stream_completion_raises_on_rate_limit(mock_settings):
    """litellm.RateLimitError 应被转换为 LLMServiceError。"""
    import litellm as _litellm

    from app.services.llm_exceptions import LLMServiceError

    with patch(
        "litellm.acompletion",
        side_effect=_litellm.RateLimitError(
            message="Rate limit exceeded", llm_provider="openai", model="gpt-4o"
        ),
    ):
        service = LLMService(mock_settings)
        with pytest.raises(LLMServiceError, match="LLM调用异常"):
            [c async for c in service.stream_completion(messages=[])]
```

### Step 4.2: 运行异常测试

- [ ] **运行测试**

```bash
cd backend
pytest tests/unit/test_llm_service.py::test_stream_completion_raises_on_auth_error tests/unit/test_llm_service.py::test_stream_completion_raises_on_rate_limit -v
```

**Expected:** 2 passed

### Step 4.3: 提交

- [ ] **提交**

```bash
git add backend/tests/unit/test_llm_service.py
git commit -m "test: 补充 LLMService 异常屏蔽测试（AuthenticationError / RateLimitError）"
```

---

## Task 5: 公共 API 导出 + DoD 全量验证

**Files:**
- Modify: `backend/app/services/__init__.py`

### Step 5.1: 更新 services 公共导出

- [ ] **修改 `backend/app/services/__init__.py`**

当前内容（空文件），替换为：

```python
from app.services.llm_exceptions import LLMServiceError
from app.services.llm_schemas import LLMStreamChunk, UsageStats
from app.services.llm_service import LLMService

__all__ = ["LLMService", "LLMStreamChunk", "LLMServiceError", "UsageStats"]
```

### Step 5.2: 运行全量单元测试

- [ ] **运行所有 M5 测试**

```bash
cd backend
pytest tests/unit/test_llm_schemas.py tests/unit/test_llm_service.py -v
```

**Expected:**
```
tests/unit/test_llm_schemas.py::test_usage_stats_instantiation PASSED
tests/unit/test_llm_schemas.py::test_llm_stream_chunk_with_token PASSED
tests/unit/test_llm_schemas.py::test_llm_stream_chunk_with_usage PASSED
tests/unit/test_llm_service.py::test_stream_completion_returns_tokens_and_usage PASSED
tests/unit/test_llm_service.py::test_stream_completion_uses_default_model PASSED
tests/unit/test_llm_service.py::test_stream_completion_uses_custom_model PASSED
tests/unit/test_llm_service.py::test_stream_completion_raises_on_auth_error PASSED
tests/unit/test_llm_service.py::test_stream_completion_raises_on_rate_limit PASSED

8 passed
```

### Step 5.3: Ruff 检查

- [ ] **Ruff 检查**

```bash
cd backend
ruff check app/services/llm_exceptions.py app/services/llm_schemas.py app/services/llm_service.py tests/unit/test_llm_schemas.py tests/unit/test_llm_service.py
```

**Expected:** 无报错输出

若有报错，运行自动修复：
```bash
ruff check --fix app/services/llm_exceptions.py app/services/llm_schemas.py app/services/llm_service.py
```

### Step 5.4: 最终提交

- [ ] **提交**

```bash
git add backend/app/services/__init__.py
git commit -m "feat: 导出 M5 LLM 服务公共 API，M5 全套测试通过"
```

---

## 完成标准确认（DoD）

| 验收项 | 验证命令 |
|---|---|
| 流式返回 + 尾帧 usage | `pytest tests/unit/test_llm_service.py::test_stream_completion_returns_tokens_and_usage` |
| 默认模型回落 | `pytest tests/unit/test_llm_service.py::test_stream_completion_uses_default_model` |
| 自定义模型透传 | `pytest tests/unit/test_llm_service.py::test_stream_completion_uses_custom_model` |
| 认证异常屏蔽 | `pytest tests/unit/test_llm_service.py::test_stream_completion_raises_on_auth_error` |
| 限速异常屏蔽 | `pytest tests/unit/test_llm_service.py::test_stream_completion_raises_on_rate_limit` |
| Ruff 全绿 | `ruff check app/services/ tests/unit/test_llm_service.py tests/unit/test_llm_schemas.py` |

