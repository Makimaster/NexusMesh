# M10 AgentCanvas 拓扑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建实时 Agent 协作拓扑画布，事件驱动增量渲染节点/边，含执行列表入口。

**Architecture:** 纯函数归约器 `reduceEvents(events[]) → {nodes, edges}`，useMemo 包装 + dagre 层次布局，React Flow 渲染；执行列表页 + 画布详情页（`/executions/:id`）；已完成执行显示提示不连 WS。

**Tech Stack:** React 19 + TypeScript 5.8 + Vite 6 + react-router 7 + @xyflow/react + @dagrejs/dagre + vitest + Biome。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `frontend/src/features/canvas/canvasReducer.ts` | 纯函数：reduceEvents + applyDagreLayout，0 React |
| `frontend/src/features/canvas/canvasReducer.test.ts` | 归约器单元测试（vitest） |
| `frontend/src/features/canvas/useCanvasState.ts` | useMemo 包装，返回 nodes/edges |
| `frontend/src/features/canvas/AgentNode.tsx` | React Flow 自定义节点 |
| `frontend/src/features/canvas/AgentCanvas.tsx` | ReactFlow 渲染组件 |
| `frontend/src/features/canvas/canvas.css` | 纯 CSS，mesh- 前缀 |
| `frontend/src/pages/executions/ExecutionsPage.tsx` | 修改：补列表（调 executionsApi） |
| `frontend/src/pages/executions/ExecutionDetailPage.tsx` | 新建：画布宿主页 |
| `frontend/src/App.tsx` | 修改：新增 /executions/:id 路由 |
| `frontend/package.json` | 修改：新增依赖 |

---

### Task 1: 安装依赖

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: 安装 @xyflow/react + @dagrejs/dagre**

Run: `cd frontend && pnpm add @xyflow/react @dagrejs/dagre`
Expected: 两包写入 dependencies，pnpm-lock.yaml 更新。

- [ ] **Step 2: 验证安装**

Run: `cd frontend && pnpm run build`
Expected: PASS（新包可导入，类型就绪）。

- [ ] **Step 3: Commit**

```bash
cd frontend && git add package.json pnpm-lock.yaml
git commit -m "chore(M10): 安装 @xyflow/react + @dagrejs/dagre"
```

---

### Task 2: 归约器 + 测试（TDD）

**Files:**
- Test: `frontend/src/features/canvas/canvasReducer.test.ts`
- Create: `frontend/src/features/canvas/canvasReducer.ts`

- [ ] **Step 1: 创建 features/canvas 目录**

Run: `cd frontend/src && mkdir -p features/canvas`

- [ ] **Step 2: 写失败测试 canvasReducer.test.ts**

