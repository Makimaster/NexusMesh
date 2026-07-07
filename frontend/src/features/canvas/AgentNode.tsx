import { Handle, Position } from "@xyflow/react";
import type { Node, NodeProps } from "@xyflow/react";
import type { AgentNodeData, NodeStatus } from "./canvasReducer";

type AgentFlowNode = Node<AgentNodeData, "agentNode">;

const STATUS_COLOR: Record<NodeStatus, string> = {
  running: "#3b82f6",
  finished: "#22c55e",
  error: "#ef4444",
};

export function AgentNode({ data }: NodeProps<AgentFlowNode>) {
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
