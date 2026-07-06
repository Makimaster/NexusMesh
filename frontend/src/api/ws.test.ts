import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { WsState } from "../types/protocol";
import { createWsClient } from "./ws";

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
  vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("createWsClient", () => {
  test("connect 后 onopen 触发 state 变 connected", () => {
    const client = createWsClient();
    const states: WsState[] = [];
    client.onStateChange((s) => states.push(s));
    client.connect("exec-1", "tok");
    expect(client.getState()).toBe("connecting");
    MockWebSocket.latest().onopen?.();
    expect(client.getState()).toBe("connected");
    expect(states).toEqual(["connecting", "connected"]);
  });

  test("URL 使用 window.location.host 默认分支且含路径与 token", () => {
    const client = createWsClient();
    client.connect("exec-9", "jwt-x");
    expect(MockWebSocket.latest().url).toContain(
      "/ws/executions/exec-9?token=jwt-x",
    );
  });

  test("常规断线 (1006) 触发退避重连 1s->2s->4s", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok");
    MockWebSocket.latest().onopen?.();

    MockWebSocket.latest().onclose?.({ code: 1006 });
    expect(client.getState()).toBe("disconnected");
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances.length).toBe(1);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(2);

    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1999);
    expect(MockWebSocket.instances.length).toBe(2);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(3);

    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(3999);
    expect(MockWebSocket.instances.length).toBe(3);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(4);
  });

  test("退避上限卡死 30s", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok");
    for (let i = 0; i < 6; i++) {
      MockWebSocket.latest().onclose?.({ code: 1006 });
      vi.advanceTimersByTime(30000);
    }
    const before = MockWebSocket.instances.length;
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(29999);
    expect(MockWebSocket.instances.length).toBe(before);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(before + 1);
  });

  test("onopen 后再断线，退避已复位为 1s", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok");
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000);
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(2000);
    MockWebSocket.latest().onopen?.();
    const before = MockWebSocket.instances.length;
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances.length).toBe(before + 1);
  });

  test("disconnect 后重新 connect 时，新会话首个断线从 1s 重新退避", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok");
    MockWebSocket.latest().onopen?.();

    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000);
    MockWebSocket.latest().onclose?.({ code: 1006 });
    vi.advanceTimersByTime(2000);

    client.disconnect();
    client.connect("exec-1", "tok");
    const before = MockWebSocket.instances.length;
    MockWebSocket.latest().onclose?.({ code: 1006 });

    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances.length).toBe(before);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(before + 1);
  });

  test("策略违规码 1008 触发熔断：state=error 且不重连", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok");
    MockWebSocket.latest().onopen?.();
    MockWebSocket.latest().onclose?.({ code: 1008 });
    expect(client.getState()).toBe("error");
    vi.advanceTimersByTime(60000);
    expect(MockWebSocket.instances.length).toBe(1);
  });

  test("disconnect 清 timer 且后续不重连", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok");
    MockWebSocket.latest().onopen?.();
    client.disconnect();
    expect(client.getState()).toBe("disconnected");
    vi.advanceTimersByTime(60000);
    expect(MockWebSocket.instances.length).toBe(1);
  });

  test("同一 executionId 但不同 token 时会重新建连并使用新 URL", () => {
    const client = createWsClient();
    client.connect("exec-1", "tok-a");
    const firstSocket = MockWebSocket.latest();

    client.connect("exec-1", "tok-b");

    expect(MockWebSocket.instances.length).toBe(2);
    expect(firstSocket.close).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.latest().url).toContain(
      "/ws/executions/exec-1?token=tok-b",
    );
  });

  test("onEvent 收到 message 并可 unsubscribe", () => {
    const client = createWsClient();
    const received: unknown[] = [];
    const unsub = client.onEvent((e) => received.push(e));
    client.connect("exec-1", "tok");
    const payload = {
      protocol_stage: "INIT",
      event_type: "agent_spawn",
      created_at: "t",
      agent_id: "agent-1",
      workflow_id: "wf-1",
    };
    MockWebSocket.latest().onmessage?.({ data: JSON.stringify(payload) });
    expect(received).toHaveLength(1);
    unsub();
    MockWebSocket.latest().onmessage?.({ data: JSON.stringify(payload) });
    expect(received).toHaveLength(1);
  });

  test("脏 JSON 被静默丢弃不抛错", () => {
    const client = createWsClient();
    client.onEvent(() => {});
    client.connect("exec-1", "tok");
    expect(() =>
      MockWebSocket.latest().onmessage?.({ data: "not-json{" }),
    ).not.toThrow();
  });
});
