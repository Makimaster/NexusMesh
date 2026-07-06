import { http } from './http';
import type {
  ExecutionListItem,
  ExecutionResponse,
  TimelineEventResponse,
} from '../types/protocol';

export interface ExecutionListParams {
  workflow_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const executionsApi = {
  list: (params: ExecutionListParams = {}) =>
    http
      .get<ExecutionListItem[]>('/executions', { params: { limit: 20, offset: 0, ...params } })
      .then((r) => r.data),
  get: (id: string) =>
    http.get<ExecutionResponse>(`/executions/${id}`).then((r) => r.data),
  timeline: (id: string) =>
    http.get<TimelineEventResponse[]>(`/executions/${id}/timeline`).then((r) => r.data),
};
