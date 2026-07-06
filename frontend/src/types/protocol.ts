// ============ REST Request Types ============
export interface AgentRequest {
  name: string;
  description?: string;
  agent_type: string;
  llm_provider: string;
  llm_model: string;
  system_prompt?: string;
  config?: Record<string, unknown>;
}

export interface AgentUpdateRequest {
  name?: string | null;
  description?: string | null;
  agent_type?: string | null;
  llm_provider?: string | null;
  llm_model?: string | null;
  system_prompt?: string | null;
  config?: Record<string, unknown> | null;
}

export interface WorkflowRequest {
  name: string;
  description?: string;
  topology?: Record<string, unknown>;
}

export interface WorkflowUpdateRequest {
  name?: string | null;
  description?: string | null;
  topology?: Record<string, unknown> | null;
}

export interface TriggerRequest {
  task_input?: Record<string, unknown>;
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
  protocol_stage: string;
  event_type: string;
  created_at: string;
}

// ============ WebSocket Protocol Types ============
export type ProtocolStage = 'INIT' | 'RECEIVE' | 'ROUTE' | 'EXECUTE' | 'FINISH';
export type ProtocolEventType = 'agent_spawn' | 'agent_call' | 'agent_finish' | 'agent_reflect';
export type StreamEventType = 'agent_chunk_stream';
export type EventType = ProtocolEventType | StreamEventType;

interface BaseProtocolWsEvent {
  created_at: string;
  protocol_stage: ProtocolStage;
  event_type: ProtocolEventType;
}

export interface InitWsEvent extends BaseProtocolWsEvent {
  protocol_stage: 'INIT';
  agent_id: string;
  workflow_id: string;
}

export interface ReceiveWsEvent extends BaseProtocolWsEvent {
  protocol_stage: 'RECEIVE';
  task_input: Record<string, unknown>;
}

export interface RouteWsEvent extends BaseProtocolWsEvent {
  protocol_stage: 'ROUTE';
  next_agent_id: string | null;
  routing_reason: string | null;
}

export interface ExecuteWsEvent extends BaseProtocolWsEvent {
  protocol_stage: 'EXECUTE';
  agent_message: string;
  prompt_tokens: number;
  completion_tokens: number;
  model: string;
  model_cost_usd: number;
}

export interface FinishWsEvent extends BaseProtocolWsEvent {
  protocol_stage: 'FINISH';
  success: boolean;
  output: Record<string, unknown> | null;
}

export interface AgentChunkStreamEvent {
  event_type: 'agent_chunk_stream';
  agent_id: string;
  text: string;
  reasoning: boolean;
}

export type WebSocketEvent =
  | InitWsEvent
  | ReceiveWsEvent
  | RouteWsEvent
  | ExecuteWsEvent
  | FinishWsEvent
  | AgentChunkStreamEvent;

export type WsState = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WsClient {
  connect(executionId: string, token: string): void;
  disconnect(): void;
  onEvent(handler: (event: WebSocketEvent) => void): () => void;
  onStateChange(handler: (state: WsState) => void): () => void;
  getState(): WsState;
}
