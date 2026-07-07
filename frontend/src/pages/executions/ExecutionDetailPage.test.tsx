import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import ReactDOM from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, test, vi } from "vitest";

import { executionsApi } from "../../api/executions";
import { useCanvasState } from "../../features/canvas/useCanvasState";
import { useAgentStream } from "../../hooks/useAgentStream";
import type { WebSocketEvent } from "../../types/protocol";
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

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      resolveGet?.({
        id: "exec-001",
        workflow_id: "wf-001",
        status: "completed",
        started_at: null,
        finished_at: null,
        created_at: "2026-07-07T12:00:00Z",
        input: {},
        output: null,
        error: null,
      });
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

    view.unmount();
  });

  test("活动执行显示 ws 状态和画布", async () => {
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

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      resolveGet?.({
        id: "exec-001",
        workflow_id: "wf-001",
        status: "running",
        started_at: "2026-07-07T12:00:00Z",
        finished_at: null,
        created_at: "2026-07-07T12:00:00Z",
        input: {},
        output: null,
        error: null,
      });
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
    expect(useCanvasState).toHaveBeenCalledWith(streamEvents);

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
