# M9 前端基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 NexusMesh 前端通信总线（WebSocket + REST）与应用外壳骨架，供 M10/M11/M12 业务模块零感知消费。

**Architecture:** 纯分层，依赖单向向下。`protocol.ts` 类型总线 → `ws.ts`（零 React 纯 TS，含指数退避 + 非重试关闭码熔断）→ `useWebSocket` → `useAgentStream`；REST 三文件复用 Phase 1 `http` 实例；布局层（AppShell/Topbar/Sidebar）对 WS 零感知。

**Tech Stack:** React 19 + TypeScript 5.8 + Vite 6 + react-router 7 + axios + TanStack Query + Zustand + Biome + vitest（新增）。

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `frontend/src/types/protocol.ts` | 类型总线：REST Request/Response + WS 协议 + WsClient/WsState 接口 |
| `frontend/src/api/ws.ts` | 纯 TS WebSocket 客户端（退避 + 熔断） |
| `frontend/src/api/ws.test.ts` | ws.ts 时序状态机单元测试 |
| `frontend/src/api/agents.ts` | Agent 5 REST 函数 |
| `frontend/src/api/workflows.ts` | Workflow 6 REST 函数（含 202 触发） |
| `frontend/src/api/executions.ts` | Execution 3 只读函数 |
| `frontend/src/hooks/useWebSocket.ts` | ws.ts 命令式 → React 响应式 |
| `frontend/src/hooks/useAgentStream.ts` | 组合 useWebSocket，聚合事件流 |
| `frontend/src/components/layout/AppShell.tsx` | 顶栏+侧边栏+Outlet 框架 |
| `frontend/src/components/layout/Topbar.tsx` | 顶部品牌栏 |
| `frontend/src/components/layout/Sidebar.tsx` | NavLink 导航 |
| `frontend/src/components/layout/layout.css` | 纯 CSS，`mesh-` 前缀 |
| `frontend/src/pages/agents/AgentsPage.tsx` | 路由骨架 |
| `frontend/src/pages/workflows/WorkflowsPage.tsx` | 路由骨架 |
| `frontend/src/pages/executions/ExecutionsPage.tsx` | 路由骨架 |
| `frontend/src/App.tsx` | 路由装配（修改） |
| `frontend/package.json` | 新增 test 脚本 + vitest/jsdom（修改） |
| `frontend/vite.config.ts` | 追加 vitest test 配置（修改） |

---

### Task 1: 类型总线 `protocol.ts`

**Files:**
- Create: `frontend/src/types/protocol.ts`

- [ ] **Step 1: 写完整类型定义**

