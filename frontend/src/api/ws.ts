import type { WebSocketEvent, WsClient, WsState } from '../types/protocol';

export function createWsClient(): WsClient {
  let socket: WebSocket | null = null;
  let currentState: WsState = 'disconnected';
  let currentExecutionId: string | null = null;
  let currentToken: string | null = null;
  let reconnectDelay = 1000;
  let reconnectTimer: number | null = null;

  const eventHandlers = new Set<(event: WebSocketEvent) => void>();
  const stateHandlers = new Set<(state: WsState) => void>();

  function changeState(nextState: WsState) {
    if (currentState === nextState) return;
    currentState = nextState;
    stateHandlers.forEach((handler) => handler(currentState));
  }

  function connect(executionId: string, token: string) {
    if (socket && currentExecutionId === executionId) return;
    disconnect();

    currentExecutionId = executionId;
    currentToken = token;
    changeState('connecting');

    const baseWsUrl = import.meta.env.VITE_WS_URL || `ws://${window.location.host}`;
    const wsUrl = `${baseWsUrl}/ws/executions/${executionId}?token=${token}`;
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      reconnectDelay = 1000;
      changeState('connected');
    };

    socket.onmessage = (event) => {
      try {
        const parsed: WebSocketEvent = JSON.parse(event.data);
        eventHandlers.forEach((handler) => handler(parsed));
      } catch {
      }
    };

    socket.onclose = (event) => {
      socket = null;
      if (event.code === 1008 || event.code >= 4000) {
        changeState('error');
        return;
      }
      if (currentState === 'disconnected') return;
      changeState('disconnected');
      reconnectTimer = window.setTimeout(() => {
        if (currentExecutionId && currentToken) {
          reconnectDelay = Math.min(30000, reconnectDelay * 2);
          connect(currentExecutionId, currentToken);
        }
      }, reconnectDelay);
    };
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    currentExecutionId = null;
    currentToken = null;
    if (socket) {
      const tempSocket = socket;
      socket = null;
      changeState('disconnected');
      tempSocket.close();
    } else {
      changeState('disconnected');
    }
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
