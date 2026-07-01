# NexusMesh 五阶段协议规范

**版本**：1.0.0  
**日期**：2026-07-01  
**状态**：已实现（M2）  
**实现位置**：`backend/app/protocol/`

## 1. 概述

`backend/app/protocol/` 定义了 Agent 间通信的统一数据契约。当前实现只负责：

- 定义五阶段枚举 `ProtocolStage`
- 定义标准事件类型 `EventType`
- 定义分阶段 payload 模型与统一信封 `ProtocolEvent`
- 提供扁平 dict 的序列化与反序列化能力

该模块本身不包含 IO、数据库或消息总线逻辑；外部系统可将 `to_payload()` 的结果存入 `execution_events.payload` 之类的 JSONB 字段，或作为协议传输载荷使用。

## 2. 五阶段

| 顺序 | 阶段 | 枚举值 | 当前职责 |
| --- | --- | --- | --- |
| 1 | 初始化 | `INIT` | 建立 Agent 上下文 |
| 2 | 接收输入 | `RECEIVE` | 接收并携带任务输入 |
| 3 | 路由决策 | `ROUTE` | 表达下一跳与路由原因 |
| 4 | 执行 | `EXECUTE` | 记录模型输出与用量 |
| 5 | 结束 | `FINISH` | 标记执行是否成功并携带结果 |

阶段枚举定义在 `backend/app/protocol/stages.py`，当前固定为 `INIT / RECEIVE / ROUTE / EXECUTE / FINISH`。

## 3. 标准事件类型

| 枚举成员 | 序列化值 | 说明 |
| --- | --- | --- |
| `AGENT_SPAWN` | `agent_spawn` | 创建或启动 Agent |
| `AGENT_CALL` | `agent_call` | 接收任务或执行调用 |
| `AGENT_FINISH` | `agent_finish` | 执行完成或流程结束 |
| `AGENT_REFLECT` | `agent_reflect` | 反思、决策或路由说明 |

事件类型定义在 `backend/app/protocol/events.py` 的 `EventType` 中。

## 4. `ProtocolEvent` 统一信封

所有协议事件都使用同一个信封模型：

```python
ProtocolEvent(
    protocol_stage=ProtocolStage,
    event_type=EventType,
    payload=<stage-specific payload model>,
    created_at=datetime,
)
```

字段约束如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `protocol_stage` | `ProtocolStage` | 五阶段之一 |
| `event_type` | `EventType` | 标准事件类型之一 |
| `payload` | `Any` | 运行时会校验为与 `protocol_stage` 匹配的 payload 模型 |
| `created_at` | `datetime` | 默认使用 timezone-aware UTC 当前时间 |

`ProtocolEvent` 在 `events.py` 中通过 `model_validator(mode="after")` 强制校验 `payload` 与阶段的对应关系：

- `INIT` 必须使用 `InitPayload`
- `RECEIVE` 必须使用 `ReceivePayload`
- `ROUTE` 必须使用 `RoutePayload`
- `EXECUTE` 必须使用 `ExecutePayload`
- `FINISH` 必须使用 `FinishPayload`

不匹配时会抛出 `ValidationError`。

## 5. 各阶段 payload

### `InitPayload`

| 字段 | 类型 | 必填 |
| --- | --- | --- |
| `agent_id` | `str` | 是 |
| `workflow_id` | `str` | 是 |

### `ReceivePayload`

| 字段 | 类型 | 必填 |
| --- | --- | --- |
| `task_input` | `dict` | 是 |

### `RoutePayload`

| 字段 | 类型 | 必填 |
| --- | --- | --- |
| `next_agent_id` | `str \| None` | 否 |
| `routing_reason` | `str \| None` | 否 |

### `ExecutePayload`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `agent_message` | `str` | 是 | 模型或 Agent 输出 |
| `prompt_tokens` | `int` | 是 | 输入 token 数 |
| `completion_tokens` | `int` | 是 | 输出 token 数 |
| `model` | `str` | 是 | 模型标识 |
| `model_cost_usd` | `float` | 是 | 调用成本 |

### `FinishPayload`

| 字段 | 类型 | 必填 |
| --- | --- | --- |
| `success` | `bool` | 是 |
| `output` | `dict \| None` | 否 |

## 6. 序列化格式

`backend/app/protocol/serializer.py` 提供两个函数：

- `to_payload(event)`：`ProtocolEvent -> dict[str, Any]`
- `from_payload(data)`：`dict[str, Any] -> ProtocolEvent`

当前实现采用扁平结构，不会嵌套 `payload` 子对象。以 `EXECUTE` 事件为例：

```json
{
  "agent_message": "分析完成",
  "prompt_tokens": 512,
  "completion_tokens": 128,
  "model": "gpt-4o",
  "model_cost_usd": 0.0032,
  "protocol_stage": "EXECUTE",
  "event_type": "agent_finish",
  "created_at": "2026-07-01T12:00:00+00:00"
}
```

信封保留字段为：

- `protocol_stage`
- `event_type`
- `created_at`

其余顶层字段都视为具体阶段 payload 的字段。

## 7. `created_at` 规则

当前实现对 `created_at` 有明确约束：

- `to_payload()` 输出 ISO 8601 字符串，保留时区信息
- `from_payload()` 要求输入必须是 timezone-aware ISO 字符串
- 如果输入时间没有时区信息，会抛出 `ValueError("created_at must be timezone-aware")`
- 反序列化成功后会统一归一化到 UTC

例如输入 `2026-07-01T20:00:00+08:00`，还原后的 `ProtocolEvent.created_at` 会变为 `2026-07-01T12:00:00+00:00`。

## 8. 公共导出

外部模块应优先从 `backend/app/protocol/__init__.py` 暴露的公共 API 导入：

```python
from app.protocol import (
    EventType,
    ExecutePayload,
    FinishPayload,
    InitPayload,
    ProtocolEvent,
    ProtocolStage,
    ReceivePayload,
    RoutePayload,
    from_payload,
    to_payload,
)
```

## 9. 扩展约束

- 新增阶段字段时，应同时更新对应的 payload 模型、序列化逻辑和文档
- 扩展字段优先保持向后兼容，避免破坏既有扁平结构
- 若新增阶段或事件类型，需要同步更新 `_PAYLOAD_CLS_MAP` 与相关校验/测试
