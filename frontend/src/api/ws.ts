import type { WebSocketEvent, WsClient, WsState } from "../types/protocol";

export function createWsClient(): WsClient {
  let socket: WebSocket | null = null;
  let currentState: WsState = "disconnected";
  let currentExecutionId: string | null = null;
  let currentToken: string | null = null;
  let reconnectDelay = 1000;
  let reconnectTimer: number | null = null;

  const eventHandlers = new Set<(event: WebSocketEvent) => void>();
  const stateHandlers = new Set<(state: WsState) => void>();

  function changeState(nextState: WsState) {
    if (currentState === nextState) return;
    currentState = nextState;
    for (const handler of stateHandlers) {
      handler(currentState);
    }
  }

  function resetConnection(resetReconnectDelay: boolean) {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (resetReconnectDelay) {
      reconnectDelay = 1000;
    }
    currentExecutionId = null;
    currentToken = null;
    if (socket) {
      const tempSocket = socket;
      socket = null;
      changeState("disconnected");
      tempSocket.close();
    } else {
      changeState("disconnected");
    }
  }

  function connect(
    executionId: string,
    token: string,
    resetReconnectDelay = true,
  ) {
    if (socket && currentExecutionId === executionId && currentToken === token)
      return;
    resetConnection(resetReconnectDelay);

    currentExecutionId = executionId;
    currentToken = token;
    changeState("connecting");

    const baseWsUrl =
      import.meta.env.VITE_WS_URL || `ws://${window.location.host}`;
    const wsUrl = `${baseWsUrl}/ws/executions/${executionId}?token=${token}`;
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      reconnectDelay = 1000;
      changeState("connected");
    };

    socket.onmessage = (event) => {
      try {
        const parsed: WebSocketEvent = JSON.parse(event.data);
        for (const handler of eventHandlers) {
          handler(parsed);
        }
      } catch {}
    };

    socket.onclose = (event) => {
      socket = null;
      if (event.code === 1008 || event.code >= 4000) {
        changeState("error");
        return;
      }
      if (currentState === "disconnected") return;
      changeState("disconnected");
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        if (currentExecutionId && currentToken) {
          reconnectDelay = Math.min(30000, reconnectDelay * 2);
          connect(currentExecutionId, currentToken, false);
        }
      }, reconnectDelay);
    };
  }

  function disconnect() {
    resetConnection(true);
  }

  return {
    connect,
    disconnect,
    onEvent: (handler) => {
      eventHandlers.add(handler);
      return () => eventHandlers.delete(handler);
    },
    onStateChange: (handler) => {
      stateHandlers.add(handler);
      return () => stateHandlers.delete(handler);
    },
    getState: () => currentState,
  };
}
