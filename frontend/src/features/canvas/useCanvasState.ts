import { useMemo } from "react";
import type { WebSocketEvent } from "../../types/protocol";
import type { CanvasGraph } from "./canvasReducer";
import { applyDagreLayout, reduceEvents } from "./canvasReducer";

export function useCanvasState(events: WebSocketEvent[]): CanvasGraph {
  return useMemo(() => {
    const { nodes, edges } = reduceEvents(events);

    return {
      nodes: applyDagreLayout(nodes, edges),
      edges,
    };
  }, [events]);
}
