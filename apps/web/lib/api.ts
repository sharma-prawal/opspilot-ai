// All browser traffic goes through the same-origin BFF (/api/ops/*). The operator token is
// attached server-side by the route handler and never reaches the browser.
import type {
  ActionRequest, DependencyHealth, Evidence, Incident, Investigation, KbDocument, Overview, SearchResponse,
  ToolCall, WorkflowEvent,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/ops/${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = body?.error?.message ?? (typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body));
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  overview: () => request<Overview>("api/v1/system/overview"),
  dependencies: () => request<DependencyHealth>("health/dependencies"),
  incidents: () => request<Incident[]>("api/v1/incidents"),
  incident: (id: string) => request<Incident>(`api/v1/incidents/${id}`),
  scenarios: () => request<{ key: string; title: string }[]>("api/v1/incidents/scenarios"),
  simulate: (scenario: string) => post<Incident>("api/v1/incidents/simulate", { scenario }),
  incidentInvestigations: (id: string) => request<Investigation[]>(`api/v1/incidents/${id}/investigations`),
  startInvestigation: (id: string) =>
    post<{ investigation_id: string; status: string }>(`api/v1/incidents/${id}/investigations`),
  investigation: (id: string) => request<Investigation>(`api/v1/investigations/${id}`),
  events: (id: string) => request<WorkflowEvent[]>(`api/v1/investigations/${id}/events`),
  toolCalls: (id: string) => request<ToolCall[]>(`api/v1/investigations/${id}/tool-calls`),
  evidence: (id: string) => request<Evidence[]>(`api/v1/investigations/${id}/evidence`),
  actions: (id: string) => request<ActionRequest[]>(`api/v1/investigations/${id}/actions`),
  report: (id: string) => request<{ markdown: string; status: string }>(`api/v1/investigations/${id}/report`),
  resume: (id: string) => post(`api/v1/investigations/${id}/resume`),
  cancel: (id: string, actor: string) => post(`api/v1/investigations/${id}/cancel`, { actor }),
  approvals: (status = "pending") => request<ActionRequest[]>(`api/v1/approvals?status=${status}`),
  decide: (actionId: string, body: { decision: "approve" | "reject"; params_hash: string; decided_by: string; comment?: string }) =>
    post<ActionRequest>(`api/v1/approvals/${actionId}/decision`, body),
  search: (query: string, mode: string, top_k = 8) => post<SearchResponse>("api/v1/knowledge/search", { query, mode, top_k }),
  documents: () => request<KbDocument[]>("api/v1/knowledge/documents"),
};
