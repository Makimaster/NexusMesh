import type { Edge, Node } from "@xyflow/react";
import type { WebSocketEvent } from "../../types/protocol";

export type NodeStatus = "running" | "finished" | "error";

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

function createNode(agentId: string): Node<AgentNodeData> {
  return {
    id: agentId,
    type: "agentNode",
    position: { x: 0, y: 0 },
    data: {
      label: agentId,
      status: "running",
    },
  };
}

export function reduceEvents(events: WebSocketEvent[]): CanvasGraph {
  const nodes = new Map<string, Node<AgentNodeData>>();
  const edges: Edge[] = [];

  let orchestratorAgentId: string | null = null;
  let currentAgentId: string | null = null;
  let lastSource: string | null = null;

  const ensureNode = (agentId: string): Node<AgentNodeData> => {
    const existingNode = nodes.get(agentId);
    if (existingNode) {
      return existingNode;
    }

    const nextNode = createNode(agentId);
    nodes.set(agentId, nextNode);
    return nextNode;
  };

  const addEdge = (source: string, target: string) => {
    edges.push({
      id: `${source}->${target}-${edges.length}`,
      source,
      target,
    });
  };

  for (const event of events) {
    if (event.event_type === "agent_chunk_stream") {
      continue;
    }

    if (event.protocol_stage === "INIT") {
      orchestratorAgentId = event.agent_id;
      ensureNode(event.agent_id).data.status = "running";
      lastSource = event.agent_id;
      continue;
    }

    if (event.protocol_stage === "ROUTE") {
      if (!event.next_agent_id) {
        continue;
      }

      ensureNode(event.next_agent_id).data.status = "running";

      if (lastSource) {
        addEdge(lastSource, event.next_agent_id);
      }

      currentAgentId = event.next_agent_id;
      continue;
    }

    if (event.protocol_stage === "EXECUTE") {
      if (!currentAgentId) {
        continue;
      }

      const node = ensureNode(currentAgentId);
      node.data.status = "finished";
      node.data.agentMessage = event.agent_message;
      node.data.tokens = event.prompt_tokens + event.completion_tokens;
      node.data.model = event.model;
      lastSource = currentAgentId;
      continue;
    }

    if (event.protocol_stage === "FINISH") {
      if (!orchestratorAgentId) {
        continue;
      }

      const orchestratorNode = ensureNode(orchestratorAgentId);
      if (event.success) {
        orchestratorNode.data.status = "finished";
      } else {
        orchestratorNode.data.status = "error";
      }
    }
  }

  return { nodes: Array.from(nodes.values()), edges };
}
