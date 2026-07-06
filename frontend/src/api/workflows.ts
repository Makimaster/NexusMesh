import type {
  ExecutionAcceptedResponse,
  TriggerRequest,
  WorkflowListItem,
  WorkflowRequest,
  WorkflowResponse,
  WorkflowUpdateRequest,
} from "../types/protocol";
import { http } from "./http";

export const workflowsApi = {
  list: (limit = 20, offset = 0) =>
    http
      .get<WorkflowListItem[]>("/workflows", { params: { limit, offset } })
      .then((r) => r.data),
  get: (id: string) =>
    http.get<WorkflowResponse>(`/workflows/${id}`).then((r) => r.data),
  create: (payload: WorkflowRequest) =>
    http.post<WorkflowResponse>("/workflows", payload).then((r) => r.data),
  update: (id: string, payload: WorkflowUpdateRequest) =>
    http
      .patch<WorkflowResponse>(`/workflows/${id}`, payload)
      .then((r) => r.data),
  delete: (id: string) => http.delete(`/workflows/${id}`).then(() => undefined),
  trigger: (id: string, payload: TriggerRequest) =>
    http
      .post<ExecutionAcceptedResponse>(`/workflows/${id}/execute`, payload)
      .then((r) => r.data),
};
