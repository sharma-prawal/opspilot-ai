// Response shapes of the OpsPilot API (see docs/architecture/API_CONTRACTS.md).

export type IncidentStatus = "open" | "investigating" | "awaiting_approval" | "mitigated" | "resolved";
export type InvestigationStatus =
  | "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled" | "interrupted";

export type EvidenceSource = "simulator" | "upload" | "connector";

export interface Incident {
  id: string; reference: string; title: string; description: string; severity: string;
  status: IncidentStatus; service: string; environment_id: string | null; evidence_source: EvidenceSource;
  detected_at: string; created_at: string;
}

// ---- v0.5 uploaded evidence ----------------------------------------------------------------------------------
export type SignalType = "log" | "metric" | "span" | "event";

export interface UploadFileReport {
  index: number; name: string; original_name: string; extension: string; bytes: number; sha256: string;
  format: string; declared_service: string | null; records: Partial<Record<SignalType, number>>; rejected: number;
  redactions: number; issues: string[]; services: string[]; timezones: string[]; start: string | null; end: string | null;
}

export interface UploadSummary {
  records: Record<SignalType, number>; rejected: number; redactions: number; services: string[];
  metrics_by_service: Record<string, string[]>; event_types: string[]; start: string | null; end: string | null;
  timezones: string[];
}

export interface NormalizedRecord {
  ts: string; ts_original: string; tz: string; service: string; service_source: "record" | "file_default" | "query";
  source: string; level?: string; level_inferred?: boolean; message?: string; metric?: string; value?: number;
  unit?: string; name?: string; status?: string; duration_ms?: number | null; trace_id?: string | null;
  span_id?: string; parent_span_id?: string | null; status_message?: string | null; kind?: string | null;
  event_type?: string; summary?: string; attributes?: Record<string, unknown>;
}

export interface UploadPreview {
  usable: boolean; files: UploadFileReport[]; summary: UploadSummary; warnings: string[];
  samples: Record<SignalType, NormalizedRecord[]>;
  limits: { max_files: number; max_file_bytes: number; max_total_bytes: number; max_records: number; extensions: string[] };
}

export interface UploadFileIn { name: string; content: string; service: string | null }

export interface UploadRequest {
  files: UploadFileIn[]; timezone: string; incident_time: string | null; service: string | null;
  affected_services: string[];
}

export interface UploadIncidentRequest extends UploadRequest {
  title: string; description: string; service: string; severity: string; incident_time: string;
}

export interface UploadedDataset {
  dataset_id: string; incident_id: string; timezone: string; affected_services: string[]; files: UploadFileReport[];
  queries: QueryProvenance[]; // v0.6 connector snapshots; empty for uploads
  summary: UploadSummary & {
    samples: Record<SignalType, NormalizedRecord[]>; warnings: string[];
    window?: { start: string; end: string }; connectors?: string[];
  };
  created_at: string; retention_days: number;
}

// ---- v0.6 connected observability (Datadog: v0.9, Azure Monitor: v0.10, AWS CloudWatch: v0.11) ------------------
export type ConnectorId = "loki" | "prometheus" | "datadog" | "azure_monitor" | "cloudwatch";
export type TelemetrySignal = "log" | "metric" | "span";

export interface QueryTemplate {
  id: string; connector: ConnectorId; label: string; description: string; query: string; metric: string | null;
  unit: string; default: boolean; source: "built-in" | "file"; signal?: TelemetrySignal | null; expand_traces?: number;
}

export interface ConnectorInfo {
  id: ConnectorId; kind: ConnectorId; name: string; signal: TelemetrySignal; signals?: TelemetrySignal[];
  configured: boolean;
  endpoint?: string; auth?: string; service_label?: string; tenant?: string | null; templates?: QueryTemplate[];
  limits?: { timeout_seconds: number; max_window_hours: number; max_log_lines_per_query: number;
    max_series_per_query: number; max_response_kib: number };
  problem?: string | null; hint?: string;
  // v0.9 Datadog
  site?: string; fixture?: boolean; env?: string | null; log_indexes?: string[];
  permissions?: Partial<Record<TelemetrySignal | "role", string>> & { actions?: string[] }; read_only_endpoints?: string[];
  limits_extra?: { max_spans_per_query?: number; max_pages_per_query?: number; max_records_per_query?: number;
    max_operations_expanded?: number; server_wait_seconds?: number; queries_in_flight?: number;
    query_timeout_seconds?: number; max_polls_per_query?: number; max_log_groups_per_query?: number;
    max_metric_pages?: number };
  // v0.10 Azure Monitor (workspace ID and auth mode only: never a credential)
  workspace_id?: string; auth_mode?: string; cloud?: string; tables?: string[];
  // v0.11 AWS CloudWatch (region, profile name, role ARN and mapping only: never a key or token)
  region?: string; partition?: string; profile?: string | null; role_arn?: string | null;
  expected_account?: string | null; log_groups?: string[];
  services?: Record<string, { log_groups: string[]; service_field: string | null; metrics: string[] }>;
}

