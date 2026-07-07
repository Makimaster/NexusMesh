import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import ReactDOM from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, test, vi } from "vitest";

import { executionsApi } from "../../api/executions";
import { useCanvasState } from "../../features/canvas/useCanvasState";
import { useAgentStream } from "../../hooks/useAgentStream";
import type {
  ExecutionResponse,
  TimelineEventResponse,
  WebSocketEvent,
} from "../../types/protocol";
import ExecutionDetailPage from "./ExecutionDetailPage";

vi.mock("../../features/canvas/AgentCanvas", () => ({
  AgentCanvas: ({ nodes, edges }: { nodes: unknown[]; edges: unknown[] }) => (
    <div data-testid="agent-canvas">
      canvas:{nodes.length}/{edges.length}
    </div>
  ),
}));

vi.mock("../../features/canvas/useCanvasState", () => ({
  useCanvasState: vi.fn(() => ({ nodes: [{ id: "node-1" }], edges: [] })),
}));

vi.mock("../../hooks/useAgentStream", () => ({
  useAgentStream: vi.fn(() => ({ wsState: "connected", events: [] })),
}));

vi.mock("../../stores/sessionStore", () => ({
  useSessionStore: vi.fn(
    (selector: (state: { accessToken: string | null }) => unknown) =>
      selector({ accessToken: "token-123" }),
  ),
}));

(
  globalThis as typeof globalThis & {
    IS_REACT_ACT_ENVIRONMENT?: boolean;
  }
).IS_REACT_ACT_ENVIRONMENT = true;

