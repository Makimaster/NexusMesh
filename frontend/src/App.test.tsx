import React, { act } from "react";
import ReactDOM from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, test } from "vitest";

import App from "./App";

function renderApp(initialEntry: string) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <App />
      </MemoryRouter>,
    );
  });

  return {
    container,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("App routes", () => {
  test("未知路径兜底重定向到 /agents 并展示骨架页标题", () => {
    const view = renderApp("/unknown");

    expect(view.container.textContent).toContain("Agents");

    view.unmount();
  });

  test("AppShell 布局路由可承载骨架页内容", () => {
    const view = renderApp("/workflows");

    expect(view.container.querySelector("main")?.textContent).toContain(
      "Workflows",
    );

    view.unmount();
  });
});
