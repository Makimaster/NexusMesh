# M10 AgentCanvas 拓扑 — 详细设计方案

> 状态：待实现
> 日期：2026-07-07
> 依赖：M9（前端基础设施全部交付）
> 定位：Phase 4 前端可视化第一个业务模块，实时渲染 Agent 协作拓扑

---

## 1. 设计目标与边界

M10 是 NexusMesh 前端的 **实时拓扑可视化层**，在 Agent 协作执行过程中动态渲染节点/边。

### 1.1 核心功能

1. **执行列表页**（`/executions`）：调用 `executionsApi.list()`，展示历史执行记录，提供进入画布的入口
2. **拓扑画布页**（`/executions/:id`）：实时渲染 Agent 协作拓扑，节点/边随 WS 事件流增量出现，状态色彩随执行进度流转

### 1.2 架构核心决策（评审锁定）

| 决策 | 选项 | 理由 |
|------|------|------|
| Q1 数据源策略 | **B — 纯事件驱动增量长图** | 单一数据源，与路线图"实时渲染"定位吻合，归约器可纯函数单测 |
| Q2 Canvas 入口路由 | **A — `/executions/:id` 专属路由** | URL 可书签，画布全屏，M13 NodePanel 侧边展开自然 |
| Q3 节点布局算法 | **A — dagre 层次自动布局** | 专业 DAG 视觉，React Flow 生态标准，top→bottom 层次图 |
| Q4 功能边界 | **B — 列表入口 + 画布** | 无列表则无手测入口，`executionsApi` 已由 M9 交付 |
| Q5 已完成执行处理 | **A — 仅实时，完成时显示提示** | YAGNI，历史回溯职责归 M12 Timeline |
| 状态管理方案 | **本地 Hook + useMemo** | 画布状态不跨路由，归约器纯函数最易单测，无需全局 store |

### 1.3 明确不做（YAGNI 边界）

- 不做已完成执行的事件回放（M12 职责）
- 不做节点编辑/拖拽定位持久化（`nodesDraggable={false}`）
- 不做触发执行功能（M10 是只读画布）
- 不做 M13 NodePanel 的内容（M13 依赖 M10，反向不成立）
- 不引入全局 canvas store（本地 useMemo 已够用）

---

## 2. 文件矩阵

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/features/canvas/canvasReducer.ts` | **新建** | 纯函数：`reduceEvents + applyDagreLayout` |
| `frontend/src/features/canvas/useCanvasState.ts` | **新建** | useMemo 包装归约器，返回 RF nodes/edges |
| `frontend/src/features/canvas/AgentNode.tsx` | **新建** | React Flow 自定义节点，状态色彩映射 |
| `frontend/src/features/canvas/AgentCanvas.tsx` | **新建** | ReactFlow 核心渲染组件 |
| `frontend/src/features/canvas/canvas.css` | **新建** | 纯 CSS，`mesh-` 前缀 |
| `frontend/src/features/canvas/canvasReducer.test.ts` | **新建** | 归约器单元测试（vitest） |
| `frontend/src/pages/executions/ExecutionsPage.tsx` | **修改** | 补充执行列表（M9 骨架→业务实现） |
| `frontend/src/pages/executions/ExecutionDetailPage.tsx` | **新建** | `/executions/:id` 页面，画布宿主 |
| `frontend/src/App.tsx` | **修改** | 新增 `/executions/:id` 路由 |
| `frontend/package.json` | **修改** | 新增 `@xyflow/react`、`@dagrejs/dagre` |

依赖单向向下：`protocol.ts（M9）→ canvasReducer → useCanvasState → AgentCanvas → ExecutionDetailPage`

---

## 3. 后端执行事件流分析

### 3.1 串行主循环（coordinator.py 实测确认）

M6 Coordinator 采用**单线程 while 循环**，每跳 await 到底，事件发射严格有序：

```
INIT(agent_id="orchestrator") → RECEIVE → 
  ROUTE(next_agent_id=X) → EXECUTE(X结果) →
  ROUTE(next_agent_id=Y) → EXECUTE(Y结果) →
  ...
  ROUTE(next_agent_id=null) → FINISH(success)
