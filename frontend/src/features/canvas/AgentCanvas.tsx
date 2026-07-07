import { Background, Controls, ReactFlow } from "@xyflow/react";
import type { Edge, Node, NodeTypes } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AgentNode } from "./AgentNode";
import type { AgentNodeData } from "./canvasReducer";
import "./canvas.css";

const nodeTypes: NodeTypes = { agentNode: AgentNode };

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
