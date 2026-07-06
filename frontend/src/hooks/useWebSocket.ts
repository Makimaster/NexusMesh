import { useEffect, useRef, useState } from "react";
import { createWsClient } from "../api/ws";
import type { WebSocketEvent, WsClient, WsState } from "../types/protocol";

interface UseWebSocketOptions {
  executionId: string;
  token: string | null;
  onEvent?: (event: WebSocketEvent) => void;
}

interface UseWebSocketResult {
  state: WsState;
}

export function useWebSocket({
  executionId,
  token,
  onEvent,
}: UseWebSocketOptions): UseWebSocketResult {
  const [state, setState] = useState<WsState>("disconnected");
  const clientRef = useRef<WsClient | null>(null);
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!token) return;
    const client = createWsClient();
    clientRef.current = client;
    const unsubState = client.onStateChange(setState);
    const unsubEvent = client.onEvent((ev) => onEventRef.current?.(ev));
    client.connect(executionId, token);
    return () => {
      unsubState();
      unsubEvent();
      client.disconnect();
      clientRef.current = null;
    };
  }, [executionId, token]);

  return { state };
}