```typescript
// frontend/src/types/protocol.ts

// ============ REST Request Types ============
export interface AgentRequest {
  name: string;
  description?: string;
  agent_type: string;
  llm_provider: string;
  llm_model: string;
  system_prompt?: string;
  config?: Record<string, unknown>;
}

export interface AgentUpdateRequest {
  name?: string | null;
  description?: string | null;
  agent_type?: string | null;
  llm_provider?: string | null;
  llm_model?: string | null;
  system_prompt?: string | null;
  config?: Record<string, unknown> | null;
}

export interface WorkflowRequest {
  name: string;
  description?: string;
  topology?: Record<string, unknown>;
}

export interface WorkflowUpdateRequest {
  name?: string | null;
  description?: string | null;
  topology?: Record<string, unknown> | null;
}

export interface TriggerRequest {
  task_input?: Record<string, unknown>;
}

// ============ REST Response Types ============
export interface AgentListItem {
  id: string;
  name: string;
  description: string | null;
  agent_type: string;
  llm_provider: string;
  llm_model: string;
  created_at: string;
}

export interface AgentResponse extends AgentListItem {
  system_prompt: string | null;
  config: Record<string, unknown>;
}

export interface WorkflowListItem {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface WorkflowResponse extends WorkflowListItem {
  topology: Record<string, unknown>;
}

export interface ExecutionListItem {
  id: string;
  workflow_id: string | null;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ExecutionResponse extends ExecutionListItem {
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface ExecutionAcceptedResponse {
  execution_id: string;
}

export interface TimelineEventResponse {
  id: string;
  execution_id: string | null;
  protocol_stage: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

// ============ WebSocket Protocol Types ============
export type ProtocolStage = 'INIT' | 'RECEIVE' | 'ROUTE' | 'EXECUTE' | 'FINISH';
export type ProtocolEventType = 'agent_spawn' | 'agent_call' | 'agent_finish' | 'agent_reflect';
export type StreamEventType = 'agent_chunk_stream';
export type EventType = ProtocolEventType | StreamEventType;

export interface InitWsEvent {
  protocol_stage: 'INIT';
  event_type: ProtocolEventType;
  created_at: string;
  agent_id: string;
  workflow_id: string;
}

export interface ReceiveWsEvent {
  protocol_stage: 'RECEIVE';
  event_type: ProtocolEventType;
  created_at: string;
  task_input: Record<string, unknown>;
}

export interface RouteWsEvent {
  protocol_stage: 'ROUTE';
  event_type: ProtocolEventType;
  created_at: string;
  next_agent_id: string | null;
  routing_reason: string | null;
}

export interface ExecuteWsEvent {
  protocol_stage: 'EXECUTE';
  event_type: ProtocolEventType;
  created_at: string;
  agent_message: string;
  prompt_tokens: number;
  completion_tokens: number;
  model: string;
  model_cost_usd: number;
}

export interface FinishWsEvent {
  protocol_stage: 'FINISH';
  event_type: ProtocolEventType;
  created_at: string;
  success: boolean;
  output: Record<string, unknown> | null;
}

export interface AgentChunkStreamEvent {
  event_type: 'agent_chunk_stream';
  agent_id: string;
  text: string;
  reasoning: boolean;
}

export type WebSocketEvent =
  | InitWsEvent
  | ReceiveWsEvent
  | RouteWsEvent
  | ExecuteWsEvent
  | FinishWsEvent
  | AgentChunkStreamEvent;

export type WsState = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WsClient {
  connect(executionId: string, token: string): void;
  disconnect(): void;
  onEvent(handler: (event: WebSocketEvent) => void): () => void;
  onStateChange(handler: (state: WsState) => void): () => void;
  getState(): WsState;
}
```

- [ ] **Step 2: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS（`tsc -b` 无类型错误）。此时 protocol.ts 为纯类型文件无副作用，build 通过。

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/types/protocol.ts
git commit -m "feat(M9): 前端协议类型总线 protocol.ts"
```

---

### Task 2: 安装 vitest 测试环境

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: 安装 vitest + jsdom**

Run: `cd frontend && pnpm add -D vitest jsdom`
Expected: `vitest` 与 `jsdom` 写入 devDependencies，`pnpm-lock.yaml` 更新。

- [ ] **Step 2: 新增 test 脚本到 package.json**

在 `scripts` 块追加 `test` 项，改后 `scripts` 为：

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "check": "biome check src",
    "test": "vitest run"
  },
```

（`vitest run` 单次执行不进 watch 模式，适合 CI 与本地一次性验证。）

- [ ] **Step 3: 追加 vitest 配置到 vite.config.ts**

改后完整文件：

```typescript
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173
  },
  test: {
    environment: "jsdom"
  }
});
```

- [ ] **Step 4: 冒烟验证 vitest 可运行**

创建临时文件 `frontend/src/smoke.test.ts`：

```typescript
import { expect, test } from 'vitest';

test('vitest 环境就绪', () => {
  expect(1 + 1).toBe(2);
});
```

Run: `cd frontend && pnpm run test`
Expected: PASS，1 passed。

- [ ] **Step 5: 暂留冒烟文件作为过渡期最小校验**

