import { useCallback, useEffect, useState } from 'react';
import { useWebSocket } from './useWebSocket';
import type { ProtocolStage, WebSocketEvent, WsState } from '../types/protocol';

interface UseAgentStreamOptions {
  executionId: string;
  token: string | null;
}

interface AgentStreamState {
  wsState: WsState;
  events: WebSocketEvent[];
  currentStage: ProtocolStage | null;
}

export function useAgentStream(
  { executionId, token }: UseAgentStreamOptions,
): AgentStreamState {
  const [events, setEvents] = useState<WebSocketEvent[]>([]);
  const [currentStage, setCurrentStage] = useState<ProtocolStage | null>(null);

  useEffect(() => {
    setEvents([]);
    setCurrentStage(null);
  }, [executionId]);

  const onEvent = useCallback((event: WebSocketEvent) => {
    if (event.event_type !== 'agent_chunk_stream') {
      setCurrentStage(event.protocol_stage);
    }
    setEvents((prev) => [...prev, event]);
  }, []);

  const { state: wsState } = useWebSocket({ executionId, token, onEvent });
  return { wsState, events, currentStage };
}
