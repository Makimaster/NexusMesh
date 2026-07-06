import { useCallback, useEffect, useState } from "react";
import type { ProtocolStage, WebSocketEvent, WsState } from "../types/protocol";
import { useWebSocket } from "./useWebSocket";

interface UseAgentStreamOptions {
  executionId: string;
  token: string | null;
}

interface AgentStreamState {
  wsState: WsState;
  events: WebSocketEvent[];
  currentStage: ProtocolStage | null;
}

export function useAgentStream({
  executionId,
  token,
}: UseAgentStreamOptions): AgentStreamState {
  const [events, setEvents] = useState<WebSocketEvent[]>([]);
  const [currentStage, setCurrentStage] = useState<ProtocolStage | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: executionId intentionally acts as the reset trigger for stream state.
  useEffect(() => {
    setEvents([]);
    setCurrentStage(null);
  }, [executionId]);

  const onEvent = useCallback((event: WebSocketEvent) => {
    if (event.event_type !== "agent_chunk_stream") {
      setCurrentStage(event.protocol_stage);
    }
    setEvents((prev) => [...prev, event]);
  }, []);

  const { state: wsState } = useWebSocket({ executionId, token, onEvent });
  return { wsState, events, currentStage };
}
