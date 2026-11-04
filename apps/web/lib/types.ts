// Response shapes of the OpsPilot API (see docs/architecture/API_CONTRACTS.md).

export type IncidentStatus = "open" | "investigating" | "awaiting_approval" | "mitigated" | "resolved";
export type InvestigationStatus =
  | "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled" | "interrupted";

export interface Incident {
  id: string; reference: string; title: string; description: string; severity: string;
  status: IncidentStatus; service: string; environment_id: string; detected_at: string; created_at: string;
}

export interface Hypothesis {
  rank: number; title: string; category: string; description: string; confidence: number;
  supporting_evidence_ids: string[]; contradicting_evidence_ids: string[];
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
  };
  proposed_action?: ProposedAction | null;
  approval?: { decision: string; decided_by: string; comment?: string; decided_at: string } | null;
  remediation?: { status: string; message: string } | null;
  verification?: { recovered: boolean; notes: string; observed_before?: number; observed_after?: number } | null;
  rejected_proposals?: { proposal: Record<string, unknown>; reason: string; category?: string | null }[];
  remediation_plan?: (ProposedAction & { step: number; role: string; added_by?: string })[];
  executions?: { step: number; status: string; message: string; action_type: string }[];
  outcome?: { code: string; summary: string; escalate: boolean; escalate_to?: string | null; reason: string;
              actions_executed: number; steps_planned: number } | null;
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

export interface ActionRequest {
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

export interface Overview {
  incidents: Record<string, number>; investigations: Record<string, number>; actions: Record<string, number>;
  knowledge: { documents: number; chunks: number };
  runtime: { llm_model: string; embedding_model: string; mcp_read_tools: string[]; mcp_action_tools: string[];
             max_concurrent_investigations: number; agent_budgets: Record<string, number> };
}

export interface DependencyHealth {
  checks: Record<string, { ok: boolean; [k: string]: unknown }>;
  config: Record<string, unknown>;
}
