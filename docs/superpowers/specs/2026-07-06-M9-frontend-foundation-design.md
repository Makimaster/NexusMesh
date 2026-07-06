# M9 前端基础设施 — 详细设计方案

> 状态：待实现
> 日期：2026-07-06
> 依赖：M2（协议类型）、M4（WebSocket 路由 `/ws/executions/{id}` 与事件广播）、M8（14 个 REST 端点契约）
> 定位：前端通信总线底座 + 应用外壳骨架，Phase 4 前端第一块基石

---

## 1. 设计目标与边界

M9 是 NexusMesh 前端的 **通信与布局基础设施层**，为 Phase 4 后续业务模块（M10 画布 / M11 工作流编辑 / M12 执行回溯）提供两条锁死的底座：

1. **双轨通信总线**：实时流轨（WebSocket）+ REST 轨（Axios），业务层"零感知"直接消费。
2. **应用外壳骨架**：顶栏 + 左侧边栏 + 三条路由骨架（agents / workflows / executions），实现"盲插"体验——M10/M11/M12 直接填充房间，无需回头改全局路由表或通信层。

### 1.1 核心架构原则：纯分层，依赖单向向下

采用**纯分层架构**（评审锁定方案 A），依赖严格单向，禁止反向越界：

```
【实时流轨】: protocol.ts ──> ws.ts ──> useWebSocket ──> useAgentStream
【REST 轨】 : protocol.ts ──> api/{agents,workflows,executions}.ts ──> (未来业务组件)
【布局轨】  : AppShell / Topbar / Sidebar（仅依赖 react-router，对 WS 体系零感知）
```

关键红利：`ws.ts` 为**零 React 依赖的纯 TypeScript 模块**，原生 Socket 生命周期与 DOM/React 重绘彻底解耦，既避免"断线闪烁 Bug"，又让重连/熔断逻辑可脱离组件独立单元测试。

### 1.2 明确不做（YAGNI 边界）

- 不接真实 JWT 登录（沿用 Phase 1 占位符 token；真实鉴权由后续模块接入）
- 不做 WS 心跳 ping/pong（后端 M4 不要求）
- 不做 WS 消息队列缓冲、重连次数上限（仅退避时间上限 30s）
- 不做 REST 分页 `total` 计数（对齐 M8，仅 limit/offset）
- 不引入 CSS 框架 / CSS Modules（延续 Phase 1 纯 CSS，`mesh-` 前缀作命名空间隔离）
- 三个骨架页面仅占位标题，业务内容由 M10/M11/M12 各自填充

---