```

### 3.2 关键约束：EXECUTE 帧不含 agent_id

`ExecutePayload` 仅有 `{agent_message, prompt_tokens, completion_tokens, model, model_cost_usd}`，无 `agent_id`。归约器通过"紧邻的 ROUTE 的 next_agent_id"关联后续 EXECUTE（串行保证此关联恒成立）。

### 3.3 M9 protocol.ts 判别联合类型

```typescript
// 各帧字段直接在事件对象上（非 payload 嵌套）
InitWsEvent:    { protocol_stage: "INIT";    agent_id, workflow_id }
RouteWsEvent:   { protocol_stage: "ROUTE";   next_agent_id, routing_reason }
ExecuteWsEvent: { protocol_stage: "EXECUTE"; agent_message, prompt_tokens, ... }
FinishWsEvent:  { protocol_stage: "FINISH";  success, output }
```

switch 语句中 TypeScript 自动窄化，`event.agent_id`（INIT 分支）等完全合法。

---

## 4. 归约器（`canvasReducer.ts`）

### 4.1 数据类型

```typescript
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
```

### 4.2 事件→拓扑动作映射

| 事件 | 归约动作 |
|------|---------|
| `INIT(agent_id="orchestrator")` | 创建根节点 running，`lastSource = "orchestrator"` |
| `RECEIVE` | 跳过（无拓扑变化） |
| `ROUTE(next_agent_id=X)` | 新建节点 X(running)；`edges += [lastSource→X-${edgeList.length}]`；`currentAgentId = X` |
| `ROUTE(next_agent_id=null)` | 跳过（路由终止信号） |
| `EXECUTE(...)` | `nodeMap[currentAgentId].status = finished`，挂载 tokens/model；`lastSource = currentAgentId` |
| `FINISH(success=true)` | orchestrator 节点 → finished |
| `FINISH(success=false)` | orchestrator 节点 → error |
| `agent_chunk_stream` | 跳过（流式 token，不影响拓扑） |

> 边 ID 格式 `${source}->${target}-${edgeList.length}`：`edgeList.length` 后缀保证循环图（A→B→A）重复路径的边 ID 全局唯一，彻底防止 React Flow 重复 key 崩溃。

### 4.3 完整实现

```typescript
// frontend/src/features/canvas/canvasReducer.ts
import dagre from '@dagrejs/dagre';
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

// ── dagre 布局 ──────────────────────────────────────────────
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
    // dagre 返回中心点，React Flow 用左上角，需偏移半宽高
    return { ...n, position: { x: x - NODE_W / 2, y: y - NODE_H / 2 } };
  });
}
```

---

## 5. React Flow 集成

### 5.1 `useCanvasState.ts`

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

每次 `events` 追加（append-only），useMemo 重新计算完整图。dagre 在几十节点规模耗时 < 1ms，无性能问题。

### 5.2 `AgentNode.tsx`

```tsx
// frontend/src/features/canvas/AgentNode.tsx
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import type { AgentNodeData, NodeStatus } from './canvasReducer';

