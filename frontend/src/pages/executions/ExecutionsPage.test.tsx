import { act } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, test, vi } from "vitest";

import { executionsApi } from "../../api/executions";
import type { ExecutionListItem } from "../../types/protocol";
import ExecutionsPage from "./ExecutionsPage";

(
  globalThis as typeof globalThis & {
    IS_REACT_ACT_ENVIRONMENT?: boolean;
  }
).IS_REACT_ACT_ENVIRONMENT = true;

async function renderPage() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ExecutionsPage />
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

describe("ExecutionsPage", () => {
  test("加载完成后展示执行列表条目", async () => {
    vi.useFakeTimers();

    let resolveList: ((value: ExecutionListItem[]) => void) | undefined;
    const mockExecution: ExecutionListItem[] = [
      {
        id: "exec-001",
        workflow_id: "wf-001",
        status: "running",
        started_at: null,
        finished_at: null,
        created_at: "2026-07-07T12:00:00Z",
      },
    ];

    vi.spyOn(executionsApi, "list").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveList = resolve;
        }),
    );

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      resolveList?.(mockExecution);
      await vi.runAllTimersAsync();
    });

    expect(view.container.textContent).toContain("exec-001");
    expect(view.container.textContent).toContain("running");
    expect(
      view.container.querySelector('a[href="/executions/exec-001"]'),
    ).not.toBeNull();

    view.unmount();
  });

  test("加载失败时展示错误提示", async () => {
    vi.useFakeTimers();

    let rejectList: ((reason?: unknown) => void) | undefined;

    vi.spyOn(executionsApi, "list").mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectList = reject;
        }),
    );

    const view = await renderPage();

    expect(view.container.textContent).toContain("加载中…");

    await act(async () => {
      rejectList?.(new Error("request failed"));
      await vi.runAllTimersAsync();
    });

    expect(view.container.textContent).toContain("加载执行列表失败");

    view.unmount();
  });
});