> `vitest run` 在零测试文件时会直接退出 1。为保证 Task 2 完成后 `pnpm run test` 仍可独立运行，保留 `frontend/src/smoke.test.ts` 直到 Task 3 的 `ws.test.ts` 落地，再由真实测试替换这份环境冒烟用例。

- [ ] **Step 6: Commit**

```bash
cd frontend && git add package.json pnpm-lock.yaml vite.config.ts src/smoke.test.ts
git commit -m "chore(M9): 接入 vitest + jsdom 测试环境"
```

---

### Task 3: WebSocket 客户端 `ws.ts`（TDD）

**Files:**
- Test: `frontend/src/api/ws.test.ts`
- Create: `frontend/src/api/ws.ts`
- Delete: `frontend/src/smoke.test.ts`（由真实 `ws.test.ts` 接棒后移除）

- [ ] **Step 1: 写失败测试 `ws.test.ts`**

测试用 mock 替换全局 `WebSocket`，用 `vi.useFakeTimers()` 驱动退避时间线。

```typescript
// frontend/src/api/ws.test.ts
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createWsClient } from './ws';
import type { WsState } from '../types/protocol';

// mock WebSocket：捕获实例，手动触发回调
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  close = vi.fn();
  url: string;
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
  static latest(): MockWebSocket {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
  static reset() {
    MockWebSocket.instances = [];
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.reset();
  vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('createWsClient', () => {
  test('connect 后 onopen 触发 state 变 connected', () => {
    const client = createWsClient();
    const states: WsState[] = [];
    client.onStateChange((s) => states.push(s));
    client.connect('exec-1', 'tok');
    expect(client.getState()).toBe('connecting');
    MockWebSocket.latest().onopen?.();
    expect(client.getState()).toBe('connected');
    expect(states).toEqual(['connecting', 'connected']);
  });

  test('URL 使用 window.location.host 默认分支且含路径与 token', () => {
    const client = createWsClient();
    client.connect('exec-9', 'jwt-x');
    expect(MockWebSocket.latest().url).toContain('/ws/executions/exec-9?token=jwt-x');
  });

  test('常规断线 (1006) 触发退避重连 1s->2s->4s', () => {
    const client = createWsClient();
    client.connect('exec-1', 'tok');
    MockWebSocket.latest().onopen?.();

    // 断线 1：等待 1s 后重连
    MockWebSocket.latest().onclose?.({ code: 1006 });
    expect(client.getState()).toBe('disconnected');
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances.length).toBe(1);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(2); // 第 2 次连接

    // 断线 2（未 onopen，退避翻倍到 2s）
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1999);
    expect(MockWebSocket.instances.length).toBe(2);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(3);

    // 断线 3（退避翻倍到 4s）
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(3999);
    expect(MockWebSocket.instances.length).toBe(3);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(4);
  });

  test('退避上限卡死 30s', () => {
    const client = createWsClient();
    client.connect('exec-1', 'tok');
    // 连续断线推高退避：1->2->4->8->16->32(capped 30)
    for (let i = 0; i < 6; i++) {
      MockWebSocket.latest().onclose?.({ code: 1006 });
      vi.advanceTimersByTime(30000);
    }
    const before = MockWebSocket.instances.length;
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(29999);
    expect(MockWebSocket.instances.length).toBe(before); // 30s 未到不重连
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(before + 1);
  });

  test('onopen 后再断线，退避已复位为 1s', () => {
    const client = createWsClient();
    client.connect('exec-1', 'tok');
    // 先断线两次推高退避
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000);
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(2000);
    // 第 3 次连接成功 → 复位
    MockWebSocket.latest().onopen?.();
    const before = MockWebSocket.instances.length;
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000); // 复位后应为 1s
    expect(MockWebSocket.instances.length).toBe(before + 1);
  });

  test('策略违规码 1008 触发熔断：state=error 且不重连', () => {
    const client = createWsClient();
    client.connect('exec-1', 'tok');
    MockWebSocket.latest().onopen?.();
    MockWebSocket.latest().onclose?.({ code: 1008 });
    expect(client.getState()).toBe('error');
    vi.advanceTimersByTime(60000);
    expect(MockWebSocket.instances.length).toBe(1); // 绝不重连
  });

  test('disconnect 清 timer 且后续不重连', () => {
    const client = createWsClient();
    client.connect('exec-1', 'tok');
    MockWebSocket.latest().onopen?.();
    client.disconnect();
    expect(client.getState()).toBe('disconnected');
    vi.advanceTimersByTime(60000);
    expect(MockWebSocket.instances.length).toBe(1);
  });

  test('onEvent 收到 message 并可 unsubscribe', () => {
    const client = createWsClient();
    const received: unknown[] = [];
    const unsub = client.onEvent((e) => received.push(e));
    client.connect('exec-1', 'tok');
    const payload = {
      protocol_stage: 'INIT',
      event_type: 'agent_spawn',
      created_at: 't',
      agent_id: 'agent-1',
      workflow_id: 'wf-1',
    };
    MockWebSocket.latest().onmessage?.({ data: JSON.stringify(payload) });
    expect(received).toHaveLength(1);
    unsub();
    MockWebSocket.latest().onmessage?.({ data: JSON.stringify(payload) });
    expect(received).toHaveLength(1); // unsubscribe 后不再收
  });

  test('脏 JSON 被静默丢弃不抛错', () => {
    const client = createWsClient();
    client.onEvent(() => {});
    client.connect('exec-1', 'tok');
    expect(() =>
      MockWebSocket.latest().onmessage?.({ data: 'not-json{' }),
    ).not.toThrow();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && pnpm run test`
