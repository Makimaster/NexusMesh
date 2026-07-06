import type {
  AgentListItem,
  AgentRequest,
  AgentResponse,
  AgentUpdateRequest,
} from "../types/protocol";
import { http } from "./http";

export const agentsApi = {
  list: (limit = 20, offset = 0) =>
    http
      .get<AgentListItem[]>("/agents", { params: { limit, offset } })
      .then((r) => r.data),
  get: (id: string) =>
    http.get<AgentResponse>(`/agents/${id}`).then((r) => r.data),
  create: (payload: AgentRequest) =>
    http.post<AgentResponse>("/agents", payload).then((r) => r.data),
  update: (id: string, payload: AgentUpdateRequest) =>
    http.patch<AgentResponse>(`/agents/${id}`, payload).then((r) => r.data),
  delete: (id: string) => http.delete(`/agents/${id}`).then(() => undefined),
};