```typescript
// frontend/src/features/canvas/canvasReducer.test.ts
import { describe, expect, test } from 'vitest';
import { reduceEvents } from './canvasReducer';
import type { WebSocketEvent } from '../../types/protocol';

describe('reduceEvents', () => {
  test('单 INIT 事件创建 orchestrator 节点', () => {
    const events: WebSocketEvent[] = [
      {
        created_at: '2026-01-01T00:00:00Z',
        protocol_stage: 'INIT',
        event_type: 'agent_spawn',
        agent_id: 'orchestrator',
        workflow_id: 'wf-1',
      },
    ];
    const { nodes, edges } = reduceEvents(events);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].id).toBe('orchestrator');
    expect(nodes[0].data.status).toBe('running');
    expect(edges).toHaveLength(0);
  });

  test('完整串行链：INIT→ROUTE(A)→EXECUTE→ROUTE(B)→EXECUTE→ROUTE(null)→FINISH', () => {
    const events: WebSocketEvent[] = [
      { created_at: 't0', protocol_stage: 'INIT', event_type: 'agent_spawn', agent_id: 'orchestrator', workflow_id: 'w1' },
      { created_at: 't1', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: 'agent-A', routing_reason: 'start' },
      { created_at: 't2', protocol_stage: 'EXECUTE', event_type: 'agent_finish', agent_message: 'A done', prompt_tokens: 10, completion_tokens: 20, model: 'gpt-4', model_cost_usd: 0.01 },
      { created_at: 't3', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: 'agent-B', routing_reason: 'next' },
      { created_at: 't4', protocol_stage: 'EXECUTE', event_type: 'agent_finish', agent_message: 'B done', prompt_tokens: 15, completion_tokens: 25, model: 'gpt-4', model_cost_usd: 0.02 },
      { created_at: 't5', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: null, routing_reason: 'end' },
      { created_at: 't6', protocol_stage: 'FINISH', event_type: 'agent_finish', success: true, output: { message: 'B done' } },
    ];
    const { nodes, edges } = reduceEvents(events);
    expect(nodes).toHaveLength(3); // orch, A, B
    expect(nodes.every(n => n.data.status === 'finished')).toBe(true);
    expect(edges).toHaveLength(2);
    expect(edges[0].source).toBe('orchestrator');
    expect(edges[0].target).toBe('agent-A');
    expect(edges[1].source).toBe('agent-A');
    expect(edges[1].target).toBe('agent-B');
  });

  test('循环图边 ID 唯一', () => {
    const events: WebSocketEvent[] = [
      { created_at: 't0', protocol_stage: 'INIT', event_type: 'agent_spawn', agent_id: 'orch', workflow_id: 'w' },
      { created_at: 't1', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: 'A', routing_reason: null },
      { created_at: 't2', protocol_stage: 'EXECUTE', event_type: 'agent_finish', agent_message: '', prompt_tokens: 1, completion_tokens: 1, model: 'm', model_cost_usd: 0 },
      { created_at: 't3', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: 'B', routing_reason: null },
      { created_at: 't4', protocol_stage: 'EXECUTE', event_type: 'agent_finish', agent_message: '', prompt_tokens: 1, completion_tokens: 1, model: 'm', model_cost_usd: 0 },
      { created_at: 't5', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: 'A', routing_reason: null },
      { created_at: 't6', protocol_stage: 'EXECUTE', event_type: 'agent_finish', agent_message: '', prompt_tokens: 1, completion_tokens: 1, model: 'm', model_cost_usd: 0 },
    ];
    const { edges } = reduceEvents(events);
    const edgeIds = edges.map(e => e.id);
    expect(new Set(edgeIds).size).toBe(edgeIds.length); // 无重复
  });

  test('FINISH success=false → orchestrator error', () => {
    const events: WebSocketEvent[] = [
      { created_at: 't0', protocol_stage: 'INIT', event_type: 'agent_spawn', agent_id: 'orchestrator', workflow_id: 'w' },
      { created_at: 't1', protocol_stage: 'FINISH', event_type: 'agent_finish', success: false, output: { error: 'fail' } },
    ];
    const { nodes } = reduceEvents(events);
    expect(nodes[0].data.status).toBe('error');
  });

  test('agent_chunk_stream 被跳过', () => {
    const events: WebSocketEvent[] = [
      { created_at: 't0', protocol_stage: 'INIT', event_type: 'agent_spawn', agent_id: 'orch', workflow_id: 'w' },
      { event_type: 'agent_chunk_stream', agent_id: 'a', text: 'chunk', reasoning: false },
    ];
    const { nodes } = reduceEvents(events);
    expect(nodes).toHaveLength(1); // 只有 orch
  });
});
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd frontend && pnpm run test`
Expected: FAIL —"Cannot find module './canvasReducer'"

- [ ] **Step 4: 创建 canvasReducer.ts 类型定义**

```typescript
// frontend/src/features/canvas/canvasReducer.ts
import type { Edge, Node } from '@xyflow/react';
import type { WebSocketEvent } from '../../types/protocol';

export type NodeStatus = 'running' | 'finished' | 'error';

export interface AgentNodeData extends Record<string, unknown> {
  label: string;
  status: NodeStatus;
  agentMessage?: string;
  tokens?: number;
  model?: string;
}

export interface CanvasGraph {
  nodes: Node<AgentNodeData>[];
  edges: Edge[];
}

export function reduceEvents(events: WebSocketEvent[]): CanvasGraph {
  return { nodes: [], edges: [] };
}
```

- [ ] **Step 5: 运行测试确认仍失败但进度前进**

Run: `cd frontend && pnpm run test`
Expected: FAIL —测试可运行，但断言失败（nodes 长度期望1 实际0）