Expected: FAIL —"Failed to resolve import './ws'"（ws.ts 尚不存在）。

- [ ] **Step 3: 实现 `ws.ts`**

```typescript
// frontend/src/api/ws.ts
import type { WebSocketEvent, WsClient, WsState } from '../types/protocol';

export function createWsClient(): WsClient {
  let socket: WebSocket | null = null;
  let currentState: WsState = 'disconnected';
  let currentExecutionId: string | null = null;
  let currentToken: string | null = null;
  let reconnectDelay = 1000;
  let reconnectTimer: number | null = null;

  const eventHandlers = new Set<(event: WebSocketEvent) => void>();
  const stateHandlers = new Set<(state: WsState) => void>();

  function changeState(nextState: WsState) {
    if (currentState === nextState) return;
    currentState = nextState;
    stateHandlers.forEach((handler) => handler(currentState));
  }

  function connect(executionId: string, token: string) {
    if (socket && currentExecutionId === executionId) return;
    disconnect();

    currentExecutionId = executionId;
    currentToken = token;
    changeState('connecting');

    const baseWsUrl = import.meta.env.VITE_WS_URL || `ws://${window.location.host}`;
    const wsUrl = `${baseWsUrl}/ws/executions/${executionId}?token=${token}`;
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      reconnectDelay = 1000;
      changeState('connected');
    };

    socket.onmessage = (event) => {
      try {
        const parsed: WebSocketEvent = JSON.parse(event.data);
        eventHandlers.forEach((handler) => handler(parsed));
      } catch {
        // 静默丢弃脏数据，保全管道通畅
      }
    };

    socket.onclose = (event) => {
      socket = null;
      if (event.code === 1008 || event.code >= 4000) {
        changeState('error');
        return;
      }
      if (currentState === 'disconnected') return;
      changeState('disconnected');
      reconnectTimer = window.setTimeout(() => {
        if (currentExecutionId && currentToken) {
          reconnectDelay = Math.min(30000, reconnectDelay * 2);
          connect(currentExecutionId, currentToken);
        }
      }, reconnectDelay);
    };
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    currentExecutionId = null;
    currentToken = null;
    if (socket) {
      const tempSocket = socket;
      socket = null;
      changeState('disconnected');
      tempSocket.close();
    } else {
      changeState('disconnected');
    }
  }

  return {
    connect,
    disconnect,
    onEvent: (handler) => {
      eventHandlers.add(handler);
      return () => eventHandlers.delete(handler);
    },
    onStateChange: (handler) => {
      stateHandlers.add(handler);
      return () => stateHandlers.delete(handler);
    },
    getState: () => currentState,
  };
}
```

> 注意重连回调里 `reconnectDelay = Math.min(30000, reconnectDelay * 2)` 在下一次 connect 前翻倍。测试用例的退避断言（1s→2s→4s）据此校准：首断线用初始 1000ms 排程，重连回调触发时才翻倍到 2000，故第二次断线等 2s。当前后端明确返回的非重试关闭码为 `1008`（token 非法）；前端同时兼容未来可能出现的 `4xxx` 应用级关闭码。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && pnpm run test`
Expected: PASS，全部用例通过。

