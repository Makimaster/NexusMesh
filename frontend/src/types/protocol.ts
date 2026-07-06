// ============ REST Request Types ============
export interface AgentRequest {
  name: string;
  description?: string;
  agent_type: string;
  llm_provider: string;
  llm_model: string;
  system_prompt?: string;
  config: Record<string, unknown>;
}

export interface AgentUpdateRequest {
  name?: string;
  description?: string;
  agent_type?: string;
  llm_provider?: string;
  llm_model?: string;
  system_prompt?: string;
  config?: Record<string, unknown>;
}

export interface WorkflowRequest {
  name: string;
  description?: string;
  topology: Record<string, unknown>;
}

export interface WorkflowUpdateRequest {
  name?: string;
  description?: string;
  topology?: Record<string, unknown>;
}

export interface TriggerRequest {
  task_input: Record<string, unknown>;
}

// ============ REST Response Types ============
export interface AgentListItem {
  id: string;
  name: string;
  description: string | null;
  agent_type: string;
  llm_provider: string;
  llm_model: string;
  created_at: string;
}

export interface AgentResponse extends AgentListItem {
  system_prompt: string | null;
  config: Record<string, unknown>;
}

export interface WorkflowListItem {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface WorkflowResponse extends WorkflowListItem {
  topology: Record<string, unknown>;
}

export interface ExecutionListItem {
  id: string;
  workflow_id: string | null;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ExecutionResponse extends ExecutionListItem {
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface ExecutionAcceptedResponse {
  execution_id: string;
}

export interface TimelineEventResponse {
  id: string;
  execution_id: string | null;
  protocol_stage: ProtocolStage;
  event_type: EventType;
  payload: Record<string, unknown>;
  created_at: string;
}

// ============ WebSocket Protocol Types ============
export type ProtocolStage = 'INIT' | 'RECEIVE' | 'ROUTE' | 'EXECUTE' | 'FINISH';
export type EventType = 'agent_spawn' | 'agent_call' | 'agent_finish' | 'agent_reflect';

export interface WebSocketEvent {
  execution_id: string;
  protocol_stage: ProtocolStage;
  event_type: EventType;
  payload: Record<string, unknown>;
  timestamp: string;
}

export type WsState = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WsClient {
  connect(executionId: string, token: string): void;
  disconnect(): void;
  onEvent(handler: (event: WebSocketEvent) => void): () => void;
  onStateChange(handler: (state: WsState) => void): () => void;
  getState(): WsState;
}