- [ ] **Step 6: 实现 reduceEvents 完整逻辑**

```typescript
// frontend/src/features/canvas/canvasReducer.ts（完整替换）
import type { Edge, Node } from '@xyflow/react';
import type { WebSocketEvent } from '../../types/protocol';

export type NodeStatus = 'running' | 'finished' | 'error';

export interface AgentNodeData extends Record<string, unknown> {
  label: string;
  status: NodeStatus;
  agentMessage?: string;
  tokens?: number;
  model?: string;
}

export interface CanvasGraph {
  nodes: Node<AgentNodeData>[];
  edges: Edge[];
}

export function reduceEvents(events: WebSocketEvent[]): CanvasGraph {
  const nodeMap = new Map<string, AgentNodeData>();
  const edgeList: Edge[] = [];
  let currentAgentId: string | null = null;
  let lastSource: string | null = null;

  for (const event of events) {
    if (event.event_type === 'agent_chunk_stream') continue;

    switch (event.protocol_stage) {
      case 'INIT':
        nodeMap.set(event.agent_id, { label: event.agent_id, status: 'running' });
        lastSource = event.agent_id;
        break;

      case 'ROUTE':
        if (event.next_agent_id) {
          if (!nodeMap.has(event.next_agent_id)) {
            nodeMap.set(event.next_agent_id, { label: event.next_agent_id, status: 'running' });
          }
          if (lastSource) {
            edgeList.push({
              id: `${lastSource}->${event.next_agent_id}-${edgeList.length}`,
              source: lastSource,
              target: event.next_agent_id,
            });
          }
          currentAgentId = event.next_agent_id;
        }
        break;

      case 'EXECUTE':
        if (currentAgentId && nodeMap.has(currentAgentId)) {
          nodeMap.set(currentAgentId, {
            ...nodeMap.get(currentAgentId)!,
            status: 'finished',
            agentMessage: event.agent_message,
            tokens: event.prompt_tokens + event.completion_tokens,
            model: event.model,
          });
          lastSource = currentAgentId;
        }
        break;

      case 'FINISH': {
        const orch = nodeMap.get('orchestrator');
        if (orch) nodeMap.set('orchestrator', { ...orch, status: event.success ? 'finished' : 'error' });
        break;
      }
    }
  }

  const nodes: Node<AgentNodeData>[] = Array.from(nodeMap.entries()).map(([id, data]) => ({
    id,
    type: 'agentNode',
    position: { x: 0, y: 0 },
    data,
  }));

  return { nodes, edges: edgeList };
}
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd frontend && pnpm run test`
Expected: PASS —全部测试通过

- [ ] **Step 8: Commit**

```bash
cd frontend && git add src/features/canvas/
git commit -m "feat(M10): canvasReducer 归约器 + 单元测试"
```

---

### Task 3: dagre 布局 + useCanvasState

**Files:**
- Modify: `frontend/src/features/canvas/canvasReducer.ts`
- Create: `frontend/src/features/canvas/useCanvasState.ts`
- Modify: `frontend/src/features/canvas/canvasReducer.test.ts`

- [ ] **Step 1: 追加 applyDagreLayout 到 canvasReducer.ts**

在文件末尾追加：

```typescript
// ── dagre 布局 ──────────────────────────────────────────────
import dagre from '@dagrejs/dagre';

const NODE_W = 160;
const NODE_H = 60;

export function applyDagreLayout(
  nodes: Node<AgentNodeData>[],
  edges: Edge[],
): Node<AgentNodeData>[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 50, ranksep: 60 });

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return nodes.map((n) => {
    const { x, y } = g.node(n.id);
    return { ...n, position: { x: x - NODE_W / 2, y: y - NODE_H / 2 } };
  });
}
```

- [ ] **Step 2: 追加 dagre 冒烟测试到 canvasReducer.test.ts**

在文件末尾追加：

```typescript
describe('applyDagreLayout', () => {
  test('dagre 注入非零坐标', () => {
    const { nodes, edges } = reduceEvents([
      { created_at: 't', protocol_stage: 'INIT', event_type: 'agent_spawn', agent_id: 'orch', workflow_id: 'w' },
      { created_at: 't', protocol_stage: 'ROUTE', event_type: 'agent_call', next_agent_id: 'A', routing_reason: null },
    ]);
    const laid = applyDagreLayout(nodes, edges);
    expect(laid.every(n => n.position.x !== 0 || n.position.y !== 0)).toBe(true);
  });
});
```