## 2. 文件矩阵

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/types/protocol.ts` | **新建** | 类型总线：REST Request/Response + WS 协议类型 + WsClient/WsState 接口 |
| `frontend/src/api/ws.ts` | **新建** | 纯 TS WebSocket 客户端 + 指数退避 + 非重试关闭码熔断 |
| `frontend/src/api/agents.ts` | **新建** | Agent 5 个强类型 REST 函数 |
| `frontend/src/api/workflows.ts` | **新建** | Workflow 6 个 REST 函数（含 1 个 202 异步触发） |
| `frontend/src/api/executions.ts` | **新建** | Execution 3 个只读查询函数 |
| `frontend/src/hooks/useWebSocket.ts` | **新建** | React 层，映射 ws.ts 命令式接口为响应式状态 |
| `frontend/src/hooks/useAgentStream.ts` | **新建** | 组合 useWebSocket，聚合事件流为结构化状态 |
| `frontend/src/components/layout/AppShell.tsx` | **新建** | 顶栏 + 侧边栏 + `<Outlet />` 主内容框架 |
| `frontend/src/components/layout/Topbar.tsx` | **新建** | 顶部品牌栏（占位） |
| `frontend/src/components/layout/Sidebar.tsx` | **新建** | 左侧 NavLink 导航，激活样式联动 |
| `frontend/src/components/layout/layout.css` | **新建** | 纯 CSS，`mesh-` 前缀命名空间 |
| `frontend/src/pages/agents/AgentsPage.tsx` | **新建** | 路由骨架（占位标题） |
| `frontend/src/pages/workflows/WorkflowsPage.tsx` | **新建** | 路由骨架（占位标题） |
| `frontend/src/pages/executions/ExecutionsPage.tsx` | **新建** | 路由骨架（占位标题） |
| `frontend/src/api/ws.test.ts` | **新建** | vitest：退避 + 熔断时序状态机测试 |
| `frontend/src/App.tsx` | **修改** | 接入 AppShell 布局路由 + 三条子路由 + 默认重定向改 `/agents` |
| `frontend/package.json` | **修改** | 新增 `test` 脚本 + `vitest`/`jsdom` devDependency |
| `frontend/vite.config.ts` | **修改** | 追加 vitest test 配置块（`environment: 'jsdom'`） |

`api/http.ts`、`stores/sessionStore.ts`、`main.tsx`、`pages/Login.tsx`、`pages/Dashboard.tsx` 保持不动（外科手术原则）。

---

## 3. 类型总线（`types/protocol.ts`）

前端类型单一权威，镜像后端 M7/M8 Schema + M4 WS 协议。

### 3.1 REST Request 类型（对齐 M7 Pydantic 类名，无 `Create` 冗余字眼）

```typescript
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
```

### 3.2 REST Response 类型（1:1 咬合 M8 Response Schema，含继承关系）

```typescript
export interface AgentListItem {
  id: string;              // UUID → string
  name: string;
  description: string | null;
  agent_type: string;
  llm_provider: string;
  llm_model: string;
  created_at: string;      // ISO 8601 datetime
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
  workflow_id: string | null;   // ORM ondelete=SET NULL
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
  execution_id: string | null;  // ORM ondelete=SET NULL
  protocol_stage: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}
```

### 3.3 WebSocket 协议类型（五阶段 + 事件流 + 客户端接口）

```typescript
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

### 3.4 类型映射约定

| 后端类型 | 前端类型 | 理由 |
|----------|----------|------|
| `uuid.UUID` | `string` | JSON 传输标准 |
| `datetime` | `string` | ISO 8601，FastAPI 自动序列化 |
| `dict` | `Record<string, unknown>` | 强制消费端显式收窄，拒绝 `any` |
| `X \| None`（nullable） | `X \| null` | 精确对齐 ORM nullable / SET NULL |

---

## 4. WebSocket 客户端（`api/ws.ts`）

纯 TS，管理 WS 生命周期，零 React 依赖。仅导出工厂函数 `createWsClient()`（类型定义在 `protocol.ts`）。

### 4.1 三大行为规范

**连接 URL（动态解析，禁止硬编码）**：
```typescript
const baseWsUrl = import.meta.env.VITE_WS_URL || `ws://${window.location.host}`;
const wsUrl = `${baseWsUrl}/ws/executions/${executionId}?token=${token}`;
```
JWT 经 query param 传递；前端订阅的是真实 WebSocket 路由，Redis `execution:{id}` 频道仅为后端内部广播实现细节，不透传给浏览器。

**指数退避重连（评审锁定 Q4=A）**：
```
尝试 → 等 1s → 尝试 → 等 2s → 等 4s → 等 8s → ... → 上限 30s
连接成功（onopen）→ 退避计数器复位为 1000
disconnect() 主动断开 → 停止重连
```

**非重试关闭码熔断**：当前后端对非法 token 明确返回 `1008`（Policy Violation）；前端同时兼容未来可能出现的 `4xxx` 应用级关闭码。`onclose` 判 `event.code === 1008 || event.code >= 4000` → 状态跃迁 `error`，彻底掐断 setTimeout 重连。仅常规断线（如 1006）才允许退避重连。

### 4.2 状态机（4 态单向流转）

```
disconnected → connecting → connected
                    ↑            ↓
                    └─ (退避重连) ┘（常规断线）
     任意态 ──(code=1008 或 code≥4000)──> error（不可恢复，对外暴露，不重连）
