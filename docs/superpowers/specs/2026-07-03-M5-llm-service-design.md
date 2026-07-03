# M5 LLM 服务层 — 设计文档

**版本**：1.0.0  
**日期**：2026-07-03  
**状态**：已确认，待实现  
**上游文档**：[模块路线图](./2026-07-01-module-roadmap.md)

---

## 1. 职责定位

M5 LLM 服务层是 NexusMesh 与所有大模型厂商之间的**统一适配层**，通过 LiteLLM 封装多厂商调用接口，对上游 M6 Orchestrator 暴露一个稳定的流式调用接口，屏蔽 LiteLLM 版本变更和厂商差异。

**职责边界**：
- ✅ 调用 LiteLLM 并返回类型化的流式响应（token + 用量统计）
- ✅ 统一异常屏蔾，转换为自定义 `LLMServiceError`
- ✅ 就地记录详细错误日志，便于生产环境排查
- ❌ **不做**：路由决策（属于 M6）、持久化（属于 M3/M1）、会话管理（属于 M3）

---

## 2. 文件结构

路线图指定落地 `services/llm_service.py`（单文件），但结合两个独立关注点（Schema + 异常），最终拆成 **3 个文件**：

```
backend/app/services/
├── llm_service.py       # LLMService 类（新增）
├── llm_schemas.py       # LLMStreamChunk / UsageStats（新增）
└── llm_exceptions.py    # LLMServiceError（新增）
```

**拆分理由**：
1. **避免循环导入**：M6 导入 `LLMService`，M4 WebSocket 将来可能直接导入 `LLMStreamChunk` 做 JSON 序列化
2. **对齐现有规范**：M3 已有独立的 `exceptions.py`
3. **测试便利性**：Schema 和异常可独立测试

---

## 3. 核心组件

### 3.1 `UsageStats`（用量统计模型）

**文件**：`backend/app/services/llm_schemas.py`

```python
from pydantic import BaseModel


class UsageStats(BaseModel):
    """权威用量统计，由 LiteLLM 从厂商响应中提取。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_cost_usd: float = 0.0
```

**设计要点**：
- 对齐 `ExecutePayload` 中的 3 个 LLM 返回字段：`prompt_tokens`、`completion_tokens`、`model_cost_usd`
- `ExecutePayload.model` 由 M6 从 `stream_completion` 的入参直接取得，不经过 `UsageStats`
- `model_cost_usd` 由 LiteLLM 内置价格表自动折算，**不需要手动计算**
- M6 将此对象直接映射到 `ExecutePayload`，无需二次转换

### 3.2 `LLMStreamChunk`（流式帧承载体）

**文件**：`backend/app/services/llm_schemas.py`

```python
from pydantic import BaseModel


class LLMStreamChunk(BaseModel):
    """流式帧承载体。三字段均可为 None，尾帧 usage 非 None。"""
    token: str | None = None
    reasoning_content: str | None = None  # 兼容思维链模型（如 DeepSeek-R1）
    usage: UsageStats | None = None        # 仅最后一帧非 None
```

**设计要点**：
- **类型化协议包**：流中流淌的不是纯文本，而是结构化对象
- **尾帧特殊性**：最后一个 chunk 的 `usage` 字段非 `None`，携带权威用量统计
- **扩展性**：`reasoning_content` 为 2026 年主流思维链模型（DeepSeek-R1/O1）预留
- **序列化友好**：可直接 `.model_dump_json()` 通过 M4 WebSocket 下发前端

### 3.3 `LLMServiceError`（统一异常）

**文件**：`backend/app/services/llm_exceptions.py`

```python
class LLMServiceError(RuntimeError):
    """LLM 服务统一异常，屏蔽底层厂商细节。"""
    pass
```

**设计要点**：
- 继承 `RuntimeError`（与 M3 的 `ConcurrencyError(RuntimeError)` 对齐）
- **单一异常类**：遵循最小化原则，不细分子类（M6 收到后统一作失败处理）
- **异常链保持**：抛出时使用 `raise ... from e`，保留原始 `litellm.*Error` 追溯链

### 3.4 `LLMService`（核心服务类）

**文件**：`backend/app/services/llm_service.py`