const STATUS_COLOR: Record<NodeStatus, string> = {
  running:  '#3b82f6',  // 蓝
  finished: '#22c55e',  // 绿
  error:    '#ef4444',  // 红
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

### 5.3 `AgentCanvas.tsx`

```tsx
// frontend/src/features/canvas/AgentCanvas.tsx
import { Background, Controls, ReactFlow } from '@xyflow/react';
import type { Edge, Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AgentNode } from './AgentNode';
import type { AgentNodeData } from './canvasReducer';
import './canvas.css';

// 组件外定义——React Flow 要求稳定引用，否则重复注册告警
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

> `nodesDraggable={false}`：dagre 每次事件重算布局，允许拖拽会被下一事件重置造成困惑；只读画布禁用拖拽。

---

## 6. 页面组件

### 6.1 `ExecutionsPage.tsx`（修改 M9 骨架）

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

### 6.2 `ExecutionDetailPage.tsx`（新建）

```tsx
// frontend/src/pages/executions/ExecutionDetailPage.tsx
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { AgentCanvas } from '../../features/canvas/AgentCanvas';
import { useCanvasState } from '../../features/canvas/useCanvasState';
import { executionsApi } from '../../api/executions';
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

---

## 7. 路由与样式

### 7.1 `App.tsx` 修改（仅新增一行路由）

```tsx
// frontend/src/App.tsx
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

> react-router v7 精确匹配，`/executions` 与 `/executions/:id` 不冲突。两个路由均在 AppShell 组内，详情页保留顶栏+侧边栏。

### 7.2 `canvas.css`（完整）

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
  min-height: 0;   /* flex 子项撑满剩余高度，React Flow 需确定尺寸 */
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
.mesh-execution-item__id    { font-family: monospace; font-size: 12px; }
.mesh-execution-item__time  { font-size: 12px; color: #6b7280; margin-left: auto; }
.mesh-status--running   { color: #2563eb; }
.mesh-status--pending   { color: #d97706; }
.mesh-status--completed { color: #16a34a; }
.mesh-status--failed    { color: #dc2626; }
```

---

## 8. 验证策略与 DoD 闭环

**DoD 原文**："给定一段事件序列，拓扑正确渲染与更新（组件测试或本地手测录屏可复现）。"

### 8.1 Tier 1 — 归约器单元测试（vitest）

`features/canvas/canvasReducer.test.ts`：

| 用例 | 断言 |
|------|------|
| 单 INIT 事件 | 1 节点 orchestrator，status=running |
| 完整串行链（INIT→ROUTE(A)→EXECUTE→ROUTE(B)→EXECUTE→ROUTE(null)→FINISH） | 3 节点均 finished，2 条边 orch→A、A→B |
| EXECUTE 归属 | ROUTE 目标节点被标 finished，agentMessage/tokens/model 正确挂载 |
| FINISH(success=true) | orchestrator → finished |
| FINISH(success=false) | orchestrator → error |
| 循环图（A→B→A→B） | 4 条边 ID 全部唯一（Fix #2 验证） |
| agent_chunk_stream 混入 | 节点数/边数不变 |
| dagre 布局冒烟 | `applyDagreLayout` 后所有节点 position 不再全为 `{0,0}` |

### 8.2 Tier 2 — 静态验证

| 命令 | 验证目标 |
|------|---------|
| `pnpm run build`（`tsc -b`） | `@xyflow/react` / `@dagrejs/dagre` 类型咬合，全链路编译通过 |
| `pnpm run check`（biome） | 代码规范 |

### 8.3 Tier 3 — 手动 dev 验证

1. `pnpm run dev`
2. 访问 `/executions` → 列表加载（需后端运行），或列表为空不报错
3. 若后端可用：触发一条工作流 → 导航到 `/executions/:id` → 画布节点随事件增量出现，色彩流转（蓝→绿）
4. 访问已完成 execution 的 `/executions/:id` → 显示"已结束"提示
5. 布局不崩塌，画布可缩放/平移

---

## 9. 设计自审清单

| 检查项 | 结论 |
|--------|------|
| Q1 纯事件驱动，无静态 topology 依赖 | ✅ `useCanvasState(events)` 单参数 |
| Q2 `/executions/:id` 独立路由 | ✅ App.tsx §7.1 |
| Q3 dagre TB 层次布局，坐标偏移正确 | ✅ `x - NODE_W/2`，`y - NODE_H/2` |
| Q4 列表页 + 画布页双交付 | ✅ ExecutionsPage + ExecutionDetailPage |
| Q5 非 active 状态显示"已结束"提示 | ✅ `ACTIVE_STATUSES` 守门 |
| React hooks 无条件调用（非 active 传 token:null） | ✅ |
| 边 ID 唯一性（循环图） | ✅ `edgeList.length` 后缀 |
| TypeScript 判别联合窄化（非 payload 路径） | ✅ switch + event_type 前置过滤 |
| `nodeTypes` 组件外稳定引用 | ✅ |
| React Flow 画布容器确定高度（`flex:1; min-height:0`） | ✅ |
| CSS `mesh-` 前缀命名空间隔离 | ✅ 所有类名 |
| App.tsx 外科手术式改动（仅新增一行路由） | ✅ |
| 新增依赖：`@xyflow/react`、`@dagrejs/dagre`（无 @types/dagre 需求） | ✅ |
| YAGNI：不含回放/触发/M13 NodePanel | ✅ |