```

### 4.3 完整实现

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

> `disconnect()` 双重保护：`changeState('disconnected')` 先于 `tempSocket.close()`，故 `onclose` 触发时 `currentState === 'disconnected'` 直接 early return，永不误触发重连。
> Task 3 的真实 `ws.test.ts` 落地后，应删除 Task 2 过渡期的 `frontend/src/smoke.test.ts`，避免测试套件长期保留无业务价值的占位用例。

---

## 5. REST API 客户端三文件

**共同约定**：全部依赖 Phase 1 已有 `http` 实例（`api/http.ts`）；`.then(r => r.data)` 剥离 Axios 包装；错误交给 TanStack Query 的 `onError`，函数内不捕获；分页默认 `limit=20, offset=0`（对齐 M8）。

### 5.1 `api/agents.ts`（5 函数）

```typescript
import { http } from './http';
import type {
  AgentRequest, AgentUpdateRequest, AgentListItem, AgentResponse,
} from '../types/protocol';

export const agentsApi = {
  list: (limit = 20, offset = 0) =>
    http.get<AgentListItem[]>('/agents', { params: { limit, offset } }).then(r => r.data),
  get: (id: string) =>
    http.get<AgentResponse>(`/agents/${id}`).then(r => r.data),
  create: (payload: AgentRequest) =>
    http.post<AgentResponse>('/agents', payload).then(r => r.data),
  update: (id: string, payload: AgentUpdateRequest) =>
    http.patch<AgentResponse>(`/agents/${id}`, payload).then(r => r.data),
  delete: (id: string) =>
    http.delete(`/agents/${id}`).then(() => undefined),
};
```

### 5.2 `api/workflows.ts`（6 函数，含 202 触发）

```typescript
import { http } from './http';
import type {
  WorkflowRequest, WorkflowUpdateRequest, TriggerRequest,
  WorkflowListItem, WorkflowResponse, ExecutionAcceptedResponse,
} from '../types/protocol';

export const workflowsApi = {
  list: (limit = 20, offset = 0) =>
    http.get<WorkflowListItem[]>('/workflows', { params: { limit, offset } }).then(r => r.data),
  get: (id: string) =>
    http.get<WorkflowResponse>(`/workflows/${id}`).then(r => r.data),
  create: (payload: WorkflowRequest) =>
    http.post<WorkflowResponse>('/workflows', payload).then(r => r.data),
  update: (id: string, payload: WorkflowUpdateRequest) =>
    http.patch<WorkflowResponse>(`/workflows/${id}`, payload).then(r => r.data),
  delete: (id: string) =>
    http.delete(`/workflows/${id}`).then(() => undefined),
  trigger: (id: string, payload: TriggerRequest) =>
    http.post<ExecutionAcceptedResponse>(`/workflows/${id}/execute`, payload).then(r => r.data),
};
```

> `trigger` → 202 Accepted 由 Axios 默认 2xx 判定正常解析，无需 `validateStatus`。返回 `execution_id` 后前端连接 `/ws/executions/{id}?token=...` 订阅实时流。

### 5.3 `api/executions.ts`（3 只读函数）

```typescript
import { http } from './http';
import type {
  ExecutionListItem, ExecutionResponse, TimelineEventResponse,
} from '../types/protocol';

export interface ExecutionListParams {
  workflow_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const executionsApi = {
  list: (params: ExecutionListParams = {}) =>
    http.get<ExecutionListItem[]>('/executions', {
      params: { limit: 20, offset: 0, ...params },
    }).then(r => r.data),
  get: (id: string) =>
    http.get<ExecutionResponse>(`/executions/${id}`).then(r => r.data),
  timeline: (id: string) =>
    http.get<TimelineEventResponse[]>(`/executions/${id}/timeline`).then(r => r.data),
};
```

> `workflow_id` / `status` 为可选过滤器（对齐 M8 `Query(None)`）；4 个可选参数用对象封装，优于位置参数；`status` 保持 `string`（M8 本期未枚举化）。

---

## 6. React Hooks

### 6.1 `hooks/useWebSocket.ts`

将 `ws.ts` 命令式接口映射为响应式状态。

```typescript
import { useEffect, useRef, useState } from 'react';
import { createWsClient } from '../api/ws';
import type { WsClient, WsState, WebSocketEvent } from '../types/protocol';

interface UseWebSocketOptions {
  executionId: string;
  token: string | null;   // null = 跳过连接（token 未就绪）
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