并在文件顶部 import 追加：

```typescript
import { applyDagreLayout, reduceEvents } from './canvasReducer';
```

- [ ] **Step 3: 运行测试确认 dagre 正常**

Run: `cd frontend && pnpm run test`
Expected: PASS

- [ ] **Step 4: 创建 useCanvasState.ts**

```typescript
// frontend/src/features/canvas/useCanvasState.ts
import { useMemo } from 'react';
import type { WebSocketEvent } from '../../types/protocol';
import { applyDagreLayout, reduceEvents } from './canvasReducer';
import type { CanvasGraph } from './canvasReducer';

export function useCanvasState(events: WebSocketEvent[]): CanvasGraph {
  return useMemo(() => {
    const { nodes, edges } = reduceEvents(events);
    return { nodes: applyDagreLayout(nodes, edges), edges };
  }, [events]);
}
```

- [ ] **Step 5: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/features/canvas/
git commit -m "feat(M10): dagre 布局 + useCanvasState hook"
```

---

### Task 4: React Flow 组件

**Files:**
- Create: `frontend/src/features/canvas/AgentNode.tsx`
- Create: `frontend/src/features/canvas/AgentCanvas.tsx`

- [ ] **Step 1: 创建 AgentNode.tsx**

```tsx
// frontend/src/features/canvas/AgentNode.tsx
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import type { AgentNodeData, NodeStatus } from './canvasReducer';

const STATUS_COLOR: Record<NodeStatus, string> = {
  running:  '#3b82f6',
  finished: '#22c55e',
  error:    '#ef4444',
};