async function renderPage(id = "exec-001") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/executions/${id}`]}>
          <Routes>
            <Route path="/executions/:id" element={<ExecutionDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });

  return {
    container,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      queryClient.clear();
      container.remove();
    },
  };
}

function createExecution(
  overrides: Partial<ExecutionResponse> = {},
): ExecutionResponse {
  return {
    id: "exec-001",
    workflow_id: "wf-001",
    status: "running",
    started_at: "2026-07-07T12:00:00Z",
    finished_at: null,
    created_at: "2026-07-07T12:00:00Z",
    input: {},
    output: null,
    error: null,
    ...overrides,
  };
}

function createTimelineEvent(
  overrides: Partial<TimelineEventResponse> = {},
): TimelineEventResponse {
  return {
    id: "timeline-001",
    execution_id: "exec-001",
    protocol_stage: "INIT",
    event_type: "agent_spawn",
    payload: {
      agent_id: "orchestrator",
      workflow_id: "wf-001",
    },
    created_at: "2026-07-07T12:00:00Z",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("ExecutionDetailPage", () => {
  test("非活动执行显示已结束提示", async () => {
    vi.useFakeTimers();
    const streamEvents: WebSocketEvent[] = [
      {
        event_type: "agent_chunk_stream",
        agent_id: "a1",
        text: "hi",
        reasoning: false,
      },
    ];

    vi.mocked(useAgentStream).mockReturnValue({
      wsState: "connected",
      events: streamEvents,
      currentStage: null,
    });

    let resolveGet:
      | ((value: Awaited<ReturnType<typeof executionsApi.get>>) => void)
      | undefined;

    vi.spyOn(executionsApi, "get").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve;
        }),
    );
    const timelineSpy = vi.spyOn(executionsApi, "timeline");

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      resolveGet?.(
        createExecution({
          status: "completed",
          started_at: null,
        }),
      );
      await vi.runAllTimersAsync();
    });

    expect(view.container.textContent).toContain("Execution exec-001");
    expect(view.container.textContent).toContain("此执行已结束（completed）");
    expect(
      view.container.querySelector('[data-testid="agent-canvas"]'),
    ).toBeNull();
    expect(useAgentStream).toHaveBeenCalledWith({
      executionId: "exec-001",
      token: null,
    });
    expect(useCanvasState).toHaveBeenCalledWith(streamEvents);
    expect(timelineSpy).not.toHaveBeenCalled();

    view.unmount();
  });

  test("活动执行会合并 timeline 历史事件与 ws 实时事件后传给画布", async () => {
    vi.useFakeTimers();
    const timelineEvents: TimelineEventResponse[] = [
      createTimelineEvent({
        payload: {
          agent_id: "orchestrator",
          workflow_id: "wf-001",
          protocol_stage: "FINISH",
          event_type: "agent_finish",
          created_at: "1999-01-01T00:00:00Z",
        },
      }),
      {
        ...createTimelineEvent({
          id: "timeline-002",
          protocol_stage: "ROUTE",
          event_type: "agent_call",
          payload: {
            next_agent_id: "agent-1",
            routing_reason: "start",
          },
          created_at: "2026-07-07T12:00:01Z",
        }),
      },
    ];
    const streamEvents: WebSocketEvent[] = [
      {
        created_at: "2026-07-07T12:00:01Z",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-1",
        routing_reason: "start",
      },
      {
        created_at: "2026-07-07T12:00:02Z",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "done",
        prompt_tokens: 10,
        completion_tokens: 20,
        model: "gpt-4.1",
        model_cost_usd: 0.01,
      },
      {
        event_type: "agent_chunk_stream",
        agent_id: "agent-1",
        text: "hi",
        reasoning: false,
      },
    ];

    vi.mocked(useAgentStream).mockReturnValue({
      wsState: "connected",
      events: streamEvents,
      currentStage: null,
    });

    let resolveGet:
      | ((value: Awaited<ReturnType<typeof executionsApi.get>>) => void)
      | undefined;

    vi.spyOn(executionsApi, "get").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve;
        }),
    );
    let resolveTimeline:
      | ((value: Awaited<ReturnType<typeof executionsApi.timeline>>) => void)
      | undefined;
    vi.spyOn(executionsApi, "timeline").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveTimeline = resolve;
        }),
    );

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      resolveGet?.(createExecution());
      await vi.runAllTimersAsync();
    });

    await act(async () => {
      resolveTimeline?.(timelineEvents);
      await vi.runAllTimersAsync();
    });

    expect(view.container.textContent).toContain("Execution exec-001");
    expect(view.container.textContent).toContain("connected");
    expect(
      view.container.querySelector('[data-testid="agent-canvas"]')?.textContent,
    ).toContain("canvas:1/0");
    expect(useAgentStream).toHaveBeenCalledWith({
      executionId: "exec-001",
      token: "token-123",
    });
    expect(executionsApi.timeline).toHaveBeenCalledWith("exec-001");
    expect(vi.mocked(useCanvasState).mock.calls.at(-1)?.[0]).toEqual([
      {
        agent_id: "orchestrator",
        workflow_id: "wf-001",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        created_at: "2026-07-07T12:00:00Z",
      },
      {
        next_agent_id: "agent-1",
        routing_reason: "start",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        created_at: "2026-07-07T12:00:01Z",
      },
      {
        created_at: "2026-07-07T12:00:02Z",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "done",
        prompt_tokens: 10,
        completion_tokens: 20,
        model: "gpt-4.1",
        model_cost_usd: 0.01,
      },
      {
        event_type: "agent_chunk_stream",
        agent_id: "agent-1",
        text: "hi",
        reasoning: false,
      },
    ]);

    view.unmount();
  });

  test("协议事件会在去重后按 created_at 排序而不是 timeline 全在前", async () => {
    vi.useFakeTimers();
    const timelineEvents: TimelineEventResponse[] = [
      createTimelineEvent({
        id: "timeline-100",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        payload: {
          agent_message: "done",
          prompt_tokens: 10,
          completion_tokens: 20,
          model: "gpt-4.1",
          model_cost_usd: 0.01,
        },
        created_at: "2026-07-07T12:00:02Z",
      }),
      createTimelineEvent({
        id: "timeline-101",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        payload: {
          agent_id: "orchestrator",
          workflow_id: "wf-001",
        },
        created_at: "2026-07-07T12:00:00Z",
      }),
    ];
    const streamEvents: WebSocketEvent[] = [
      {
        created_at: "2026-07-07T12:00:01Z",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-1",
        routing_reason: "start",
      },
      {
        event_type: "agent_chunk_stream",
        agent_id: "agent-1",
        text: "hi",
        reasoning: false,
      },
    ];

    vi.mocked(useAgentStream).mockReturnValue({
      wsState: "connected",
      events: streamEvents,
      currentStage: null,
    });

    let resolveGet:
      | ((value: Awaited<ReturnType<typeof executionsApi.get>>) => void)
      | undefined;

    vi.spyOn(executionsApi, "get").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve;
        }),
    );
    let resolveTimeline:
      | ((value: Awaited<ReturnType<typeof executionsApi.timeline>>) => void)
      | undefined;
    vi.spyOn(executionsApi, "timeline").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveTimeline = resolve;
        }),
    );

    const view = await renderPage();

    await act(async () => {
      resolveGet?.(createExecution());
      await vi.runAllTimersAsync();
    });

    await act(async () => {
      resolveTimeline?.(timelineEvents);
      await vi.runAllTimersAsync();
    });

    expect(vi.mocked(useCanvasState).mock.calls.at(-1)?.[0]).toEqual([
      {
        agent_id: "orchestrator",
        workflow_id: "wf-001",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        created_at: "2026-07-07T12:00:00Z",
      },
      {
        created_at: "2026-07-07T12:00:01Z",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-1",
        routing_reason: "start",
      },
      {
        created_at: "2026-07-07T12:00:02Z",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "done",
        prompt_tokens: 10,
        completion_tokens: 20,
        model: "gpt-4.1",
        model_cost_usd: 0.01,
      },
      {
        event_type: "agent_chunk_stream",
        agent_id: "agent-1",
        text: "hi",
        reasoning: false,
      },
    ]);

    view.unmount();
  });

  test("加载失败时展示错误提示", async () => {
    vi.useFakeTimers();
    const streamEvents: WebSocketEvent[] = [
      {
        event_type: "agent_chunk_stream",
        agent_id: "a1",
        text: "hi",
        reasoning: false,
      },
    ];

    vi.mocked(useAgentStream).mockReturnValue({
      wsState: "connected",
      events: streamEvents,
      currentStage: null,
    });

    let rejectGet: ((reason?: unknown) => void) | undefined;

    vi.spyOn(executionsApi, "get").mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectGet = reject;
        }),
    );

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      rejectGet?.(new Error("request failed"));
      await vi.runAllTimersAsync();
    });

    expect(view.container.textContent).toContain("加载执行详情失败");

    view.unmount();
  });
});