  useEffect(() => { onEventRef.current = onEvent; }, [onEvent]);

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

关键决策：`clientRef` 存实例不入 state（变更不触发 re-render）；`onEventRef` 稳定引用避免 handler 引用变化重建连接（断线闪烁 Bug 根治）；`token: null` 守门兼容 Phase 1 占位符→真实 JWT 过渡期时序。

### 6.2 `hooks/useAgentStream.ts`

组合 `useWebSocket`，聚合事件流为结构化状态。

```typescript
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

关键决策：`events` append-only（对齐后端事件流仅追加语义）；`currentStage` 仅由五阶段协议事件推进，`agent_chunk_stream` token 流不覆盖阶段状态；`executionId` 变更时 reset 防止污染新任务事件流；`useCallback([])` 配合 `onEventRef` 双重稳定。

---

## 7. 应用外壳布局（`components/layout/`）

评审锁定 Q1=A（顶栏 + 左侧边栏），Q5=A（纯 CSS + `mesh-` 前缀命名空间）。

### 7.1 `AppShell.tsx`

```tsx
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

### 7.2 `Topbar.tsx`

```tsx
export function Topbar() {
  return (
    <header className="mesh-topbar">
      <span className="mesh-topbar-brand">NexusMesh</span>
    </header>
  );
}
```

### 7.3 `Sidebar.tsx`

```tsx
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

> `<Outlet />` 承载子路由；`NavLink` 的 `isActive` 回调驱动激活样式；`NAV_ITEMS as const` 不可变元组，扩展导航只改此一处。

### 7.4 `layout.css`

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

---

## 8. 路由装配（`App.tsx` 修改）

外科手术式修改：保留 `/login` `/dashboard`，新增 AppShell 布局路由包裹三条子路由，默认重定向改 `/agents`。

```tsx
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

三个骨架页面（占位标题，业务由 M10/M11/M12 填充）：

```tsx
// pages/agents/AgentsPage.tsx
export default function AgentsPage() { return <h1>Agents</h1>; }
// pages/workflows/WorkflowsPage.tsx
export default function WorkflowsPage() { return <h1>Workflows</h1>; }
// pages/executions/ExecutionsPage.tsx
export default function ExecutionsPage() { return <h1>Executions</h1>; }
```

> `<Route element={<AppShell />}>` 无 path，仅作布局包裹；子路由内容渲染进 AppShell 的 `<Outlet />`。

---

## 9. 验证策略与 DoD 闭环

DoD 原文：**"WS 连接/重连 + REST 数据获取 hook 有测试或最小可运行验证；协议类型与后端无偏差"**

`ws.ts` 纯 TS 设计让重连/熔断逻辑可脱离 React 独立测试。分两层验证：

### 9.1 Tier 1 — 零依赖静态验证（必做）

| 命令 | 验证目标 | DoD 对应 |
|------|---------|---------|
| `pnpm run build`（`tsc -b && vite build`） | 类型编译 + 全链路构建通过；protocol.ts 与消费端类型无偏差 | "协议类型与后端无偏差" + "最小可运行验证" |
| `pnpm run check`（`biome check src`） | lint + format | 代码规范 |
| 手动 `pnpm run dev` | 三骨架页面切换、NavLink 激活样式联动、布局不崩塌 | 路由与视觉验证 |

> 本项目无独立 `type-check` 脚本，类型校验已内置于 `build` 的 `tsc -b`；linter 为 Biome（非 ESLint）。

### 9.2 Tier 2 — WS 核心逻辑单元测试（vitest，评审锁定纳入）

`ws.ts` 的指数退避 + 非重试关闭码熔断是最高风险时序逻辑，用 `vitest` + `vi.useFakeTimers()` 兜底。

**新增依赖与配置**：
- `package.json` devDependency：`vitest`、`jsdom`；新增脚本 `"test": "vitest"`
- `vite.config.ts` 追加 `test: { environment: 'jsdom' }` 配置块（复用现有 Vite 配置，无独立 vitest.config.ts）
- `frontend/src/smoke.test.ts` 作为 Task 2→Task 3 过渡期的最小冒烟校验，待 `ws.test.ts` 落地后可移除

**`api/ws.test.ts` 核心用例**：

| 用例 | 断言 |
|------|------|
| connect → mock `WebSocket.onopen` | state 变 `connected` |
| onclose(code=1006) | 触发重连，退避严格 1s→2s→4s 翻倍 |
| 退避上限 | 多次重连后延迟卡死 30s，不超出 |
| onopen 后再断线 | `reconnectDelay` 已复位为 1000 |
| onclose(code=1008) | state 跃迁 `error`，绝不触发任何 setTimeout 重连（熔断） |
| disconnect() | 清 timer；后续 onclose 不触发重连 |
| onStateChange / onEvent | 注册触发正确，返回的 unsubscribe 生效 |

### 9.3 测试环境注意事项

- `vi.useFakeTimers()` 驱动 setTimeout 虚拟时间线，毫秒级跑完 30s 退避序列
- mock 全局 `WebSocket`：手动触发 `onopen` / `onclose` / `onmessage` 回调验证状态机
- mock `import.meta.env.VITE_WS_URL` 或依赖 `window.location.host` 默认分支

---

## 10. 依赖关系与"盲插"契约

M9 交付后，M10/M11/M12 的消费方式（零 WS/Axios 感知）：

```typescript
// 实时流消费（M10 画布 / M12 回溯）
const { wsState, events, currentStage } = useAgentStream({
  executionId: params.id,
  token: useSessionStore((s) => s.accessToken),
});

// REST 消费（M10/M11 列表与详情）
const agents = await agentsApi.list();
const execId = await workflowsApi.trigger(wfId, { task_input: {...} });
```

新增顶级导航只需向 `Sidebar.tsx` 的 `NAV_ITEMS` 追加一项 + `App.tsx` 追加一条子路由，全局路由表与通信层零改动。

---

## 11. 设计自审清单

| 检查项 | 结论 |
|--------|------|
| REST Response 类型 1:1 咬合 M8 Schema（含继承） | ✅ 逐字段核对 §3.2 |
| nullable 字段（`workflow_id`/`execution_id` SET NULL）反映为 `\| null` | ✅ |
| Request 类型命名对齐后端 Pydantic（无 `Create` 冗余） | ✅ `AgentRequest`/`WorkflowRequest` |
| `dict` → `Record<string, unknown>`，杜绝 `any` | ✅ |
| WS URL 动态解析，无硬编码 localhost | ✅ `VITE_WS_URL` fallback |
| 1008 / 4xxx 非重试关闭码熔断，防无效凭证死循环重连 | ✅ §4.1 |
| `onStateChange` 补齐响应式链路（getState 不驱动 re-render） | ✅ |
| `onEventRef` 稳定引用，根治断线闪烁 | ✅ §6.1 |
| 依赖单向向下，布局层对 WS 零感知 | ✅ §1.1 |
| CSS `mesh-` 前缀命名空间隔离 | ✅ §7.4 |
| 工具链命令对齐真实 package.json（pnpm/Biome/tsc -b） | ✅ §9.1 |
| 外科手术：http.ts/sessionStore/main.tsx/Login/Dashboard 不动 | ✅ §2 |
| YAGNI：不接 JWT、无心跳、无缓冲、骨架页仅占位 | ✅ §1.2 |