export function AgentNode({ data }: NodeProps<AgentNodeData>) {
  const bg = STATUS_COLOR[data.status];
  return (
    <div className="mesh-agent-node" style={{ background: bg }}>
      <Handle type="target" position={Position.Top} />
      <span className="mesh-agent-node__label">{data.label}</span>
      {data.tokens != null && (
        <span className="mesh-agent-node__tokens">{data.tokens} tok</span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
```

- [ ] **Step 2: 创建 AgentCanvas.tsx**

```tsx
// frontend/src/features/canvas/AgentCanvas.tsx
import { Background, Controls, ReactFlow } from '@xyflow/react';
import type { Edge, Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AgentNode } from './AgentNode';
import type { AgentNodeData } from './canvasReducer';
import './canvas.css';

const nodeTypes = { agentNode: AgentNode };

interface AgentCanvasProps {
  nodes: Node<AgentNodeData>[];
  edges: Edge[];
}

export function AgentCanvas({ nodes, edges }: AgentCanvasProps) {
  return (
    <div className="mesh-canvas-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 3: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/features/canvas/AgentNode.tsx src/features/canvas/AgentCanvas.tsx
git commit -m "feat(M10): AgentNode + AgentCanvas 组件"
```

---

### Task 5: CSS 样式

**Files:**
- Create: `frontend/src/features/canvas/canvas.css`

- [ ] **Step 1: 创建 canvas.css**

```css
/* frontend/src/features/canvas/canvas.css */

/* ── 画布容器 ─────────────────────────── */
.mesh-canvas-container { width: 100%; height: 100%; }

/* ── 执行详情页布局 ───────────────────── */
.mesh-execution-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.mesh-execution-detail__header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.mesh-execution-detail__canvas {
  flex: 1;
  min-height: 0;
  border: 1px solid #e0e2e7;
  border-radius: 8px;
}
.mesh-execution-ended { color: #6b7280; }

/* ── WS 状态指示器 ────────────────────── */
.mesh-ws-indicator { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
.mesh-ws--connected    { background: #dcfce7; color: #166534; }
.mesh-ws--connecting   { background: #fef9c3; color: #854d0e; }
.mesh-ws--disconnected { background: #f3f4f6; color: #6b7280; }
.mesh-ws--error        { background: #fee2e2; color: #991b1b; }

/* ── Agent 自定义节点 ─────────────────── */
.mesh-agent-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  width: 160px;
  height: 60px;
  border-radius: 8px;
  color: #fff;
  font-size: 13px;
}
.mesh-agent-node__label  { font-weight: 600; }
.mesh-agent-node__tokens { font-size: 11px; opacity: 0.85; }

/* ── 执行列表页 ───────────────────────── */
.mesh-execution-list { list-style: none; margin: 0; padding: 0; }
.mesh-execution-item { border-bottom: 1px solid #f0f0f0; }
.mesh-execution-item a {
  display: flex;
  gap: 16px;
  padding: 12px 0;
  text-decoration: none;
  color: #3c4149;
}
.mesh-execution-item__id   { font-family: monospace; font-size: 12px; }
.mesh-execution-item__time { font-size: 12px; color: #6b7280; margin-left: auto; }
.mesh-status--running   { color: #2563eb; }
.mesh-status--pending   { color: #d97706; }
.mesh-status--completed { color: #16a34a; }
.mesh-status--failed    { color: #dc2626; }
```

- [ ] **Step 2: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/features/canvas/canvas.css
git commit -m "feat(M10): canvas.css 样式（mesh- 前缀）"
```

---

### Task 6: ExecutionsPage 列表（修改骨架）

**Files:**
- Modify: `frontend/src/pages/executions/ExecutionsPage.tsx`

- [ ] **Step 1: 替换 ExecutionsPage.tsx**

```tsx
// frontend/src/pages/executions/ExecutionsPage.tsx
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { executionsApi } from '../../api/executions';

export default function ExecutionsPage() {
  const { data: executions, isLoading, isError } = useQuery({
    queryKey: ['executions'],
    queryFn: () => executionsApi.list(),
  });

  if (isLoading) return <p>加载中…</p>;
  if (isError)   return <p>加载执行列表失败</p>;

  return (
    <div>
      <h1>Executions</h1>
      <ul className="mesh-execution-list">
        {executions?.map((exec) => (
          <li key={exec.id} className="mesh-execution-item">
            <Link to={`/executions/${exec.id}`}>
              <span className="mesh-execution-item__id">{exec.id}</span>
              <span className={`mesh-execution-item__status mesh-status--${exec.status}`}>
                {exec.status}
              </span>
              <span className="mesh-execution-item__time">{exec.created_at}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/pages/executions/ExecutionsPage.tsx
git commit -m "feat(M10): ExecutionsPage 执行列表"
```

---

### Task 7: ExecutionDetailPage（画布宿主页）

**Files:**
- Create: `frontend/src/pages/executions/ExecutionDetailPage.tsx`

- [ ] **Step 1: 创建 ExecutionDetailPage.tsx**

```tsx
// frontend/src/pages/executions/ExecutionDetailPage.tsx
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { executionsApi } from '../../api/executions';
import { AgentCanvas } from '../../features/canvas/AgentCanvas';
import { useCanvasState } from '../../features/canvas/useCanvasState';
import { useAgentStream } from '../../hooks/useAgentStream';
import { useSessionStore } from '../../stores/sessionStore';

const ACTIVE_STATUSES = ['pending', 'running'];

export default function ExecutionDetailPage() {
  const { id = '' } = useParams();
  const token = useSessionStore((s) => s.accessToken);

  const { data: execution, isLoading, isError } = useQuery({
    queryKey: ['execution', id],
    queryFn: () => executionsApi.get(id),
    enabled: !!id,
  });

  const isActive = execution ? ACTIVE_STATUSES.includes(execution.status) : false;

  // hooks 无条件调用（React 规则）；非活动执行 token:null 跳过 WS
  const { wsState, events } = useAgentStream({
    executionId: id,
    token: isActive ? token : null,
  });
  const { nodes, edges } = useCanvasState(events);

  if (isLoading) return <p>加载中…</p>;
  if (isError || !execution) return <p>加载执行详情失败</p>;

  if (!isActive) {
    return (
      <div className="mesh-execution-detail">
        <h1>Execution {id}</h1>
        <p className="mesh-execution-ended">
          此执行已结束（{execution.status}）。实时画布仅用于进行中的执行，历史回溯请查看 Timeline。
        </p>
      </div>
    );
  }

  return (
    <div className="mesh-execution-detail">
      <header className="mesh-execution-detail__header">
        <h1>Execution {id}</h1>
        <span className={`mesh-ws-indicator mesh-ws--${wsState}`}>{wsState}</span>
      </header>
      <div className="mesh-execution-detail__canvas">
        <AgentCanvas nodes={nodes} edges={edges} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/pages/executions/ExecutionDetailPage.tsx
git commit -m "feat(M10): ExecutionDetailPage 画布宿主页"
```

---

### Task 8: App.tsx 路由装配

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 修改 App.tsx（仅新增一条路由 + 一个 import）**

```tsx
// frontend/src/App.tsx（完整文件）
import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/layout/AppShell";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import AgentsPage from "./pages/agents/AgentsPage";
import ExecutionDetailPage from "./pages/executions/ExecutionDetailPage";
import ExecutionsPage from "./pages/executions/ExecutionsPage";
import WorkflowsPage from "./pages/workflows/WorkflowsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route element={<AppShell />}>
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/executions" element={<ExecutionsPage />} />
        <Route path="/executions/:id" element={<ExecutionDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate replace to="/agents" />} />
    </Routes>
  );
}
```

- [ ] **Step 2: 类型校验**

Run: `cd frontend && pnpm run build`
Expected: PASS（完整链路编译通过）

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/App.tsx
git commit -m "feat(M10): 路由装配 /executions/:id"
```

---

### Task 9: 全量验证与收口

**Files:** 无新增，全链路验证。

- [ ] **Step 1: 运行全部测试**

Run: `cd frontend && pnpm run test`
Expected: PASS，所有 canvasReducer 测试通过（含 dagre 冒烟）

- [ ] **Step 2: 全量构建**

Run: `cd frontend && pnpm run build`
Expected: PASS

- [ ] **Step 3: Biome 检查**

Run: `cd frontend && pnpm run check`
Expected: PASS。若有格式问题运行 `pnpm exec biome check --write src` 后重跑。

- [ ] **Step 4: 手动 dev 验证**

Run: `cd frontend && pnpm run dev`

手动检查清单：
- 访问 `/executions` → 列表页无报错（后端未起时显示加载失败提示，可接受）
- 访问 `/executions/test-id` → 显示"此执行已结束"提示（无后端时 isError=true，显示"加载执行详情失败"）
- 如有后端运行：触发工作流 → 获取 execution_id → 访问 `/executions/:id` → 画布节点随事件流增量出现，运行中节点蓝色，完成后变绿；WS 状态指示器显示 `connected`
- 所有页面 AppShell 布局正常（顶栏+侧边栏），导航 NavLink 激活样式正确

停止 dev：Ctrl+C

- [ ] **Step 5: 若 Biome 有格式化改动则提交**

```bash
cd frontend && git status
# 如有改动：
git add -A && git commit -m "style(M10): biome 格式化收口"
```

---

## Self-Review

**Spec 覆盖核对：**
- 文件矩阵 10 项 → Task 1（deps）/ Task 2（reducer+test）/ Task 3（dagre+useCanvasState）/ Task 4（组件）/ Task 5（CSS）/ Task 6（ExecutionsPage）/ Task 7（ExecutionDetailPage）/ Task 8（App.tsx）全覆盖 ✅
- Q1 纯事件驱动 → `useCanvasState(events)` 单参数，无静态拓扑 ✅
- Q2 专属路由 → Task 8 `/executions/:id` ✅
- Q3 dagre 布局 → Task 3 applyDagreLayout ✅
- Q4 列表+画布 → Task 6+7 ✅
- Q5 已完成提示 → Task 7 `ACTIVE_STATUSES` 守门 ✅
- 归约器测试 → Task 2（5 用例含循环图边 ID 唯一） ✅

**类型一致性：**
- `AgentNodeData`、`CanvasGraph`、`NodeStatus`、`reduceEvents`、`applyDagreLayout`、`useCanvasState`、`AgentCanvas` 跨 Task 2-8 命名完全一致 ✅
- `nodeTypes = { agentNode: AgentNode }` 与 `type: 'agentNode'` 在 Task 2/4 一致 ✅

**Placeholder 扫描：** 无 TBD/TODO/"类似 Task N"，每个代码步骤含完整代码 ✅