export interface ConnectorList { connectors: ConnectorInfo[]; template_problems: string[]; planned: string[]; max_queries: number }

export type ConnectionState =
  "ok" | "partial" | "not_configured" | "auth_error" | "permission_denied" | "rate_limited" | "unavailable" | "error";
export type SignalState = "ok" | "permission_denied" | "unsupported" | "rate_limited" | "unavailable" | "error";
export interface ConnectionStatus { connector: string; status: ConnectionState; message: string; version?: string | null;
  latency_ms?: number | null; checked_at?: string;
  signals?: Partial<Record<TelemetrySignal, { status: SignalState; message: string }>> | null;
  tables?: Record<string, { status: SignalState; message: string }> | null;
  // v0.11 AWS CloudWatch: account context (no ARN or session name) and the configured log groups
  identity?: { account: string; principal: string; region: string; role?: string } | null;
  log_groups?: Record<string, { status: SignalState; message: string }> | null }

export interface DiscoveredServices {
  connector: string; services: string[]; error: { kind: string; message: string } | null; notes?: string[];
}

export interface QueryProvenance {
  id: string; connector: ConnectorId; connector_name: string; endpoint: string; template: string; template_label: string;
  service: string; query: string; start: string; end: string; step_seconds: number | null; limit: number | null;
  status: "ok" | "empty" | "error"; error: { kind: string; message: string } | null; returned: number; rejected: number;
  redactions: number; truncated: boolean; series: number | null; unit: string; fetched_at: string; duration_ms: number;
  issues: string[]; signal?: TelemetrySignal | null; site?: string | null; link?: string | null; pages?: number | null;
  workspace?: string | null; tables?: string[] | null;
  /** v0.11 AWS CloudWatch: region, account, log groups, Logs Insights query ID/status/polls/statistics or metric
   * definitions; never a credential. */
  aws?: {
    region?: string; account?: string; log_groups?: string[]; query_id?: string; query_status?: string;
    polls?: number; statistics?: Record<string, number>; stopped?: boolean; stop_error?: string; partial?: boolean;
    not_queried?: boolean; period_seconds?: number; status_codes?: Record<string, string>;
    metrics?: { namespace: string; metric_name: string; stat: string; unit: string; dimensions: Record<string, string> }[];
  } | null;
}

/** v0.9: metric points exactly as returned (never resampled); empty `points` when they cannot be charted. */
export interface ChartSeries {
  service: string; metric: string; unit: string; query: string; step_seconds: number | null; count: number;
  points: [string, number][]; omitted: string | null;
}

export interface ConnectedRequest {
  sources: { connector: ConnectorId; templates: string[] }[]; service: string; affected_services: string[];
  start: string; end: string; incident_time: string | null;
}

export interface ConnectedIncidentRequest extends ConnectedRequest {
  title: string; description: string; severity: string; incident_time: string;
}

export interface ConnectedPreview {
  usable: boolean; summary: UploadSummary; queries: QueryProvenance[];
  collected: Record<"log" | "metric", string[]> & { span?: string[] };
  warnings: string[]; samples: Record<SignalType, NormalizedRecord[]>; series?: ChartSeries[];
}

export interface Hypothesis {
  rank: number; title: string; category: string; description: string; confidence: number;
  supporting_evidence_ids: string[]; contradicting_evidence_ids: string[];
  evidence_warnings?: string[]; // v0.9: deterministic evidence-state check (e.g. "no change" without change history)
}

export interface ProposedAction {
  action_id: string; action_type: string; parameters: Record<string, string>; params_hash: string;
  rationale: string; risk: string;
}