唯一公开方法：`stream_completion()`，返回 `AsyncGenerator[LLMStreamChunk, None]`。

构造函数注入 `AppSettings`（通过 `Depends(lambda: settings)` 支持 FastAPI 自动注入和手动测试注入双向可用）。

---

## 4. 数据流设计

### 4.1 完整调用链路

```
M6 Orchestrator
  │
  └─→ LLMService.stream_completion(messages, model?, temperature?)
        │
        └─→ litellm.acompletion(
              stream=True,
              stream_options={"include_usage": True}  # 关键参数
            )
              │
              ├─→ yield LLMStreamChunk(token="Hello")
              ├─→ yield LLMStreamChunk(token=" world")
              ├─→ yield LLMStreamChunk(reasoning_content="...")  ← 思维链（可选）
              └─→ yield LLMStreamChunk(usage=UsageStats(...))   ← 最后一帧
```

### 4.2 M6 到 M3/M1 的完整数据流

1. **M6** 调用 `stream_completion()` 开始流式接收
2. **M6** 累积所有 `token` 字段，拼接成完整 `agent_message`
3. **M6** 收到最后一帧的 `usage` 后，组装 `ExecutePayload`：
   ```python
   ExecutePayload(
       agent_message=accumulated_tokens,
       prompt_tokens=usage.prompt_tokens,
       completion_tokens=usage.completion_tokens,
       model=model_name,
       model_cost_usd=usage.model_cost_usd
   )
   ```
4. **M6** 将 `ExecutePayload` 通过 M3 写入 Redis，通过 M1 持久化到 PostgreSQL
5. **M4** 订阅 Redis 事件，将完整 payload 推送前端

### 4.3 LiteLLM `stream_options` 机制

LiteLLM 1.50.x 原生支持在流式调用的**最后一个 chunk** 中包含完整 `usage` 统计，需在调用时传入：

```python
await litellm.acompletion(
    stream=True,
    stream_options={"include_usage": True}  # 强制最后一帧携带 usage
)
```

**注意事项**：
- 此特性在 OpenAI/Anthropic/Azure 等主流厂商 2026 年已全面支持
- 如果厂商不支持，LiteLLM 会在最后一帧返回空的 `usage`（`total_tokens=0`）
- M5 不做 fallback 本地计数——成本计算是黑盒，必须由厂商权威返回

---

## 5. 接口设计

### 5.1 `LLMService.__init__`

```python
from fastapi import Depends
from app.config.settings import AppSettings, settings


class LLMService:
    def __init__(
        self,
        app_settings: AppSettings = Depends(lambda: settings)
    ) -> None:
        """
        通过 FastAPI Depends 默认注入全局 settings 单例。
        在非 FastAPI 环境（如 M6 独立脚本）中，可手动传入：LLMService(settings)
        """
        self.settings = app_settings
        
        # 关闭 LiteLLM 全局遥测，确保企业级数据隐私
        litellm.telemetry = False
```

**设计亮点**：
- `Depends(lambda: settings)` 双向可用：
  - FastAPI 路由中：`llm_service: LLMService = Depends()` 自动注入
  - 后台脚本/测试：`service = LLMService(my_mock_settings)` 手动注入
- `litellm.telemetry = False` 阻止遥测数据上报，符合企业级部署要求

### 5.2 `LLMService.stream_completion`

```python
from typing import AsyncGenerator, Any


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
```

**参数设计原则**：
- **必需参数**：仅 `messages`（最小接口）
- **常用参数显式化**：`model`、`temperature` 作为命名参数，便于调用方阅读
- **扩展性**：`**kwargs` 透传给 LiteLLM，满足 M6 按需覆盖 `max_tokens`、`top_p` 等高级参数，无需修改 M5
- **无重试参数**：重试策略属于 M6 编排层职责，M5 只负责单次调用

---

## 6. 错误处理策略

### 6.1 异常包装机制

M5 捕获所有底层 litellm 异常，统一转换为 `LLMServiceError`，实现上游与厂商细节的完全解耦：

