"use client";

import {
  Background,
  Controls,
  Edge,
  Handle,
  MiniMap,
  Node,
  NodeProps,
  Panel,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { Badge, Button, Card, PageHeader } from "@/components/ui";

type DiagramKey = "system" | "workflow" | "rag" | "sources";

interface ComponentDetail {
  id: string;
  name: string;
  category: string;
  role: string;
  sourcePath?: string;
  inputs: string[];
  outputs: string[];
  safetyBoundary: string;
  errorPathways: string;
  technicalSpecs?: string[];
  implementationStatus?: "implemented" | "requires_adapter" | "planned";
}

// ---------------------------------------------------------------------------
// Custom Flow Node Component
// ---------------------------------------------------------------------------
export type NodeTone =
  | "neutral"
  | "info"
  | "warn"
  | "danger"
  | "success"
  | "purple"
  | "cyan"
  | "accent";

export interface CustomNodeData extends Record<string, unknown> {
  label: string;
  category: string;
  badge?: string;
  tone?: NodeTone;
  tech?: string;
  detailId: string;
  status?: "implemented" | "requires_adapter" | "planned";
}

export type CustomNodeType = Node<CustomNodeData, "custom">;

function CustomNode({ data, selected }: NodeProps<CustomNodeType>) {
  const tone = data.tone ?? "neutral";
  const borderTone =
    tone === "accent" || tone === "info"
      ? "border-accent group-hover:border-accent"
      : tone === "success"
      ? "border-success group-hover:border-success"
      : tone === "warn"
      ? "border-warn group-hover:border-warn"
      : tone === "danger"
      ? "border-danger group-hover:border-danger"
      : tone === "purple"
      ? "border-purple group-hover:border-purple"
      : tone === "cyan"
      ? "border-cyan-500 group-hover:border-cyan-400"
      : "border-border group-hover:border-border-strong";

  const glowTone = selected
    ? "ring-2 ring-accent ring-offset-2 ring-offset-bg shadow-lg"
    : "hover:shadow-md";

  return (
    <div
      className={`group relative min-w-[210px] max-w-[270px] rounded-xl border bg-panel p-3 text-left transition-all ${borderTone} ${glowTone}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-border-strong !size-2" />
      <Handle type="target" position={Position.Left} className="!bg-border-strong !size-2" />

      <div className="flex items-center justify-between gap-1.5 border-b border-border/60 pb-1.5">
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
          {data.category}
        </span>
        {data.status ? (
          <span
            className={`rounded px-1.5 py-0.2 font-mono text-[9px] font-semibold ${
              data.status === "implemented"
                ? "bg-success-soft text-success border border-success/30"
                : data.status === "requires_adapter"
                ? "bg-info-soft text-info border border-info/30"
                : "bg-warn-soft text-warn border border-warn/30"
            }`}
          >
            {data.status === "implemented"
              ? "Implemented"
              : data.status === "requires_adapter"
              ? "Adapter Seam"
              : "Planned"}
          </span>
        ) : data.badge ? (
          <span className="rounded bg-panel-2 px-1.5 py-0.2 font-mono text-[9px] text-text-muted">
            {data.badge}
          </span>
        ) : null}
      </div>

      <div className="mt-1.5">
        <h4 className="text-xs font-bold text-text leading-snug">{data.label}</h4>
        {data.tech && (
          <p className="mt-1 font-mono text-[10px] text-muted truncate">{data.tech}</p>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-accent !size-2" />
      <Handle type="source" position={Position.Right} className="!bg-accent !size-2" />
    </div>
  );
}

const nodeTypes = {
  custom: CustomNode,
};

// ---------------------------------------------------------------------------
// Architecture Component Details Database
// ---------------------------------------------------------------------------
const COMPONENT_DETAILS: Record<string, ComponentDetail> = {
  // System Architecture
  "browser-ui": {
    id: "browser-ui",
    name: "Operator UI (Next.js 16)",
    category: "Presentation Layer",
    role: "Single-pane-of-glass operations console for human SRE operators. Renders incident summaries, live investigation progress, root-cause hypotheses, and cryptographic remediation approval prompts.",
    sourcePath: "apps/web",
    inputs: ["Operator credentials (passphrase)", "Approval/Rejection decisions", "Scenario simulation triggers"],
    outputs: ["Authenticated browser session", "CSRF-protected mutation requests"],
    safetyBoundary: "Runs in local browser. Operator token is never delivered to client code; stored securely in server-side HTTP-only session.",
    errorPathways: "Unauthenticated requests redirected to /login with next parameter. Network faults surface retryable alerts.",
    technicalSpecs: ["Next.js 16 (Turbopack, Partial Prerendering)", "React 19", "@tanstack/react-query 5", "Tailwind CSS 4"],
    implementationStatus: "implemented",
  },
  "bff-proxy": {
    id: "bff-proxy",
    name: "Same-Origin BFF Proxy",
    category: "Security Gateway",
    role: "Server-side proxy (/api/ops/*) mediating all communication between browser and FastAPI backend. Attaches the signed operator authorization token server-side and enforces origin/CSRF validation.",
    sourcePath: "apps/web/app/api/ops/[...path]/route.ts",
    inputs: ["Client session cookie", "x-opspilot-csrf header on mutations", "Incoming REST requests"],
    outputs: ["Authenticated upstream requests to FastAPI on 127.0.0.1:8000 with Authorization: Bearer <token>"],
    safetyBoundary: "Origin checking prevents CSRF attacks. Redacts sensitive parameters from responses. Eliminates token leakage to browser.",
    errorPathways: "Missing or invalid CSRF returns 403 Forbidden. Expired session returns 401 and prompts re-auth.",
    technicalSpecs: ["Node.js Edge/Server runtime", "Deterministic redaction engine", "Signed session cookies"],
    implementationStatus: "implemented",
  },
  "fastapi-api": {
    id: "fastapi-api",
    name: "FastAPI REST API & Runner",
    category: "Core Application Service",
    role: "Central HTTP API and bounded workflow coordinator. Manages incident lifecycles, schedules LangGraph background executions, checks concurrency limits, and issues approval tokens.",
    sourcePath: "apps/api/opspilot_api",
    inputs: ["Incident creation & simulation requests", "Approval decisions (approve/reject)", "Investigation inspection calls"],
    outputs: ["REST DTOs (Incidents, Investigations, Approvals, Knowledge)", "Investigation thread creation"],
    safetyBoundary: "Strict semaphore-guarded concurrency (default 1 concurrent investigation). Bounded timeouts on all tool invocations.",
    errorPathways: "Runner crashes trigger startup lease reconciliation. Dead workflows can be resumed cleanly from last checkpoint.",
    technicalSpecs: ["FastAPI async", "Pydantic v2 domain schemas", "SQLAlchemy asyncpg session pool"],
    implementationStatus: "implemented",
  },
  "langgraph-engine": {
    id: "langgraph-engine",
    name: "LangGraph StateGraph",
    category: "Agent Orchestration",
    role: "Stateful agent execution graph compiled with AsyncPostgresSaver checkpointer. Orchestrates supervisor planning, evidence gathering nodes, RCA generation, safety gating, approval interrupts, and verification.",
    sourcePath: "packages/agents/opspilot_agents/graph.py",
    inputs: ["Incident snapshot", "Analysis window", "Resumed approval decision"],
    outputs: ["Durable checkpoint state", "Ranked hypotheses", "Remediation plan", "Outcome verdict"],
    safetyBoundary: "Strict MsgPack deserialization. Thread state checkpointed at every super-step. Interrupt on await_approval pauses execution with deterministic parameter hash.",
    errorPathways: "Transient tool errors retried up to 2 times via LangGraph RetryPolicy. Model output failures fall back safely to evidence gaps.",
    technicalSpecs: ["LangGraph StateGraph", "Strict typing TypedDict", "PostgreSQL checkpointer"],
    implementationStatus: "implemented",
  },
  "ollama-llm": {
    id: "ollama-llm",
    name: "Ollama Local Inference",
    category: "Inference Engine",
    role: "Local Metal GPU inference runtime serving Qwen3 8B (structured reasoning & planning) and Qwen3-Embedding 0.6B (1024-dim vector generation). Air-gapped with no cloud dependencies.",
    sourcePath: "packages/shared/opspilot_shared/llm",
    inputs: ["System prompts with structured Pydantic schemas", "Unembedded text documents and search queries"],
    outputs: ["Valid JSON structured outputs", "1024-dimensional normalized float vectors"],
    safetyBoundary: "100% local localhost-only (127.0.0.1). Zero outbound network traffic. Prompt injection attacks in logs are captured as inert evidence strings and ignored.",
    errorPathways: "Inference timeouts (180s) or invalid schemas trigger bounded retries before failing closed to evidence gaps.",
    technicalSpecs: ["Ollama 0.40+", "qwen3:8b (4-bit quantized)", "qwen3-embedding:0.6b (1024 dims)"],
    implementationStatus: "implemented",
  },
  "mcp-read-server": {
    id: "mcp-read-server",
    name: "MCP Read Server",
    category: "Model Context Protocol",
    role: "Child process connected via stdio transport providing read-only inspection tools: list_service_metrics, query_metrics, search_logs, get_service_dependencies, get_datastore_status, inspect_queue, search_runbooks.",
    sourcePath: "packages/mcp/opspilot_mcp/read_server.py",
    inputs: ["Typed tool invocation requests with bounds"],
    outputs: ["JSON tool results: metric series, log clusters, health reads"],
    safetyBoundary: "Read-only database role (opspilot_mcp_read). Free-form SQL, shell commands, or arbitrary file access strictly rejected.",
    errorPathways: "Transport disconnects handled by SupervisedMcpGateway with exponential backoff and bounded reconnection.",
    technicalSpecs: ["Model Context Protocol stdio", "Read-only DB connection", "Timeout per call: 20s"],
    implementationStatus: "implemented",
  },
  "mcp-action-server": {
    id: "mcp-action-server",
    name: "MCP Action Server",
    category: "State-Changing Execution",
    role: "Privileged child process over stdio executing sandbox remediations: rollback_deployment, scale_connection_pool, pause_consumer, quarantine_messages, resume_consumer.",
    sourcePath: "packages/mcp/opspilot_mcp/actions_server.py",
    inputs: ["Action type", "Parameters", "Cryptographic approval token", "Parameter hash"],
    outputs: ["Execution receipt", "Pre/post telemetry telemetry changes"],
    safetyBoundary: "Independent verification: re-reads approval token and parameters from DB before executing. Atomic claim prevents double-execution. Confined to synthetic sim schema.",
    errorPathways: "Unapproved, modified, or expired tokens immediately rejected with PermissionDenied.",
    technicalSpecs: ["Model Context Protocol stdio", "Database role opspilot_mcp_actions", "Idempotent action IDs"],
    implementationStatus: "implemented",
  },
  "postgresql-pgvector": {
    id: "postgresql-pgvector",
    name: "PostgreSQL 17 + pgvector",
    category: "Persistence & Vector Store",
    role: "Primary persistent store hosting 3 distinct logical schemas: ops (incidents, investigations, actions, audit logs), kb (knowledge documents, chunks, HNSW vector indexes), and sim (synthetic infrastructure tables).",
    sourcePath: "infra/docker-compose.yml",
    inputs: ["SQL queries", "HNSW vector cosine similarity searches", "Full-text tsvector queries"],
    outputs: ["Persisted entities", "Fused search candidate chunks"],
    safetyBoundary: "Role-based separation: opspilot_app (owner), opspilot_mcp_read (SELECT only), opspilot_mcp_actions (scoped sim write).",
    errorPathways: "Database transactions maintain consistency across chunks and document versions. Deferred composite FK prevents revision drift.",
    technicalSpecs: ["PostgreSQL 17", "pgvector 0.8.7", "HNSW cosine indexing", "GIN tsvector indexing"],
    implementationStatus: "implemented",
  },
  "synthetic-simulator": {
    id: "synthetic-simulator",
    name: "Synthetic Incident Simulator",
    category: "Simulation Environment",
    role: "Deterministic fault injection engine generating byte-for-byte reproducible operational failures across 6 scenarios (INC-001..003, NEG-001..003) using fixed seed 1001 and anchor timestamp.",
    sourcePath: "services/simulator/opspilot_simulator",
    inputs: ["Scenario key (e.g. INC-001)", "Random seed (default 1001)"],
    outputs: ["Seeded database metrics, dependency graphs, error logs, and queue messages in sim schema"],
    safetyBoundary: "Isolated strictly in sim schema. Never connects to or mutates real external clouds or live infrastructure.",
    errorPathways: "Unknown scenario key raises KeyError; deterministic generation guarantees 100% reproducible tests.",
    technicalSpecs: ["Python 3.12", "Seeded pseudo-random generators", "Simulated Redis/Kafka/Postgres state"],
    implementationStatus: "implemented",
  },
  "safety-boundary": {
    id: "safety-boundary",
    name: "Deterministic Safety Gates",
    category: "Safety & Human-in-the-Loop",
    role: "Non-LLM deterministic rules engine evaluating every proposed remediation step before human approval. Checks impact, evidence grounding, correlation threshold, ambiguity margin, causal consistency, and capacity.",
    sourcePath: "packages/agents/opspilot_agents/remediation.py",
    inputs: ["Raw model plan", "Collected evidence", "Anomaly timeline"],
    outputs: ["Admitted plan steps", "Categorized rejected proposals (unsafe, unwarranted, ambiguous)"],
    safetyBoundary: "Blocks hallucinated actions, out-of-order execution, and unsafe capacity expansions without operator override.",
    errorPathways: "Uncertain or conflicting evidence withholds proposals and escalates to human operator.",
    technicalSpecs: ["Pure deterministic Python rules", "Tri-state impact logic", "Correlation scoring"],
    implementationStatus: "implemented",
  },

  // Workflow Nodes
  "wf-intake": {
    id: "wf-intake",
    name: "Intake Node",
    category: "Workflow Initialization",
    role: "Loads incident reference, calculates initial analysis window (onset time minus lookback), and populates initial graph state.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["Incident ID"],
    outputs: ["Incident snapshot", "Analysis window (start/end/onset)"],
    safetyBoundary: "Read-only access via get_incident.",
    errorPathways: "Missing incident halts graph with IntakeError.",
    implementationStatus: "implemented",
  },
  "wf-plan": {
    id: "wf-plan",
    name: "Supervisor Plan Node",
    category: "Autonomous Planning",
    role: "LLM supervisor node that classifies the incident category, prioritizes agent capabilities, and enforces mandatory telemetry and runbook retrieval.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["Incident description", "Initial analysis window"],
    outputs: ["Classification DTO", "Queued capability tasks"],
    safetyBoundary: "Policy-mandated rules inject telemetry and knowledge if model omits them.",
    errorPathways: "LLM timeout falls back to all-capabilities conservative execution.",
    implementationStatus: "implemented",
  },
  "wf-dispatch": {
    id: "wf-dispatch",
    name: "Dynamic Dispatcher Node",
    category: "Routing & Budgets",
    role: "Pops next task from queue and enforces execution order (telemetry → deps → changes → knowledge). Enforces budget limits.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["Queued tasks", "Budget state"],
    outputs: ["Next active capability task"],
    safetyBoundary: "De-duplicates tasks by (capability, service) preventing infinite loops.",
    errorPathways: "Exhausted tool or LLM budgets route directly to RCA with available evidence.",
    implementationStatus: "implemented",
  },
  "wf-rca": {
    id: "wf-rca",
    name: "RCA Generation Node",
    category: "Hypothesis Formulation",
    role: "Synthesizes gathered evidence, ranks root-cause hypotheses with confidence, and proposes remediation actions.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["All persisted Evidence items", "Observation notes"],
    outputs: ["Ranked hypotheses", "Remediation plan", "Follow-up recommendations"],
    safetyBoundary: "Fabricated citations discarded automatically. Confidence threshold (0.6) prevents low-confidence guesses.",
    errorPathways: "Low confidence with evidence gaps triggers followup loop up to 2 rounds.",
    implementationStatus: "implemented",
  },
  "wf-propose": {
    id: "wf-propose",
    name: "Propose & Safety Filter Node",
    category: "Deterministic Validation",
    role: "Applies the 7 deterministic safety gates to every step in the raw model remediation plan. Rejects unsafe or ungrounded steps.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["Raw model plan", "Evidence index"],
    outputs: ["Validated remediation plan", "List of rejected proposals with reasons"],
    safetyBoundary: "Hard mathematical and evidence checks; cannot be bypassed by model prompting.",
    errorPathways: "If all steps blocked or confidence is ambiguous, routes directly to Report with outcome escalated.",
    implementationStatus: "implemented",
  },
  "wf-approval": {
    id: "wf-approval",
    name: "Human Approval Interrupt Node",
    category: "Human-in-the-Loop",
    role: "Pauses LangGraph execution using interrupt(). Emits action request to API and waits for authenticated operator sign-off.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["Admitted plan step with parameter hash"],
    outputs: ["Interrupt payload to database runner"],
    safetyBoundary: "Graph execution completely suspended in PostgreSQL checkpointer until resume API call.",
    errorPathways: "Approval requests expire after 60s. Mismatched parameter hash fails closed.",
    implementationStatus: "implemented",
  },
  "wf-verify": {
    id: "wf-verify",
    name: "Recovery Verification Node",
    category: "Verification Engine",
    role: "Re-queries telemetry and health to verify that all in-scope recovery conditions are met before marking incident mitigated.",
    sourcePath: "packages/agents/opspilot_agents/nodes.py",
    inputs: ["Initial anomaly metrics", "Postcondition checks", "Service health"],
    outputs: ["Verification verdict: VERIFIED, FAILED, or INCOMPLETE"],
    safetyBoundary: "Missing, unknown, or stale telemetry is never treated as healthy. Mitigated requires affirmative proof.",
    errorPathways: "Unverified recovery results in outcome not_recovered and triggers human escalation.",
    implementationStatus: "implemented",
  },

  // RAG Pipeline Nodes
  "rag-ingest": {
    id: "rag-ingest",
    name: "Ingestion & Normalisation",
    category: "Document Processing",
    role: "Discovers Markdown and JSON runbooks, normalizes Unicode NFC, canonicalizes line breaks, and computes SHA-256 content hashes.",
    sourcePath: "packages/rag/opspilot_rag/ingest.py",
    inputs: ["Corpus runbooks and postmortems"],
    outputs: ["Parsed documents with stable UUID5 IDs"],
    safetyBoundary: "Incremental: unchanged content hashes are skipped without invoking embeddings.",
    errorPathways: "Duplicate documents detected and recorded as duplicate_of.",
    implementationStatus: "implemented",
  },
  "rag-chunking": {
    id: "rag-chunking",
    name: "Heading-Aware Chunking",
    category: "Chunking Engine",
    role: "Splits documents into coherent sections preserving heading paths (e.g. Schema migration > Rollback > Verify). Adds heading path to embedded text.",
    sourcePath: "packages/rag/opspilot_rag/chunking.py",
    inputs: ["Parsed markdown AST"],
    outputs: ["Chunks with ordinal, heading path, and content"],
    safetyBoundary: "Section coverage expansion links parent runbooks to child sections.",
    errorPathways: "Oversized sections split on paragraph boundaries with 40-word overlap.",
    implementationStatus: "implemented",
  },
  "rag-hybrid": {
    id: "rag-hybrid",
    name: "Hybrid RRF Retrieval",
    category: "Retrieval Fusion",
    role: "Executes parallel vector cosine search and GIN tsvector keyword search, fusing ranks via Reciprocal Rank Fusion (RRF k=60).",
    sourcePath: "packages/rag/opspilot_rag/retrieval.py",
    inputs: ["Investigation search query", "Service metadata filters"],
    outputs: ["Ranked candidate chunks with fusion scores"],
    safetyBoundary: "Lifecycle filtering partitions current vs superseded docs before ranking.",
    errorPathways: "If Ollama embedding fails, gracefully degrades to keyword-only search with warning.",
    implementationStatus: "implemented",
  },
  "rag-lifecycle": {
    id: "rag-lifecycle",
    name: "Lifecycle Partitioning",
    category: "Knowledge Integrity",
    role: "Filters out superseded, unreviewed, or withdrawn runbooks during normal investigation search (exclude_obsolete=True).",
    sourcePath: "packages/rag/opspilot_rag/lifecycle.py",
    inputs: ["Fused candidate chunks"],
    outputs: ["Tier-0 validated operational runbooks"],
    safetyBoundary: "Prevents model from acting on outdated runbooks (e.g. obsolete INC-002 pool size).",
    errorPathways: "Obsolete guidance that reaches agent is flagged as withheld_obsolete.",
    implementationStatus: "implemented",
  },

  // Diagram D: Source-Agnostic Evidence Ingestion & Extensibility
  "src-ext-adapters": {
    id: "src-ext-adapters",
    name: "Pluggable Observability Adapters",
    category: "Adapter Seam",
    role: "Extensible protocol translation layer connecting third-party metrics (Prometheus, Datadog, CloudWatch), logs (Loki, Elasticsearch), and traces (Tempo, Jaeger) into the standard ToolGateway interface.",
    sourcePath: "packages/mcp/opspilot_mcp/adapters/",
    inputs: ["PromQL queries", "LogQL streams", "KQL exceptions", "OTLP trace spans"],
    outputs: ["Standardized MetricSeries", "Error signature clusters", "Call graph edges"],
    safetyBoundary: "Read-only access enforced at adapter network boundaries. No remote state-changing tools permitted.",
    errorPathways: "Network timeouts fall back to recorded evidence gaps without crashing investigation.",
    technicalSpecs: ["ToolGateway protocol", "Asynchronous HTTP/gRPC clients", "Bounded rate limits"],
    implementationStatus: "requires_adapter",
  },
  "norm-evidence": {
    id: "norm-evidence",
    name: "Standardized Evidence Repository",
    category: "Evidence Core",
    role: "Immutable PostgreSQL persistence layer (ops.evidence) storing normalized telemetry, change correlations, dependency states, and knowledge citations with relevance scores.",
    sourcePath: "packages/shared/opspilot_shared/domain/evidence.py",
    inputs: ["Evidence DTOs from tool invocations"],
    outputs: ["Persisted evidence indexed by investigation ID and kind"],
    safetyBoundary: "Immutable audit log. Citations validated against physical chunk IDs; fabricated IDs discarded.",
    errorPathways: "Database transaction isolation prevents partial evidence writes.",
    technicalSpecs: ["SQLAlchemy AsyncPG", "JSONB payload storage", "UUID primary keys"],
    implementationStatus: "implemented",
  },
  "norm-analytics": {
    id: "norm-analytics",
    name: "Deterministic Analytics Engine",
    category: "Evidence Core",
    role: "Non-LLM deterministic analysis: computes bidirectional shift detection, unit-aware baseline comparisons, log error clustering, and temporal deployment correlation scores.",
    sourcePath: "packages/agents/opspilot_agents/analysis.py",
    inputs: ["Pre/post-onset metric series", "Git commit history", "Application logs"],
    outputs: ["Onset timestamp", "Correlation scores (0.00..1.00)", "Identified anomaly directions"],
    safetyBoundary: "Pure Python mathematical algorithms; avoids LLM hallucinations in numeric analysis.",
    errorPathways: "Insufficient baseline data marks metric signal as 'unknown' rather than healthy.",
    technicalSpecs: ["NumPy statistical functions", "Drain log clustering algorithm", "UTC temporal math"],
    implementationStatus: "implemented",
  },
};

// ---------------------------------------------------------------------------
// Diagram A: System Architecture Nodes & Edges
// ---------------------------------------------------------------------------
const SYSTEM_NODES: CustomNodeType[] = [
  {
    id: "browser-ui",
    type: "custom",
    position: { x: 50, y: 150 },
    data: {
      label: "Next.js Operator Console",
      category: "Operator UI",
      badge: "Port 3000",
      tone: "cyan",
      tech: "Next.js 16 · React 19 · SSE/Poll",
      detailId: "browser-ui",
    },
  },
  {
    id: "bff-proxy",
    type: "custom",
    position: { x: 340, y: 150 },
    data: {
      label: "Same-Origin BFF Proxy",
      category: "Security Gateway",
      badge: "/api/ops/*",
      tone: "info",
      tech: "CSRF Guard · Session Token Inject",
      detailId: "bff-proxy",
    },
  },
  {
    id: "fastapi-api",
    type: "custom",
    position: { x: 640, y: 150 },
    data: {
      label: "FastAPI REST Runner",
      category: "Application Service",
      badge: "Port 8000",
      tone: "purple",
      tech: "FastAPI Async · Bounded Semaphore",
      detailId: "fastapi-api",
    },
  },
  {
    id: "langgraph-engine",
    type: "custom",
    position: { x: 940, y: 150 },
    data: {
      label: "LangGraph Orchestrator",
      category: "Agent Graph",
      badge: "StateGraph",
      tone: "purple",
      tech: "AsyncPostgresSaver · Checkpointer",
      detailId: "langgraph-engine",
    },
  },
  {
    id: "ollama-llm",
    type: "custom",
    position: { x: 1240, y: 80 },
    data: {
      label: "Ollama Local Inference",
      category: "Model Engine",
      badge: "Metal GPU",
      tone: "accent",
      tech: "qwen3:8b · qwen3-embedding:0.6b",
      detailId: "ollama-llm",
    },
  },
  {
    id: "mcp-read-server",
    type: "custom",
    position: { x: 940, y: 340 },
    data: {
      label: "MCP Read Server",
      category: "Telemetry & Tools",
      badge: "stdio child",
      tone: "info",
      tech: "Metrics · Logs · Queue · Runbooks",
      detailId: "mcp-read-server",
    },
  },
  {
    id: "safety-boundary",
    type: "custom",
    position: { x: 940, y: 490 },
    data: {
      label: "Deterministic Safety Gates",
      category: "Safety Boundary",
      badge: "HITL Policy",
      tone: "warn",
      tech: "7 Invariant Gates · 60s Expiring Token",
      detailId: "safety-boundary",
    },
  },
  {
    id: "mcp-action-server",
    type: "custom",
    position: { x: 640, y: 490 },
    data: {
      label: "MCP Actions Server",
      category: "Sandbox Remediation",
      badge: "stdio child",
      tone: "danger",
      tech: "Double Token Check · Atomic Claim",
      detailId: "mcp-action-server",
    },
  },
  {
    id: "postgresql-pgvector",
    type: "custom",
    position: { x: 640, y: 340 },
    data: {
      label: "PostgreSQL 17 + pgvector",
      category: "Persistence",
      badge: "Port 5433",
      tone: "success",
      tech: "ops · kb (HNSW) · sim schemas",
      detailId: "postgresql-pgvector",
    },
  },
  {
    id: "synthetic-simulator",
    type: "custom",
    position: { x: 340, y: 340 },
    data: {
      label: "Synthetic Fault Simulator",
      category: "Simulation",
      badge: "Seed 1001",
      tone: "neutral",
      tech: "INC-001..003 · NEG-001..003",
      detailId: "synthetic-simulator",
    },
  },
];

const SYSTEM_EDGES: Edge[] = [
  { id: "e1", source: "browser-ui", target: "bff-proxy", label: "HTTPS / Session", animated: true },
  { id: "e2", source: "bff-proxy", target: "fastapi-api", label: "Signed Bearer Token", animated: true },
  { id: "e3", source: "fastapi-api", target: "langgraph-engine", label: "Start / Resume Graph", animated: true },
  { id: "e4", source: "langgraph-engine", target: "ollama-llm", label: "Structured JSON", animated: true },
  { id: "e5", source: "langgraph-engine", target: "mcp-read-server", label: "stdio MCP Tools", animated: true },
  { id: "e6", source: "langgraph-engine", target: "safety-boundary", label: "Await Approval Interrupt", animated: true },
  { id: "e7", source: "safety-boundary", target: "mcp-action-server", label: "Signed Approval Token", animated: true },
  { id: "e8", source: "mcp-action-server", target: "postgresql-pgvector", label: "Execute in sim schema" },
  { id: "e9", source: "mcp-read-server", target: "postgresql-pgvector", label: "Read telemetry & kb" },
  { id: "e10", source: "mcp-read-server", target: "ollama-llm", label: "Query Embeddings" },
  { id: "e11", source: "fastapi-api", target: "postgresql-pgvector", label: "Checkpoints & Events" },
  { id: "e12", source: "synthetic-simulator", target: "postgresql-pgvector", label: "Seed Fault State" },
];

// ---------------------------------------------------------------------------
// Diagram B: Agent Workflow Nodes & Edges
// ---------------------------------------------------------------------------
const WORKFLOW_NODES: CustomNodeType[] = [
  {
    id: "wf-intake",
    type: "custom",
    position: { x: 50, y: 150 },
    data: {
      label: "1. Intake & Window",
      category: "Initialization",
      badge: "No LLM",
      tone: "info",
      tech: "Detect Onset · Set Time Window",
      detailId: "wf-intake",
    },
  },
  {
    id: "wf-plan",
    type: "custom",
    position: { x: 300, y: 150 },
    data: {
      label: "2. Supervisor Plan",
      category: "LLM Planner",
      badge: "1 LLM Call",
      tone: "purple",
      tech: "Classify Triage · Seed Task Queue",
      detailId: "wf-plan",
    },
  },
  {
    id: "wf-dispatch",
    type: "custom",
    position: { x: 550, y: 150 },
    data: {
      label: "3. Dynamic Dispatcher",
      category: "Task Router",
      badge: "No LLM",
      tone: "cyan",
      tech: "Order Tasks · Enforce Budgets",
      detailId: "wf-dispatch",
    },
  },
  {
    id: "wf-tools",
    type: "custom",
    position: { x: 550, y: 320 },
    data: {
      label: "4. Investigation Tools",
      category: "Evidence Loop",
      badge: "Parallel MCP",
      tone: "info",
      tech: "Telemetry · Changes · Deps · RAG",
      detailId: "mcp-read-server",
    },
  },
  {
    id: "wf-rca",
    type: "custom",
    position: { x: 800, y: 150 },
    data: {
      label: "5. Root Cause Analysis",
      category: "Hypothesis LLM",
      badge: "1 LLM / Round",
      tone: "purple",
      tech: "Rank Hypotheses · Evidence Citations",
      detailId: "wf-rca",
    },
  },
  {
    id: "wf-propose",
    type: "custom",
    position: { x: 1050, y: 150 },
    data: {
      label: "6. Propose & Safety Gates",
      category: "Deterministic Gate",
      badge: "No LLM",
      tone: "warn",
      tech: "7 Invariant Gates · Drop Unsafe Steps",
      detailId: "wf-propose",
    },
  },
  {
    id: "wf-approval",
    type: "custom",
    position: { x: 1050, y: 320 },
    data: {
      label: "7. Operator Approval",
      category: "Human Interrupt",
      badge: "LangGraph Interrupt",
      tone: "warn",
      tech: "Operator Review · Signed Token",
      detailId: "wf-approval",
    },
  },
  {
    id: "wf-execute",
    type: "custom",
    position: { x: 800, y: 320 },
    data: {
      label: "8. Sandbox Execution",
      category: "Action Server",
      badge: "Privileged MCP",
      tone: "danger",
      tech: "Atomic Claim · Idempotent Execution",
      detailId: "mcp-action-server",
    },
  },
  {
    id: "wf-verify",
    type: "custom",
    position: { x: 800, y: 470 },
    data: {
      label: "9. Recovery Verification",
      category: "Post-Conditions",
      badge: "Telemetry Re-query",
      tone: "success",
      tech: "Affirmative Proof · Metric Thresholds",
      detailId: "wf-verify",
    },
  },
  {
    id: "wf-report",
    type: "custom",
    position: { x: 1050, y: 470 },
    data: {
      label: "10. RCA Report & Escalation",
      category: "Outcome",
      badge: "Terminal State",
      tone: "success",
      tech: "Mitigated · Escalated · Blocked",
      detailId: "browser-ui",
    },
  },
];

const WORKFLOW_EDGES: Edge[] = [
  { id: "we1", source: "wf-intake", target: "wf-plan", animated: true },
  { id: "we2", source: "wf-plan", target: "wf-dispatch", animated: true },
  { id: "we3", source: "wf-dispatch", target: "wf-tools", label: "Telemetry, Deps, Changes, RAG", animated: true },
  { id: "we4", source: "wf-tools", target: "wf-dispatch", label: "Observations & New Tasks" },
  { id: "we5", source: "wf-dispatch", target: "wf-rca", label: "Queue empty or budget reached", animated: true },
  { id: "we6", source: "wf-rca", target: "wf-propose", label: "Model proposed plan", animated: true },
  { id: "we7", source: "wf-rca", target: "wf-report", label: "Empty plan / escalate" },
  { id: "we8", source: "wf-propose", target: "wf-approval", label: "Steps passed gates", animated: true },
  { id: "we9", source: "wf-propose", target: "wf-report", label: "All steps blocked" },
  { id: "we10", source: "wf-approval", target: "wf-execute", label: "Approved by human", animated: true },
  { id: "we11", source: "wf-approval", target: "wf-report", label: "Rejected / Expired" },
  { id: "we12", source: "wf-execute", target: "wf-verify", label: "Action complete", animated: true },
  { id: "we13", source: "wf-verify", target: "wf-report", label: "Verified outcome", animated: true },
];

// ---------------------------------------------------------------------------
// Diagram C: RAG Pipeline Nodes & Edges
// ---------------------------------------------------------------------------
const RAG_NODES: CustomNodeType[] = [
  {
    id: "rag-ingest",
    type: "custom",
    position: { x: 50, y: 150 },
    data: {
      label: "1. Corpus Ingestion",
      category: "Ingestion",
      badge: "Markdown/JSON",
      tone: "info",
      tech: "Discover · NFC Normalization · Hash",
      detailId: "rag-ingest",
    },
  },
  {
    id: "rag-chunking",
    type: "custom",
    position: { x: 320, y: 150 },
    data: {
      label: "2. Heading Chunking",
      category: "Chunking",
      badge: "220 words / 40 overlap",
      tone: "purple",
      tech: "Preserve Heading Hierarchy Breadcrumbs",
      detailId: "rag-chunking",
    },
  },
  {
    id: "rag-embed",
    type: "custom",
    position: { x: 590, y: 150 },
    data: {
      label: "3. Vector Embedding",
      category: "Ollama Embedding",
      badge: "1024 dims",
      tone: "accent",
      tech: "qwen3-embedding:0.6b · Batched",
      detailId: "ollama-llm",
    },
  },
  {
    id: "rag-store",
    type: "custom",
    position: { x: 860, y: 150 },
    data: {
      label: "4. PostgreSQL Storage",
      category: "Vector Index",
      badge: "pgvector 0.8.7",
      tone: "success",
      tech: "HNSW Cosine + GIN tsvector",
      detailId: "postgresql-pgvector",
    },
  },
  {
    id: "rag-query",
    type: "custom",
    position: { x: 320, y: 340 },
    data: {
      label: "5. Investigation Query",
      category: "Agent Search",
      badge: "MCP search_runbooks",
      tone: "cyan",
      tech: "Service Filter · exclude_obsolete=True",
      detailId: "rag-hybrid",
    },
  },
  {
    id: "rag-hybrid",
    type: "custom",
    position: { x: 590, y: 340 },
    data: {
      label: "6. Hybrid RRF Fusion",
      category: "Retrieval",
      badge: "RRF k=60",
      tone: "purple",
      tech: "Vector + Full-Text Rank Fusion",
      detailId: "rag-hybrid",
    },
  },
  {
    id: "rag-lifecycle",
    type: "custom",
    position: { x: 860, y: 340 },
    data: {
      label: "7. Lifecycle Partitioning",
      category: "Safety Filter",
      badge: "Current > Superseded",
      tone: "warn",
      tech: "Exclude Withdrawn/Obsolete Chunks",
      detailId: "rag-lifecycle",
    },
  },
  {
    id: "rag-citation",
    type: "custom",
    position: { x: 1120, y: 340 },
    data: {
      label: "8. Citation Snapshots",
      category: "Evidence Integrity",
      badge: "SHA-256 Verified",
      tone: "success",
      tech: "Chunk Hash · Version · Evidence Link",
      detailId: "rag-lifecycle",
    },
  },
];

const RAG_EDGES: Edge[] = [
  { id: "re1", source: "rag-ingest", target: "rag-chunking", label: "Parsed Sections", animated: true },
  { id: "re2", source: "rag-chunking", target: "rag-embed", label: "Heading + Snippet", animated: true },
  { id: "re3", source: "rag-embed", target: "rag-store", label: "Atomic Transaction", animated: true },
  { id: "re4", source: "rag-query", target: "rag-hybrid", label: "Query + Prefix", animated: true },
  { id: "re5", source: "rag-store", target: "rag-hybrid", label: "Vector & Keyword Search" },
  { id: "re6", source: "rag-hybrid", target: "rag-lifecycle", label: "Top-k Candidates", animated: true },
  { id: "re7", source: "rag-lifecycle", target: "rag-citation", label: "Section Coverage & Citations", animated: true },
];

// ---------------------------------------------------------------------------
// Diagram D: Source-Agnostic Evidence Ingestion & Extensibility Architecture
// ---------------------------------------------------------------------------
const SOURCES_NODES: CustomNodeType[] = [
  // Column 1: Ingestion Sources
  {
    id: "src-sim",
    type: "custom",
    position: { x: 40, y: 50 },
    data: {
      label: "Synthetic Simulator",
      category: "Source (Demo)",
      tone: "success",
      status: "implemented",
      tech: "Seed 1001 · 6 Scenarios",
      detailId: "synthetic-simulator",
    },
  },
  {
    id: "src-runbooks",
    type: "custom",
    position: { x: 40, y: 170 },
    data: {
      label: "Runbooks & Postmortems",
      category: "Source (Files)",
      tone: "success",
      status: "implemented",
      tech: "Markdown & JSON with frontmatter",
      detailId: "rag-ingest",
    },
  },
  {
    id: "src-file-dumps",
    type: "custom",
    position: { x: 40, y: 290 },
    data: {
      label: "Offline Telemetry Dumps",
      category: "Source (Files)",
      tone: "cyan",
      status: "requires_adapter",
      tech: "Prometheus Matrix / CSV / JSONL",
      detailId: "src-ext-adapters",
    },
  },
  {
    id: "src-prom-loki",
    type: "custom",
    position: { x: 40, y: 410 },
    data: {
      label: "Prometheus & Loki",
      category: "Source (Connected)",
      tone: "cyan",
      status: "requires_adapter",
      tech: "PromQL Range & LogQL Streams",
      detailId: "src-ext-adapters",
    },
  },
  {
    id: "src-datadog-cloud",
    type: "custom",
    position: { x: 40, y: 530 },
    data: {
      label: "Datadog / CloudWatch / Azure",
      category: "Source (Connected)",
      tone: "cyan",
      status: "requires_adapter",
      tech: "Cloud Metrics & Log Insights",
      detailId: "src-ext-adapters",
    },
  },
  {
    id: "src-tracing",
    type: "custom",
    position: { x: 40, y: 650 },
    data: {
      label: "Tempo / Jaeger / OTel",
      category: "Source (Connected)",
      tone: "cyan",
      status: "requires_adapter",
      tech: "Distributed Trace Span Waterfalls",
      detailId: "src-ext-adapters",
    },
  },
  {
    id: "src-ci-cd",
    type: "custom",
    position: { x: 40, y: 770 },
    data: {
      label: "GitHub Actions / Argo CD",
      category: "Source (Connected)",
      tone: "cyan",
      status: "requires_adapter",
      tech: "Deployments API & Git Changelog",
      detailId: "src-ext-adapters",
    },
  },
  {
    id: "src-webhooks",
    type: "custom",
    position: { x: 40, y: 890 },
    data: {
      label: "PagerDuty / Alertmanager",
      category: "Source (Alerting)",
      tone: "warn",
      status: "planned",
      tech: "Inbound HMAC Webhook Receiver",
      detailId: "src-ext-adapters",
    },
  },

  // Column 2: Extensibility Seams
  {
    id: "seam-mcp-gateway",
    type: "custom",
    position: { x: 400, y: 220 },
    data: {
      label: "MCP Read Server Protocol",
      category: "Protocol Seam",
      tone: "purple",
      status: "implemented",
      tech: "ToolGateway Port · stdio MCP",
      detailId: "mcp-read-server",
    },
  },
  {
    id: "seam-ext-adapters",
    type: "custom",
    position: { x: 400, y: 530 },
    data: {
      label: "Pluggable Tool Adapters",
      category: "Extensibility Seam",
      tone: "cyan",
      status: "requires_adapter",
      tech: "Prometheus, Loki, Datadog Clients",
      detailId: "src-ext-adapters",
    },
  },

  // Column 3: Normalization & Core Evidence
  {
    id: "norm-evidence",
    type: "custom",
    position: { x: 740, y: 350 },
    data: {
      label: "Standardized Evidence Core",
      category: "Normalization",
      tone: "success",
      status: "implemented",
      tech: "ops.evidence (Kind, Tool, Relevance)",
      detailId: "norm-evidence",
    },
  },
  {
    id: "norm-analytics",
    type: "custom",
    position: { x: 740, y: 530 },
    data: {
      label: "Deterministic Analytics",
      category: "Analysis Engine",
      tone: "success",
      status: "implemented",
      tech: "Shift Detection · Change Correlation",
      detailId: "norm-analytics",
    },
  },

  // Column 4: Agent Reasoning & Safety Gates
  {
    id: "agent-reasoning",
    type: "custom",
    position: { x: 1080, y: 350 },
    data: {
      label: "Investigation Agents",
      category: "Agent StateGraph",
      tone: "purple",
      status: "implemented",
      tech: "Telemetry, Changes, Deps, RAG, RCA",
      detailId: "langgraph-engine",
    },
  },
  {
    id: "agent-safety",
    type: "custom",
    position: { x: 1080, y: 530 },
    data: {
      label: "Deterministic Safety Gates",
      category: "HITL Gate",
      tone: "warn",
      status: "implemented",
      tech: "7 Invariant Gates · Operator Approval",
      detailId: "safety-boundary",
    },
  },
];

const SOURCES_EDGES: Edge[] = [
  // Implemented solid green edges
  { id: "se-1", source: "src-sim", target: "seam-mcp-gateway", label: "Direct SQL/stdio", animated: true },
  { id: "se-2", source: "src-runbooks", target: "seam-mcp-gateway", label: "Heading Chunks", animated: true },
  { id: "se-3", source: "seam-mcp-gateway", target: "norm-evidence", label: "Typed Tool Results", animated: true },
  { id: "se-4", source: "norm-evidence", target: "norm-analytics", label: "Pre/Post Windows", animated: true },
  { id: "se-5", source: "norm-evidence", target: "agent-reasoning", label: "Grounded Observations", animated: true },
  { id: "se-6", source: "norm-analytics", target: "agent-reasoning", label: "Shift & Correlation Scores", animated: true },
  { id: "se-7", source: "agent-reasoning", target: "agent-safety", label: "Proposed Action Plan", animated: true },

  // Extensibility dashed cyan edges
  { id: "se-8", source: "src-file-dumps", target: "seam-ext-adapters", label: "JSON/CSV Parser", style: { strokeDasharray: "5,5" } },
  { id: "se-9", source: "src-prom-loki", target: "seam-ext-adapters", label: "PromQL/LogQL", style: { strokeDasharray: "5,5" } },
  { id: "se-10", source: "src-datadog-cloud", target: "seam-ext-adapters", label: "REST / SDK", style: { strokeDasharray: "5,5" } },
  { id: "se-11", source: "src-tracing", target: "seam-ext-adapters", label: "OTLP Trace Spans", style: { strokeDasharray: "5,5" } },
  { id: "se-12", source: "src-ci-cd", target: "seam-ext-adapters", label: "GitHub Releases API", style: { strokeDasharray: "5,5" } },
  { id: "se-13", source: "seam-ext-adapters", target: "norm-evidence", label: "Mapped Evidence", style: { strokeDasharray: "5,5" } },

  // Planned dotted amber edges
  { id: "se-14", source: "src-webhooks", target: "seam-ext-adapters", label: "Inbound HMAC Webhooks", style: { strokeDasharray: "2,2" } },
];

// ---------------------------------------------------------------------------
// Main Interactive Architecture Explorer Page
// ---------------------------------------------------------------------------
export default function ArchitectureExplorerPage() {
  const [activeDiagram, setActiveDiagram] = useState<DiagramKey>("system");
  const [selectedDetail, setSelectedDetail] = useState<ComponentDetail | null>(
    COMPONENT_DETAILS["fastapi-api"]
  );
  const [animatedFlow, setAnimatedFlow] = useState(true);
  const [accessibleMode, setAccessibleMode] = useState(false);

  const initialNodes = useMemo(() => {
    if (activeDiagram === "system") return SYSTEM_NODES;
    if (activeDiagram === "workflow") return WORKFLOW_NODES;
    if (activeDiagram === "rag") return RAG_NODES;
    return SOURCES_NODES;
  }, [activeDiagram]);

  const initialEdges = useMemo(() => {
    const raw =
      activeDiagram === "system"
        ? SYSTEM_EDGES
        : activeDiagram === "workflow"
        ? WORKFLOW_EDGES
        : activeDiagram === "rag"
        ? RAG_EDGES
        : SOURCES_EDGES;
    return raw.map((e) => ({
      ...e,
      animated: animatedFlow ? (e.animated ?? true) : false,
      style: {
        stroke: "var(--border-strong)",
        strokeWidth: 2,
        ...e.style,
      },
    }));
  }, [activeDiagram, animatedFlow]);

  const [nodes, setNodes, onNodesChange] = useNodesState<CustomNodeType>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Switch diagram datasets cleanly
  const handleDiagramSwitch = useCallback(
    (key: DiagramKey) => {
      setActiveDiagram(key);
      const nextNodes =
        key === "system"
          ? SYSTEM_NODES
          : key === "workflow"
          ? WORKFLOW_NODES
          : key === "rag"
          ? RAG_NODES
          : SOURCES_NODES;
      const nextEdges =
        key === "system"
          ? SYSTEM_EDGES
          : key === "workflow"
          ? WORKFLOW_EDGES
          : key === "rag"
          ? RAG_EDGES
          : SOURCES_EDGES;

      setNodes(nextNodes);
      setEdges(
        nextEdges.map((e) => ({
          ...e,
          animated: animatedFlow ? (e.animated ?? true) : false,
          style: {
            stroke: "var(--border-strong)",
            strokeWidth: 2,
            ...e.style,
          },
        }))
      );

      // Select default component detail for diagram
      if (key === "system") setSelectedDetail(COMPONENT_DETAILS["fastapi-api"]);
      if (key === "workflow") setSelectedDetail(COMPONENT_DETAILS["wf-rca"]);
      if (key === "rag") setSelectedDetail(COMPONENT_DETAILS["rag-hybrid"]);
      if (key === "sources") setSelectedDetail(COMPONENT_DETAILS["src-ext-adapters"]);
    },
    [animatedFlow, setNodes, setEdges]
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const data = node.data as unknown as CustomNodeData;
      if (data?.detailId && COMPONENT_DETAILS[data.detailId]) {
        setSelectedDetail(COMPONENT_DETAILS[data.detailId]);
      }
    },
    []
  );

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <PageHeader
        title="Interactive Architecture &amp; Workflow Explorer"
        subtitle="Explore the real components, execution stategraph, RAG retrieval pipeline, and source-agnostic evidence ingestion architecture."
        actions={
          <div className="flex items-center gap-2">
            <Link href="/integrations">
              <Button variant="secondary" size="md">
                Data Sources &amp; Integrations →
              </Button>
            </Link>
            <button
              onClick={() => setAccessibleMode(!accessibleMode)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                accessibleMode
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border bg-panel text-muted hover:text-text"
              }`}
              aria-label="Toggle accessible structured text hierarchy"
            >
              {accessibleMode ? "Visual Canvas View" : "Accessible Text Tree"}
            </button>
          </div>
        }
      />

      {/* Diagram Selection Controls & Mode Badges */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-border bg-panel p-3">
        <div
          role="tablist"
          aria-label="Architecture Diagrams"
          className="flex flex-wrap gap-1.5"
        >
          <button
            role="tab"
            aria-selected={activeDiagram === "system"}
            onClick={() => handleDiagramSwitch("system")}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
              activeDiagram === "system"
                ? "bg-accent text-white shadow-xs"
                : "bg-panel-2 text-muted hover:text-text"
            }`}
          >
            Diagram A: System Architecture
          </button>
          <button
            role="tab"
            aria-selected={activeDiagram === "workflow"}
            onClick={() => handleDiagramSwitch("workflow")}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
              activeDiagram === "workflow"
                ? "bg-accent text-white shadow-xs"
                : "bg-panel-2 text-muted hover:text-text"
            }`}
          >
            Diagram B: Agent Workflow Graph
          </button>
          <button
            role="tab"
            aria-selected={activeDiagram === "rag"}
            onClick={() => handleDiagramSwitch("rag")}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
              activeDiagram === "rag"
                ? "bg-accent text-white shadow-xs"
                : "bg-panel-2 text-muted hover:text-text"
            }`}
          >
            Diagram C: RAG Pipeline
          </button>
          <button
            role="tab"
            aria-selected={activeDiagram === "sources"}
            onClick={() => handleDiagramSwitch("sources")}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
              activeDiagram === "sources"
                ? "bg-accent text-white shadow-xs"
                : "bg-panel-2 text-muted hover:text-text"
            }`}
          >
            Diagram D: Evidence Ingestion &amp; Extensibility
          </button>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted cursor-pointer select-none">
            <input
              type="checkbox"
              checked={animatedFlow}
              onChange={(e) => setAnimatedFlow(e.target.checked)}
              className="rounded border-border accent-accent"
            />
            <span>Animate Flow Edges</span>
          </label>
        </div>
      </div>

      {/* Main Content: Interactive Canvas or Accessible Structured View */}
      {!accessibleMode ? (
        <div className="grid gap-6 lg:grid-cols-12">
          {/* React Flow Canvas (8 columns) */}
          <div className="relative h-[680px] w-full rounded-2xl border border-border bg-bg overflow-hidden shadow-inner lg:col-span-8">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={onNodeClick}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.15 }}
              minZoom={0.35}
              maxZoom={1.8}
            >
              <Background color="var(--border)" gap={24} size={1} />
              <Controls showInteractive={false} />
              <MiniMap
                nodeColor={(node) => {
                  const data = node.data as unknown as CustomNodeData;
                  if (data?.tone === "accent") return "var(--accent)";
                  if (data?.tone === "danger") return "var(--danger)";
                  if (data?.tone === "warn") return "var(--warn)";
                  if (data?.tone === "success") return "var(--success)";
                  if (data?.tone === "cyan") return "#06b6d4";
                  return "var(--panel-2)";
                }}
                maskColor="rgba(9, 13, 22, 0.7)"
              />
              <Panel position="bottom-left" className="m-3">
                <div className="rounded-lg border border-border/80 bg-panel/90 p-2.5 backdrop-blur-md text-[11px] text-muted space-y-1">
                  <div className="font-semibold text-text">Canvas Controls:</div>
                  <div>• Pan: Drag canvas or scroll wheel</div>
                  <div>• Zoom: Pinch or +/- buttons</div>
                  <div>• Inspect: Click any component node</div>
                </div>
              </Panel>
            </ReactFlow>
          </div>

          {/* Component Inspector Panel (4 columns) */}
          <div className="space-y-4 lg:col-span-4">
            {selectedDetail ? (
              <Card
                title={selectedDetail.name}
                subtitle={selectedDetail.category}
                actions={
                  selectedDetail.implementationStatus ? (
                    <Badge
                      tone={
                        selectedDetail.implementationStatus === "implemented"
                          ? "success"
                          : selectedDetail.implementationStatus === "requires_adapter"
                          ? "cyan"
                          : "warn"
                      }
                    >
                      {selectedDetail.implementationStatus === "implemented"
                        ? "Implemented"
                        : selectedDetail.implementationStatus === "requires_adapter"
                        ? "Requires Adapter"
                        : "Planned"}
                    </Badge>
                  ) : (
                    <Badge tone="cyan">Inspecting</Badge>
                  )
                }
                className="sticky top-20"
              >
                <div className="space-y-4 text-xs">
                  <div>
                    <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                      Role &amp; Responsibility
                    </h4>
                    <p className="mt-1 text-text leading-relaxed font-normal">
                      {selectedDetail.role}
                    </p>
                  </div>

                  {selectedDetail.sourcePath && (
                    <div className="rounded-md border border-border/80 bg-panel-2/60 p-2 font-mono text-[11px]">
                      <span className="text-muted">Path: </span>
                      <span className="text-accent">{selectedDetail.sourcePath}</span>
                    </div>
                  )}

                  <div>
                    <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                      Inputs &amp; Invariants
                    </h4>
                    <ul className="mt-1 list-disc pl-4 space-y-0.5 text-text-muted">
                      {selectedDetail.inputs.map((inp, i) => (
                        <li key={i}>{inp}</li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                      Outputs &amp; State Changes
                    </h4>
                    <ul className="mt-1 list-disc pl-4 space-y-0.5 text-text-muted">
                      {selectedDetail.outputs.map((out, i) => (
                        <li key={i}>{out}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="rounded-lg border border-warn/30 bg-warn-soft/40 p-3">
                    <h4 className="font-bold uppercase tracking-wider text-warn text-[10px]">
                      Safety &amp; Trust Boundary
                    </h4>
                    <p className="mt-1 text-text leading-relaxed">
                      {selectedDetail.safetyBoundary}
                    </p>
                  </div>

                  <div className="rounded-lg border border-border bg-panel-2/40 p-3">
                    <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                      Error &amp; Failure Pathways
                    </h4>
                    <p className="mt-1 text-text-muted leading-relaxed">
                      {selectedDetail.errorPathways}
                    </p>
                  </div>

                  {selectedDetail.technicalSpecs && (
                    <div>
                      <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                        Technical Specifications
                      </h4>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {selectedDetail.technicalSpecs.map((s, i) => (
                          <Badge key={i} tone="neutral">
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </Card>
            ) : (
              <Card title="Component Inspector">
                <p className="text-xs text-muted">
                  Click any node in the interactive architecture canvas to inspect its role,
                  input/output invariants, error handling, and source files.
                </p>
              </Card>
            )}
          </div>
        </div>
      ) : (
        /* Accessible Structured Tree View */
        <Card
          title="Structured Architectural Hierarchy"
          subtitle="Keyboard-navigable accessible overview of all components, execution nodes, and safety boundaries."
        >
          <div className="space-y-6 text-sm">
            {Object.values(COMPONENT_DETAILS).map((c) => (
              <div
                key={c.id}
                className="rounded-xl border border-border bg-panel-2/50 p-4 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
                  <h3 className="font-bold text-text">{c.name}</h3>
                  <div className="flex items-center gap-2">
                    <Badge tone="cyan">{c.category}</Badge>
                    {c.implementationStatus && (
                      <Badge
                        tone={
                          c.implementationStatus === "implemented"
                            ? "success"
                            : c.implementationStatus === "requires_adapter"
                            ? "cyan"
                            : "warn"
                        }
                      >
                        {c.implementationStatus}
                      </Badge>
                    )}
                  </div>
                </div>
                <p className="text-xs text-text-muted">{c.role}</p>
                {c.sourcePath && (
                  <p className="font-mono text-xs text-accent">Source: {c.sourcePath}</p>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-2">
                  <div>
                    <strong className="text-text">Inputs:</strong>
                    <ul className="list-disc pl-4 mt-0.5 text-muted">
                      {c.inputs.map((inp, i) => (
                        <li key={i}>{inp}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <strong className="text-text">Outputs:</strong>
                    <ul className="list-disc pl-4 mt-0.5 text-muted">
                      {c.outputs.map((out, i) => (
                        <li key={i}>{out}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="rounded bg-warn-soft/30 p-2 text-xs text-text-muted">
                  <strong className="text-warn">Safety: </strong>
                  {c.safetyBoundary}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Component Legend */}
      <Card title="Architecture Status &amp; Protocol Legend">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-emerald-500" />
            <span className="text-text font-medium">Implemented in Repository</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-cyan-400" />
            <span className="text-text font-medium">Adapter Seam Available</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-amber-400" />
            <span className="text-text font-medium">Planned Roadmap Seam</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-purple-400" />
            <span className="text-text font-medium">Agent Graph / MCP Protocol</span>
          </div>
        </div>
      </Card>
    </div>
  );
}
