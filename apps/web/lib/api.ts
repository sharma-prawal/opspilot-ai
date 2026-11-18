// All browser traffic goes through the same-origin BFF (/api/ops/*). The operator token is
// attached server-side by the route handler and never reaches the browser.
import type {
  ActionRequest, ConnectedIncidentRequest, ConnectedPreview, ConnectedRequest, ConnectionStatus, ConnectorId,
  ConnectorList, DependencyHealth, Evidence, Incident, Investigation, KbDocument, Overview, SearchResponse,
  ToolCall, UploadedDataset, UploadIncidentRequest, UploadPreview, UploadRequest, WorkflowEvent,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export interface SessionInfo { authenticated: boolean; sub?: string; role?: "viewer" | "operator"; csrf?: string }

let sessionCache: SessionInfo | null = null;

export async function getSession(force = false): Promise<SessionInfo> {
  if (sessionCache && !force) return sessionCache;
  const res = await fetch("/api/session", { cache: "no-store" });
  sessionCache = res.ok ? ((await res.json()) as SessionInfo) : { authenticated: false };
  return sessionCache;
}

export function clearSession(): void { sessionCache = null; }

export const UNAUTHENTICATED_EVENT = "opspilot:unauthenticated";

function toLogin(): void {
  // Handled by <Providers>, which navigates with the Next router.
  if (typeof window !== "undefined") window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (init?.method === "POST") {
    const s = await getSession();
    if (s.csrf) headers["x-opspilot-csrf"] = s.csrf;
  }
  const res = await fetch(`/api/ops/${path}`, { ...init, headers, cache: "no-store" });
  if (res.status === 401) {
    clearSession();
    toLogin();
  }
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
  // v0.5 uploaded evidence: files are read as text in the browser and sent as JSON through the BFF.
  uploadPreview: (body: UploadRequest) => post<UploadPreview>("api/v1/incidents/upload/preview", body),
  uploadIncident: (body: UploadIncidentRequest) => post<Incident>("api/v1/incidents/upload", body),
  dataset: (id: string) => request<UploadedDataset>(`api/v1/incidents/${id}/dataset`),
  discardUpload: (id: string) => post<{ incident_id: string; files_removed: boolean }>(`api/v1/incidents/${id}/discard`),
  // v0.6 connected observability: configured Loki/Prometheus only; requests carry IDs and a window, never a URL.
  connectors: () => request<ConnectorList>("api/v1/connectors"),
  testConnector: (id: ConnectorId) => post<ConnectionStatus>(`api/v1/connectors/${id}/test`),
  connectorServices: (id: ConnectorId, window: { start: string; end: string }) =>
    post<{ connector: string; services: string[]; error: { kind: string; message: string } | null }>(
      `api/v1/connectors/${id}/services`, window),
  connectedPreview: (body: ConnectedRequest) => post<ConnectedPreview>("api/v1/incidents/connected/preview", body),
  connectedIncident: (body: ConnectedIncidentRequest) => post<Incident>("api/v1/incidents/connected", body),
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
  cancel: (id: string) => post(`api/v1/investigations/${id}/cancel`, {}),
  approvals: (status = "pending") => request<ActionRequest[]>(`api/v1/approvals?status=${status}`),
  // decided_by / actor are set server-side from the signed-in session; any client value is overwritten.
  decide: (actionId: string, body: { decision: "approve" | "reject"; params_hash: string; comment?: string }) =>
    post<ActionRequest>(`api/v1/approvals/${actionId}/decision`, body),
  search: (query: string, mode: string, top_k = 8) => post<SearchResponse>("api/v1/knowledge/search", { query, mode, top_k }),
  documents: () => request<KbDocument[]>("api/v1/knowledge/documents"),
};