export interface InvestigationResult {
  classification?: { category: string; confidence: number; rationale: string; source: string };
  plan?: { capabilities: string[]; notes: string[] };
  rca?: {
    summary: string; hypotheses?: Hypothesis[]; evidence_gaps?: string[]; followups?: string[];
    citation_violations?: string[]; remediation?: Record<string, string | null>; round?: number;
    evidence_warnings?: string[]; // v0.9/v0.10: deterministic notes on the summary's wording (claims.py)
    impact?: { state: string; reasons?: string[] };
  };
  proposed_action?: ProposedAction | null;
  approval?: { decision: string; decided_by: string; comment?: string; decided_at: string } | null;
  remediation?: { status: string; message: string } | null;
  verification?: { recovered: boolean; notes: string; observed_before?: number; observed_after?: number } | null;
  rejected_proposals?: { proposal: Record<string, unknown>; reason: string; category?: string | null }[];
  remediation_plan?: (ProposedAction & { step: number; role: string; added_by?: string })[];
  suggested_remediation?: { step: number; action_type: string; parameters: Record<string, string>; rationale: string;
                            risk: string; role: string; limitations?: string[] }[];
  executions?: { step: number; status: string; message: string; action_type: string }[];
  outcome?: { code: string; summary: string; escalate: boolean; escalate_to?: string | null; reason: string;
              actions_executed: number; steps_planned: number; read_only?: boolean; suggested_steps?: number } | null;
  window?: Record<string, string>;
  errors?: { node: string; error_class: string; message: string }[];
}

export interface Investigation {
  id: string; incident_id: string; status: InvestigationStatus; current_step: string | null; model: string;
  started_at: string | null; completed_at: string | null; error: string | null; error_class: string | null;
  created_at: string; updated_at: string; result?: InvestigationResult | null; executing_in_process?: boolean;
}

export interface WorkflowEvent {
  id: number; event_type: string; node: string | null; created_at: string;
  payload: {
    tool_calls?: { id: string; tool: string; status: string; latency_ms: number }[];
    llm_calls?: { purpose: string; model: string; latency_ms: number; prompt_tokens?: number; completion_tokens?: number }[];
    evidence_ids?: string[];
    observations?: { agent: string; finding: string; service?: string | null }[];
    errors?: { message: string; error_class: string }[];
    active_task?: { capability: string; service: string | null; reason: string } | null;
    queued?: { capability: string; service: string | null; reason: string }[] | null;
    [k: string]: unknown;
  };
}

export interface ToolCall {
  id: string; tool: string; server: string; agent: string; arguments: Record<string, unknown>; status: string;
  latency_ms: number; result_summary: string | null; error: string | null; started_at: string;
}

export interface Citation { document_id: string; chunk_id: string; source_uri: string; title: string; heading_path: string }

export interface Evidence {
  evidence_id: string; kind: string; source_tool: string; collected_by: string; service: string | null;
  summary: string; data: Record<string, unknown>; citation: Citation | null; relevance: number; observed_at: string | null;
}

export interface Authorization {
  decision: "approve" | "reject" | "expired"; decided_by: string; decided_at: string;
}

export interface ActionRequest {
  authorization?: Authorization | null;
  decision_history?: Authorization | null;
  id: string; investigation_id: string; incident_id: string; action_type: string; parameters: Record<string, string>;
  params_hash: string; rationale: string; risk: string; status: string; requested_at: string;
  decided_at: string | null; decided_by: string | null; decision_comment: string | null; executed_at: string | null;
  execution_result: Record<string, unknown> | null; verification: { recovered: boolean; notes: string } | null;
}

export interface RetrievedChunk {
  chunk_id: string; document_id: string; document_version: number; source_uri: string; title: string; doc_type: string;
  heading_path: string; snippet: string; score: number; vector_rank: number | null; keyword_rank: number | null;
}

export interface SearchResponse { query_id: string; query: string; mode: string; results: RetrievedChunk[]; latency_ms: number }

export interface KbDocument {
  id: string; source_uri: string; title: string; doc_type: string; services: string[]; version: number;
  status: string; duplicate_of: string | null; chunk_count: number; updated_at: string;
}

export interface InferenceConfig {
  provider: string; llm_model: string; think: boolean; temperature: number; num_ctx: number; num_predict: number;
  embedding_model: string; embedding_dimensions: number;
}

export interface Overview {
  incident_sources?: Record<string, number>;
  incidents: Record<string, number>; investigations: Record<string, number>; actions: Record<string, number>;
  knowledge: { documents: number; chunks: number };
  runtime: { llm_model: string; embedding_model: string; mcp_read_tools: string[]; mcp_action_tools: string[];
             inference?: InferenceConfig;
             max_concurrent_investigations: number; agent_budgets: Record<string, number> };
}

export interface DependencyHealth {
  checks: Record<string, { ok: boolean; [k: string]: unknown }>;
  config: Record<string, unknown>;
}