- [ ] **Step 5: 移除过渡 smoke test**

Run: `cd frontend && rm src/smoke.test.ts && pnpm run test`
Expected: PASS（`ws.test.ts` 已接棒，删除 smoke 后测试仍全部通过）。

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/api/ws.ts src/api/ws.test.ts src/smoke.test.ts
git commit -m "feat(M9): WebSocket 客户端 ws.ts（退避+熔断）+ 单元测试"
```

---

### Task 4: REST 客户端三文件

**Files:**
- Create: `frontend/src/api/agents.ts`
- Create: `frontend/src/api/workflows.ts`
- Create: `frontend/src/api/executions.ts`

> 这三个文件是 `http` 实例的薄类型封装，由 Tier 1 静态验证（`tsc -b`）保证正确性，不写单元测试（避免只测 axios mock 的空转，符合 YAGNI）。

- [ ] **Step 1: 创建 `agents.ts`**

```typescript
// frontend/src/api/agents.ts
import { http } from './http';
import type {
  AgentRequest,
  AgentUpdateRequest,
  AgentListItem,
  AgentResponse,
} from '../types/protocol';

export const agentsApi = {
  list: (limit = 20, offset = 0) =>
    http.get<AgentListItem[]>('/agents', { params: { limit, offset } }).then((r) => r.data),
  get: (id: string) =>
    http.get<AgentResponse>(`/agents/${id}`).then((r) => r.data),
  create: (payload: AgentRequest) =>
    http.post<AgentResponse>('/agents', payload).then((r) => r.data),
  update: (id: string, payload: AgentUpdateRequest) =>
    http.patch<AgentResponse>(`/agents/${id}`, payload).then((r) => r.data),
  delete: (id: string) =>
    http.delete(`/agents/${id}`).then(() => undefined),
};
```

- [ ] **Step 2: 创建 `workflows.ts`**

```typescript
// frontend/src/api/workflows.ts
import { http } from './http';
import type {
  WorkflowRequest,
  WorkflowUpdateRequest,
  TriggerRequest,
  WorkflowListItem,
  WorkflowResponse,
  ExecutionAcceptedResponse,
} from '../types/protocol';

export const workflowsApi = {
  list: (limit = 20, offset = 0) =>
    http.get<WorkflowListItem[]>('/workflows', { params: { limit, offset } }).then((r) => r.data),
  get: (id: string) =>
    http.get<WorkflowResponse>(`/workflows/${id}`).then((r) => r.data),
  create: (payload: WorkflowRequest) =>
    http.post<WorkflowResponse>('/workflows', payload).then((r) => r.data),
  update: (id: string, payload: WorkflowUpdateRequest) =>
    http.patch<WorkflowResponse>(`/workflows/${id}`, payload).then((r) => r.data),
  delete: (id: string) =>
    http.delete(`/workflows/${id}`).then(() => undefined),
  trigger: (id: string, payload: TriggerRequest) =>
    http.post<ExecutionAcceptedResponse>(`/workflows/${id}/execute`, payload).then((r) => r.data),
};
```

- [ ] **Step 3: 创建 `executions.ts`**

```typescript
// frontend/src/api/executions.ts
import { http } from './http';
import type {
  ExecutionListItem,
  ExecutionResponse,
  TimelineEventResponse,
} from '../types/protocol';

