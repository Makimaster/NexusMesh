import { describe, expect, test } from "vitest";
import type { WebSocketEvent } from "../../types/protocol";
import { applyDagreLayout, reduceEvents } from "./canvasReducer";

describe("reduceEvents", () => {
  test("单 INIT 事件创建 orchestrator 节点", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "2026-01-01T00:00:00Z",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orchestrator",
        workflow_id: "wf-1",
      },
    ];
    const { nodes, edges } = reduceEvents(events);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].id).toBe("orchestrator");
    expect(nodes[0].type).toBe("agentNode");
    expect(nodes[0].data.status).toBe("running");
    expect(edges).toHaveLength(0);
  });

  test("完整串行链：INIT→ROUTE(A)→EXECUTE→ROUTE(B)→EXECUTE→ROUTE(null)→FINISH", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "t0",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orchestrator",
        workflow_id: "w1",
      },
      {
        created_at: "t1",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-A",
        routing_reason: "start",
      },
      {
        created_at: "t2",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "A done",
        prompt_tokens: 10,
        completion_tokens: 20,
        model: "gpt-4",
        model_cost_usd: 0.01,
      },
      {
        created_at: "t3",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-B",
        routing_reason: "next",
      },
      {
        created_at: "t4",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "B done",
        prompt_tokens: 15,
        completion_tokens: 25,
        model: "gpt-4",
        model_cost_usd: 0.02,
      },
      {
        created_at: "t5",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: null,
        routing_reason: "end",
      },
      {
        created_at: "t6",
        protocol_stage: "FINISH",
        event_type: "agent_finish",
        success: true,
        output: { message: "B done" },
      },
    ];
    const { nodes, edges } = reduceEvents(events);
    const orchestratorNode = nodes.find((node) => node.id === "orchestrator");
    const agentANode = nodes.find((node) => node.id === "agent-A");
    const agentBNode = nodes.find((node) => node.id === "agent-B");

    expect(nodes).toHaveLength(3);
    expect(orchestratorNode?.data.status).toBe("finished");
    expect(agentANode?.data.status).toBe("finished");
    expect(agentBNode?.data.status).toBe("finished");
    expect(edges).toHaveLength(2);
    expect(edges[0].source).toBe("orchestrator");
    expect(edges[0].target).toBe("agent-A");
    expect(edges[1].source).toBe("agent-A");
    expect(edges[1].target).toBe("agent-B");
  });

  test("循环图边 ID 唯一", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "t0",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orch",
        workflow_id: "w",
      },
      {
        created_at: "t1",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "A",
        routing_reason: null,
      },
      {
        created_at: "t2",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "",
        prompt_tokens: 1,
        completion_tokens: 1,
        model: "m",
        model_cost_usd: 0,
      },
      {
        created_at: "t3",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "B",
        routing_reason: null,
      },
      {
        created_at: "t4",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "",
        prompt_tokens: 1,
        completion_tokens: 1,
        model: "m",
        model_cost_usd: 0,
      },
      {
        created_at: "t5",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "A",
        routing_reason: null,
      },
      {
        created_at: "t6",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "",
        prompt_tokens: 1,
        completion_tokens: 1,
        model: "m",
        model_cost_usd: 0,
      },
    ];
    const { edges } = reduceEvents(events);
    const edgeIds = edges.map((e) => e.id);
    expect(new Set(edgeIds).size).toBe(edgeIds.length);
    expect(edgeIds[0]).toBe("orch->A-0");
    expect(edgeIds[1]).toBe("A->B-1");
    expect(edgeIds[2]).toBe("B->A-2");
  });

  test("lastSource 在 EXECUTE 后更新", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "t0",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orchestrator",
        workflow_id: "w",
      },
      {
        created_at: "t1",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-A",
        routing_reason: "first",
      },
      {
        created_at: "t2",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "A done",
        prompt_tokens: 2,
        completion_tokens: 3,
        model: "gpt-4",
        model_cost_usd: 0.01,
      },
      {
        created_at: "t3",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-B",
        routing_reason: "second",
      },
      {
        created_at: "t4",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-C",
        routing_reason: "third",
      },
    ];
    const { nodes, edges } = reduceEvents(events);
    const agentCNode = nodes.find((node) => node.id === "agent-C");

    expect(edges).toHaveLength(3);
    expect(edges[0].source).toBe("orchestrator");
    expect(edges[0].target).toBe("agent-A");
    expect(edges[1].source).toBe("agent-A");
    expect(edges[1].target).toBe("agent-B");
    expect(edges[2].source).toBe("agent-A");
    expect(edges[2].target).toBe("agent-C");
    expect(edges[0].id).toBe("orchestrator->agent-A-0");
    expect(edges[1].id).toBe("agent-A->agent-B-1");
    expect(edges[2].id).toBe("agent-A->agent-C-2");
    expect(agentCNode?.data.status).toBe("running");
  });

  test("FINISH success=false → orchestrator error", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "t0",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orchestrator",
        workflow_id: "w",
      },
      {
        created_at: "t1",
        protocol_stage: "FINISH",
        event_type: "agent_finish",
        success: false,
        output: { error: "fail" },
      },
    ];
    const { nodes } = reduceEvents(events);
    expect(nodes[0].data.status).toBe("error");
  });

  test("FINISH success=false 只标记 orchestrator 为 error", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "t0",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orchestrator",
        workflow_id: "w",
      },
      {
        created_at: "t1",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "agent-A",
        routing_reason: "start",
      },
      {
        created_at: "t2",
        protocol_stage: "EXECUTE",
        event_type: "agent_finish",
        agent_message: "A done",
        prompt_tokens: 10,
        completion_tokens: 20,
        model: "gpt-4",
        model_cost_usd: 0.01,
      },
      {
        created_at: "t3",
        protocol_stage: "FINISH",
        event_type: "agent_finish",
        success: false,
        output: { error: "fail" },
      },
    ];
    const { nodes } = reduceEvents(events);
    const orchestratorNode = nodes.find((node) => node.id === "orchestrator");
    const agentNode = nodes.find((node) => node.id === "agent-A");

    expect(orchestratorNode?.data.status).toBe("error");
    expect(agentNode?.data.status).toBe("finished");
  });

  test("agent_chunk_stream 被跳过", () => {
    const events: WebSocketEvent[] = [
      {
        created_at: "t0",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orch",
        workflow_id: "w",
      },
      {
        event_type: "agent_chunk_stream",
        agent_id: "a",
        text: "chunk",
        reasoning: false,
      },
    ];
    const { nodes } = reduceEvents(events);
    expect(nodes).toHaveLength(1);
  });
});

describe("applyDagreLayout", () => {
  test("dagre 生成自上而下的层次布局", () => {
    const { nodes, edges } = reduceEvents([
      {
        created_at: "t",
        protocol_stage: "INIT",
        event_type: "agent_spawn",
        agent_id: "orch",
        workflow_id: "w",
      },
      {
        created_at: "t",
        protocol_stage: "ROUTE",
        event_type: "agent_call",
        next_agent_id: "A",
        routing_reason: null,
      },
    ]);

    const laid = applyDagreLayout(nodes, edges);
    const orch = laid.find((node) => node.id === "orch");
    const agentA = laid.find((node) => node.id === "A");

    expect(orch).toBeDefined();
    expect(agentA).toBeDefined();
    expect(orch?.position).toEqual({ x: 0, y: 0 });
    expect(agentA?.position.y).toBeGreaterThan(orch?.position.y ?? 0);
    expect(agentA?.position).not.toEqual(orch?.position);
  });
});