```python
try:
    response = await litellm.acompletion(...)
    async for chunk in response:
        # ... yield 逻辑
        yield parsed_chunk

except (
    litellm.AuthenticationError,
    litellm.BadRequestError,
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
) as e:
    # 就地记录详细上下文，避免 M6 捕获后信息丢失
    logger.error(f"[LLMService] LLM调用失败: {e} | model={target_model}")
    raise LLMServiceError(f"LLM调用异常: {str(e)}") from e

except Exception as e:
    # 兜底：未知网络断开、asyncio 超时等
    logger.critical(f"[LLMService] 未知异常: {e}")
    raise LLMServiceError(f"LLM网络异常: {str(e)}") from e
```

### 6.2 设计要点

| 要点 | 说明 |
|---|---|
| `raise ... from e` | Python 3.11+ 规范，保持 `__cause__` 异常链，Sentry 等可完整显示双层调用栈 |
| 就地 `logger.error` | 在转换前记录原始 `litellm.*Error` 详情，防止信息在 M6 catch 后丢失 |
| 精准捕获 vs 兜底 | 已知的 4 类 litellm 异常精准捕获；其余 `Exception` 兜底，记录 `critical` 级别 |
| 不捕获 `asyncio.CancelledError` | 主动取消（用户中断）不视为 LLM 故障，透传给 Python 运行时正常处理 |

---

## 7. 测试策略

### 7.1 测试文件位置

```
backend/tests/unit/test_llm_service.py
```

### 7.2 Mock 方法

使用 `unittest.mock.patch` 替换 `litellm.acompletion`，全程不消耗真实 API 配额：

```python
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.DEFAULT_LLM_MODEL = "gpt-4o"
    settings.LITELLM_API_BASE = None
    return settings


@pytest.mark.asyncio
async def test_stream_completion_returns_tokens_and_usage(mock_settings):
    mock_chunk1 = MagicMock(
        choices=[MagicMock(delta=MagicMock(content="Hello", reasoning_content=None))]
    )
    mock_chunk2 = MagicMock(
        choices=[MagicMock(delta=MagicMock(content=" world", reasoning_content=None))]
    )
    # 真实尾帧：厂商通常不返回 choices，只返回 usage
    mock_chunk3 = MagicMock(spec=[])
    mock_chunk3.usage = MagicMock(
        prompt_tokens=10, completion_tokens=5,
        total_tokens=15, model_cost_usd=0.0001,
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

### 7.3 单元测试用例清单

| 测试名称 | 验证目标 |
|---|---|
| `test_stream_completion_returns_tokens_and_usage` | 流式返回 token + 尾帧 usage 字段正确 |
| `test_stream_completion_uses_default_model` | `model=None` 时回落 `settings.DEFAULT_LLM_MODEL` |
| `test_stream_completion_uses_custom_model` | `model` 参数透传给 litellm |
| `test_stream_completion_raises_on_auth_error` | `litellm.AuthenticationError` → `LLMServiceError` |
| `test_stream_completion_raises_on_rate_limit` | `litellm.RateLimitError` → `LLMServiceError` |

共 **5 个单元测试**，均对 mock LLM 后端，无真实 API 调用。

---

## 8. 完成标准（DoD）

| 验收项 | 说明 |
|---|---|
| 流式返回正确 | `stream_completion()` yield `LLMStreamChunk`，尾帧 `usage` 非 `None` |
| 默认模型回落 | `model=None` 时使用 `settings.DEFAULT_LLM_MODEL` |
| 用量字段对齐 | `UsageStats` 的 4 个字段与 `ExecutePayload` 完全对应 |
| 异常屏蔽 | litellm 异常被捕获并转换为 `LLMServiceError` |
| 5 个单测全绿 | 不消耗真实 API 配额 |
| Ruff 通过 | `ruff check app tests` 无报错 |

---

## 9. 前置依赖与下游影响

| 依赖方向 | 模块 | 说明 |
|---|---|---|
| M5 依赖 | `common`（`settings`、`logger`） | 已有，无需新增 |
| M5 依赖 | `litellm==1.50.*` | 已在 `pyproject.toml` 锁定 |
| M6 依赖 M5 | `LLMService` | M6 构造注入并调用 `stream_completion()` |
| M4 可选依赖 M5 | `LLMStreamChunk` | M4 可直接 `model_dump_json()` 作为 WebSocket 帧 |