export interface ExecutionListParams {
  workflow_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const executionsApi = {
  list: (params: ExecutionListParams = {}) =>
    http
      .get<ExecutionListItem[]>('/executions', { params: { limit: 20, offset: 0, ...params } })
      .then((r) => r.data),
  get: (id: string) =>
    http.get<ExecutionResponse>(`/executions/${id}`).then((r) => r.data),
  timeline: (id: string) =>
    http.get<TimelineEventResponse[]>(`/executions/${id}/timeline`).then((r) => r.data),
};
```

- [ ] **Step 4: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS（三文件类型与 protocol.ts 咬合无误）。

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/api/agents.ts src/api/workflows.ts src/api/executions.ts
git commit -m "feat(M9): REST 客户端三文件（agents/workflows/executions）"
```

---

### Task 5: React Hooks

**Files:**
- Create: `frontend/src/hooks/useWebSocket.ts`
- Create: `frontend/src/hooks/useAgentStream.ts`

> Hooks 为 ws.ts 的薄 React 封装。核心时序逻辑已在 Task 3 的 ws.test.ts 全覆盖；Hooks 由 `tsc -b` 编译校验 + Task 8 手动 dev 验证（未引入 @testing-library，符合 YAGNI）。

- [ ] **Step 1: 创建 `useWebSocket.ts`**

```typescript
// frontend/src/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from 'react';
import { createWsClient } from '../api/ws';
import type { WsClient, WsState, WebSocketEvent } from '../types/protocol';

interface UseWebSocketOptions {
  executionId: string;
  token: string | null;
  onEvent?: (event: WebSocketEvent) => void;
}

interface UseWebSocketResult {
  state: WsState;
}

export function useWebSocket(
  { executionId, token, onEvent }: UseWebSocketOptions,
): UseWebSocketResult {
  const [state, setState] = useState<WsState>('disconnected');
  const clientRef = useRef<WsClient | null>(null);
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!token) return;
    const client = createWsClient();
    clientRef.current = client;
    const unsubState = client.onStateChange(setState);
    const unsubEvent = client.onEvent((ev) => onEventRef.current?.(ev));
    client.connect(executionId, token);
    return () => {
      unsubState();
      unsubEvent();
      client.disconnect();
      clientRef.current = null;
    };
  }, [executionId, token]);

  return { state };
}
```

- [ ] **Step 2: 创建 `useAgentStream.ts`**

```typescript
// frontend/src/hooks/useAgentStream.ts
import { useCallback, useEffect, useState } from 'react';
import { useWebSocket } from './useWebSocket';
import type { ProtocolStage, WebSocketEvent, WsState } from '../types/protocol';

interface UseAgentStreamOptions {
  executionId: string;
  token: string | null;
}

interface AgentStreamState {
  wsState: WsState;
  events: WebSocketEvent[];
  currentStage: ProtocolStage | null;
}

export function useAgentStream(
  { executionId, token }: UseAgentStreamOptions,
): AgentStreamState {
  const [events, setEvents] = useState<WebSocketEvent[]>([]);
  const [currentStage, setCurrentStage] = useState<ProtocolStage | null>(null);

  useEffect(() => {
    setEvents([]);
    setCurrentStage(null);
  }, [executionId]);

  const onEvent = useCallback((event: WebSocketEvent) => {
    if (event.event_type !== 'agent_chunk_stream') {
      setCurrentStage(event.protocol_stage);
    }
    setEvents((prev) => [...prev, event]);
  }, []);

  const { state: wsState } = useWebSocket({ executionId, token, onEvent });
  return { wsState, events, currentStage };
}
```

- [ ] **Step 3: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/hooks/useWebSocket.ts src/hooks/useAgentStream.ts
git commit -m "feat(M9): useWebSocket + useAgentStream hooks"
```

---

### Task 6: 布局组件 + CSS

**Files:**
- Create: `frontend/src/components/layout/AppShell.tsx`
- Create: `frontend/src/components/layout/Topbar.tsx`
- Create: `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/components/layout/layout.css`

- [ ] **Step 1: 创建 `layout.css`**

```css
/* frontend/src/components/layout/layout.css */
.mesh-app-shell { display: flex; flex-direction: column; height: 100vh; }

.mesh-topbar {
  display: flex; align-items: center; height: 56px; padding: 0 20px;
  background: #1a1d24; color: #fff; flex-shrink: 0;
}
.mesh-topbar-brand { font-size: 18px; font-weight: 600; }

.mesh-app-body { display: flex; flex: 1; min-height: 0; }

.mesh-sidebar {
  width: 220px; background: #f4f5f7; border-right: 1px solid #e0e2e7; flex-shrink: 0;
}
.mesh-sidebar-nav { list-style: none; margin: 0; padding: 12px 0; }
.mesh-sidebar-link {
  display: block; padding: 10px 20px; color: #3c4149; text-decoration: none;
}
.mesh-sidebar-link:hover { background: #e9ebef; }
.mesh-sidebar-link--active {
  background: #e4e9ff; color: #2f54eb; font-weight: 600; border-right: 3px solid #2f54eb;
}

.mesh-app-main { flex: 1; padding: 24px; overflow: auto; }
```

- [ ] **Step 2: 创建 `Topbar.tsx`**

```tsx
// frontend/src/components/layout/Topbar.tsx
export function Topbar() {
  return (
    <header className="mesh-topbar">
      <span className="mesh-topbar-brand">NexusMesh</span>
    </header>
  );
}
```

- [ ] **Step 3: 创建 `Sidebar.tsx`**

```tsx
// frontend/src/components/layout/Sidebar.tsx
import { NavLink } from 'react-router';

const NAV_ITEMS = [
  { to: '/agents', label: 'Agents' },
  { to: '/workflows', label: 'Workflows' },
  { to: '/executions', label: 'Executions' },
] as const;

export function Sidebar() {
  return (
    <nav className="mesh-sidebar">
      <ul className="mesh-sidebar-nav">
        {NAV_ITEMS.map(({ to, label }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) =>
                isActive ? 'mesh-sidebar-link mesh-sidebar-link--active' : 'mesh-sidebar-link'
              }
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 4: 创建 `AppShell.tsx`**

```tsx
// frontend/src/components/layout/AppShell.tsx
import { Outlet } from 'react-router';
import { Topbar } from './Topbar';
import { Sidebar } from './Sidebar';
import './layout.css';

export function AppShell() {
  return (
    <div className="mesh-app-shell">
      <Topbar />
      <div className="mesh-app-body">
        <Sidebar />
        <main className="mesh-app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/components/layout/
git commit -m "feat(M9): AppShell 布局组件（顶栏+侧边栏）"
```

---

### Task 7: 骨架页面 + 路由装配

**Files:**
- Create: `frontend/src/pages/agents/AgentsPage.tsx`
- Create: `frontend/src/pages/workflows/WorkflowsPage.tsx`
- Create: `frontend/src/pages/executions/ExecutionsPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 创建三个骨架页面**

```tsx
// frontend/src/pages/agents/AgentsPage.tsx
export default function AgentsPage() {
  return <h1>Agents</h1>;
}
```

```tsx
// frontend/src/pages/workflows/WorkflowsPage.tsx
export default function WorkflowsPage() {
  return <h1>Workflows</h1>;
}
```

```tsx
// frontend/src/pages/executions/ExecutionsPage.tsx
export default function ExecutionsPage() {
  return <h1>Executions</h1>;
}
```

- [ ] **Step 2: 修改 `App.tsx` 装配路由**

改后完整文件：

```tsx
// frontend/src/App.tsx
import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/layout/AppShell";
import AgentsPage from "./pages/agents/AgentsPage";
import ExecutionsPage from "./pages/executions/ExecutionsPage";
import WorkflowsPage from "./pages/workflows/WorkflowsPage";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route element={<AppShell />}>
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/executions" element={<ExecutionsPage />} />
      </Route>
      <Route path="*" element={<Navigate replace to="/agents" />} />
    </Routes>
  );
}
```

- [ ] **Step 3: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/pages/agents src/pages/workflows src/pages/executions src/App.tsx
git commit -m "feat(M9): 三条路由骨架 + AppShell 路由装配"
```

---

### Task 8: 全量验证与收口

**Files:** 无新增，全链路验证。

- [ ] **Step 1: 运行全部单元测试**

Run: `cd frontend && pnpm run test`
Expected: PASS，ws.test.ts 全部用例通过。

- [ ] **Step 2: 构建 + 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS，`tsc -b` 无类型错误，vite build 产物生成。

- [ ] **Step 3: Biome lint/format**

Run: `cd frontend && pnpm run check`
Expected: PASS。若有格式问题，运行 `pnpm exec biome check --write src` 修复后重跑。

- [ ] **Step 4: 手动 dev 验证（人工确认）**

Run: `cd frontend && pnpm run dev`
手动检查清单：
- 访问 `/` → 自动重定向到 `/agents`
- 顶栏显示 "NexusMesh"，左侧边栏三项导航
- 点击 Agents/Workflows/Executions → 主内容区标题切换，URL 变化
- 当前项 NavLink 呈激活样式（蓝底 + 右侧蓝边）
- 浏览器缩放 / 窗口拉伸，布局不崩塌（侧边栏固定 220px，主区滚动）

停止 dev：Ctrl+C。

- [ ] **Step 5: 若 Biome 有自动修复产生的改动则提交**

```bash
cd frontend && git status
# 如有格式化改动：
git add -A && git commit -m "style(M9): biome 格式化收口"
```

---

## Self-Review

**Spec 覆盖核对：**
- §2 文件矩阵 18 项 → Task 1（protocol）/ Task 3（ws + test）/ Task 4（REST×3）/ Task 5（hooks×2）/ Task 6（layout×4）/ Task 7（pages×3 + App）/ Task 2（package.json + vite.config）全覆盖 ✅
- §3 类型总线 → Task 1 完整定义 ✅
- §4 ws.ts 退避+熔断 → Task 3 实现 + 测试 ✅
- §5 REST 三文件 → Task 4 ✅
- §6 两 Hooks → Task 5 ✅
- §7 布局四组件 → Task 6 ✅
- §8 路由装配 → Task 7 ✅
- §9 双层验证（Tier 1 build/check + Tier 2 vitest）→ Task 2 + Task 3 + Task 8 ✅
- §9.2 全部 7 类 WS 测试用例 → Task 3 Step 1 逐一落地 ✅

**类型一致性核对：**
- `createWsClient` / `WsClient` / `WsState` / `WebSocketEvent` / `ProtocolStage` / `EventType` 跨 Task 1/3/5 命名一致 ✅
- `agentsApi` / `workflowsApi` / `executionsApi` 导出名与 spec §5 一致 ✅
- `useWebSocket` / `useAgentStream` 参数对象签名跨 Task 5 一致 ✅
- `mesh-` 前缀 CSS 类名在 Task 6 组件与 layout.css 间一一对应 ✅

**Placeholder 扫描：** 无 TBD/TODO/"类似 Task N"，每个代码步骤含完整代码 ✅
