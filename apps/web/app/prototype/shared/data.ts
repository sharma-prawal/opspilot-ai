export interface ScenarioDetail {
  key: string;
  title: string;
  service: string;
  category: "mitigated" | "escalate" | "no_action";
  mode: "simulator" | "uploaded" | "connected";
  description: string;
  triggerTime: string;
  ttdSeconds: number;
  confidence: number;
  hypotheses: Array<{
    id: string;
    title: string;
    probability: number;
    supportingEvidence: string[];
    contradictingEvidence: string[];
    status: "confirmed" | "refuted" | "plausible";
    reasoning: string;
  }>;
  evidence: Array<{
    id: string;
    kind: "log" | "metric" | "trace" | "change" | "document" | "connector";
    source: string;
    sourceRef?: string;
    service?: string;
    timestamp: string;
    title: string;
    summary: string;
    relevance: number;
    cited: boolean;
    anomalyScore?: number;
    rawPayload?: Record<string, unknown>;
  }>;
  safetyGates: Array<{
    id: string;
    name: string;
    status: "passed" | "blocked" | "evaluating";
    rule: string;
    detail: string;
    timestamp: string;
  }>;
  remediationPlan: Array<{
    step: number;
    action: string;
    targetService: string;
    riskLevel: "low" | "medium" | "critical";
    requiresApproval: boolean;
    status: "approved" | "executed" | "pending" | "blocked" | "skipped";
    idempotent: boolean;
    rationale: string;
  }>;
  eventsTimeline: Array<{
    timeOffset: string; // e.g. "-04:12" or "+01:30"
    absoluteTime: string;
    type: "telemetry" | "deploy" | "agent_node" | "gate" | "approval" | "recovery";
    node?: string;
    summary: string;
    details: string;
    severity?: "nominal" | "warning" | "critical";
  }>;
  rcaSummary: {
    rootCause: string;
    category: string;
    primaryDeployment?: string;
    recoveryConfirmed: boolean;
    meanTimeToResolve: string;
    provenanceTable: Array<{
      claim: string;
      sourceExhibit: string;
      verifier: string;
    }>;
  };
}

export const PROTOTYPE_SCENARIOS: Record<string, ScenarioDetail> = {
  "INC-003": {
    key: "INC-003",
    title: "Invalid settlement payloads flooding Dead-Letter Queue",
    service: "settlement-worker",
    category: "mitigated",
    mode: "simulator",
    description: "Schema drift in upstream transaction-api causes unhandled deserialization crashes in settlement-worker consumer loop, poisoning DLQ with 1,420 dropped records.",
    triggerTime: "12:14:02 UTC",
    ttdSeconds: 24,
    confidence: 0.96,
    hypotheses: [
      {
        id: "HYP-01",
        title: "Poison message schema drift post dep-sw-0819",
        probability: 0.96,
        supportingEvidence: ["EVID-L01", "EVID-C01", "EVID-M01", "EVID-T01"],
        contradictingEvidence: [],
        status: "confirmed",
        reasoning: "Correlated timestamp with dep-sw-0819 release, stack trace points to missing 'vat_code' attribute during JSON decode.",
      },
      {
        id: "HYP-02",
        title: "Downstream RabbitMQ broker partition",
        probability: 0.12,
        supportingEvidence: ["EVID-M01"],
        contradictingEvidence: ["EVID-M02", "EVID-L02"],
        status: "refuted",
        reasoning: "Broker TCP connection remains healthy; message ingress is steady while consumer ack drops to zero.",
      },
      {
        id: "HYP-03",
        title: "Database connection leak in batch flusher",
        probability: 0.04,
        supportingEvidence: [],
        contradictingEvidence: ["EVID-M03"],
        status: "refuted",
        reasoning: "Postgres connection count is 14/100, well below saturation threshold.",
      },
    ],
    evidence: [
      {
        id: "EVID-L01",
        kind: "log",
        source: "MCP:search_logs",
        sourceRef: "settlement-worker/stdout#L4812",
        service: "settlement-worker",
        timestamp: "12:14:05 UTC",
        title: "Deserialization KeyError: 'vat_code'",
        summary: "Traceback in consumer.py:84: KeyError: 'vat_code' in parse_settlement_record(). 1,420 errors in 180s.",
        relevance: 0.98,
        cited: true,
        anomalyScore: 0.95,
        rawPayload: { exception: "KeyError", field: "vat_code", count: 1420 },
      },
      {
        id: "EVID-C01",
        kind: "change",
        source: "MCP:get_recent_deployments",
        sourceRef: "git:sharma-prawal/opspilot-ai@011853f",
        service: "settlement-worker",
        timestamp: "12:12:30 UTC",
        title: "Deployment dep-sw-0819 rolled out",
        summary: "Release v2.14.0 promoted to production 92 seconds prior to DLQ error rate explosion.",
        relevance: 0.94,
        cited: true,
        anomalyScore: 0.88,
        rawPayload: { deployId: "dep-sw-0819", author: "sre-oncall", diffSummary: "require strict vat_code" },
      },
      {
        id: "EVID-M01",
        kind: "metric",
        source: "MCP:get_service_metrics",
        sourceRef: "prom:rabbitmq_dlq_messages_total",
        service: "settlement-worker",
        timestamp: "12:14:00 UTC",
        title: "DLQ message accumulation spike",
        summary: "DLQ depth jumped from 0 to 1,420 msgs/min (14.2 std deviations above baseline).",
        relevance: 0.92,
        cited: true,
        anomalyScore: 0.99,
        rawPayload: { metric: "rabbitmq_dlq_messages_total", value: 1420, baseline: 0 },
      },
      {
        id: "EVID-T01",
        kind: "trace",
        source: "MCP:inspect_trace",
        sourceRef: "jaeger:span-88f21901b",
        service: "settlement-worker",
        timestamp: "12:14:08 UTC",
        title: "Consumer batch transaction abort",
        summary: "Span failed at settlement_consumer:process_batch with unhandled exception.",
        relevance: 0.89,
        cited: true,
        anomalyScore: 0.85,
        rawPayload: { traceId: "88f21901b", durationMs: 44, status: "error" },
      },
      {
        id: "EVID-D01",
        kind: "document",
        source: "RAG:hybrid_pgvector",
        sourceRef: "runbooks/settlement-consumer-recovery.md#chunk-41a",
        service: "settlement-worker",
        timestamp: "Static Runbook",
        title: "Runbook: Poison Message Quarantine Procedure",
        summary: "Approved runbook dictates immediate consumer pause, revision rollback, DLQ quarantine, and resume.",
        relevance: 0.91,
        cited: true,
        rawPayload: { runbookId: "RB-SETTLE-004", revision: "2026-10-12" },
      },
    ],
    safetyGates: [
      {
        id: "GATE-01",
        name: "Destructive Action Fencing",
        status: "passed",
        rule: "No DROP, TRUNCATE, or permanent message discard permitted.",
        detail: "Quarantine moves messages to safe isolation queue; zero data loss.",
        timestamp: "12:14:28 UTC",
      },
      {
        id: "GATE-02",
        name: "Evidence Grounding Threshold",
        status: "passed",
        rule: "Plan must cite ≥2 distinct telemetry sources and matching runbook.",
        detail: "Cited EVID-L01 (log), EVID-M01 (metric), EVID-C01 (change), RB-SETTLE-004.",
        timestamp: "12:14:29 UTC",
      },
      {
        id: "GATE-03",
        name: "Cryptographic Human Approval",
        status: "passed",
        rule: "Action token signed by authorized operator key before sandbox dispatch.",
        detail: "Signed by demo-operator · Token: tok_9f81a7b0… (valid for 300s)",
        timestamp: "12:14:35 UTC",
      },
    ],
    remediationPlan: [
      {
        step: 1,
        action: "pause_consumer",
        targetService: "settlement-worker",
        riskLevel: "low",
        requiresApproval: true,
        status: "executed",
        idempotent: true,
        rationale: "Halt incoming poisonous message consumption to prevent cascading DLQ overflow.",
      },
      {
        step: 2,
        action: "rollback_deployment",
        targetService: "settlement-worker",
        riskLevel: "medium",
        requiresApproval: true,
        status: "executed",
        idempotent: true,
        rationale: "Revert from dep-sw-0819 back to known-stable dep-sw-0818.",
      },
      {
        step: 3,
        action: "quarantine_messages",
        targetService: "settlement-worker",
        riskLevel: "low",
        requiresApproval: true,
        status: "executed",
        idempotent: true,
        rationale: "Transfer 1,420 poison payloads to quarantine-v2 queue for safe inspection.",
      },
      {
        step: 4,
        action: "resume_consumer",
        targetService: "settlement-worker",
        riskLevel: "low",
        requiresApproval: true,
        status: "executed",
        idempotent: true,
        rationale: "Restore consumer workers on stable code version dep-sw-0818.",
      },
    ],
    eventsTimeline: [
      {
        timeOffset: "-01:32",
        absoluteTime: "12:12:30 UTC",
        type: "deploy",
        summary: "Deployment dep-sw-0819 completed",
        details: "Promoted commit 011853f by automated release pipeline.",
        severity: "nominal",
      },
      {
        timeOffset: "+00:00",
        absoluteTime: "12:14:02 UTC",
        type: "telemetry",
        summary: "Incident Onset — DLQ rate spike",
        details: "DLQ ingress breached 50 msgs/sec critical alerting threshold.",
        severity: "critical",
      },
      {
        timeOffset: "+00:15",
        absoluteTime: "12:14:17 UTC",
        type: "agent_node",
        node: "triage_symptom",
        summary: "LangGraph Agent dispatched triage node",
        details: "Fetched RabbitMQ queue stats via MCP tool inspect_queue.",
        severity: "nominal",
      },
      {
        timeOffset: "+00:27",
        absoluteTime: "12:14:29 UTC",
        type: "gate",
        summary: "Deterministic Safety Gate 3/3 Passed",
        details: "Evidence validated against runbook RB-SETTLE-004.",
        severity: "nominal",
      },
      {
        timeOffset: "+00:33",
        absoluteTime: "12:14:35 UTC",
        type: "approval",
        summary: "Operator approval granted",
        details: "demo-operator signed execution lease for 4-step remediation plan.",
        severity: "warning",
      },
      {
        timeOffset: "+01:12",
        absoluteTime: "12:15:14 UTC",
        type: "recovery",
        summary: "Verified Recovery Confirmed",
        details: "DLQ ingress dropped to 0 msgs/sec, consumer ack rate restored to 850/sec.",
        severity: "nominal",
      },
    ],
    rcaSummary: {
      rootCause: "Deployment dep-sw-0819 introduced strict schema validation on 'vat_code' which was absent in legacy transaction payloads, causing deserialization crashes and poison-head queue stalling.",
      category: "Software Defect / Backward Incompatible Contract",
      primaryDeployment: "dep-sw-0819",
      recoveryConfirmed: true,
      meanTimeToResolve: "1m 12s",
      provenanceTable: [
        { claim: "DLQ queue flooded with 1,420 msgs", sourceExhibit: "EVID-M01", verifier: "MCP:inspect_queue" },
        { claim: "KeyError 'vat_code' in deserializer", sourceExhibit: "EVID-L01", verifier: "MCP:search_logs" },
        { claim: "Deployment timestamp correlated -92s", sourceExhibit: "EVID-C01", verifier: "MCP:get_recent_deployments" },
        { claim: "Recovery verified by zero DLQ growth", sourceExhibit: "EVID-M01", verifier: "MCP:verify_recovery" },
      ],
    },
  },

  "INC-002": {
    key: "INC-002",
    title: "Database connection pool exhaustion & safety gate block",
    service: "ledger-db",
    category: "mitigated",
    mode: "simulator",
    description: "Unindexed query in dep-ls-0291 drives pool saturation to 93%. Agent proposed scaling pool to 120; safety gate blocked resize as dangerous, safely forcing deploy rollback instead.",
    triggerTime: "09:41:15 UTC",
    ttdSeconds: 18,
    confidence: 0.94,
    hypotheses: [
      {
        id: "HYP-01",
        title: "Unindexed sequential scan introduced in dep-ls-0291",
        probability: 0.94,
        supportingEvidence: ["EVID-L10", "EVID-C10", "EVID-M10"],
        contradictingEvidence: [],
        status: "confirmed",
        reasoning: "Query pg_stat_activity shows 48 idle-in-transaction connections holding table lock on account_balances.",
      },
      {
        id: "HYP-02",
        title: "External DDoS traffic burst on /transfer endpoint",
        probability: 0.08,
        supportingEvidence: [],
        contradictingEvidence: ["EVID-M11"],
        status: "refuted",
        reasoning: "Ingress request volume is flat (+1.4% delta), ruling out external load spike.",
      },
    ],
    evidence: [
      {
        id: "EVID-L10",
        kind: "log",
        source: "MCP:search_logs",
        sourceRef: "ledger-db/postgres.log#L1092",
        service: "ledger-db",
        timestamp: "09:41:20 UTC",
        title: "FATAL: remaining connection slots reserved for superuser",
        summary: "Connection count reached 47/50 max connections on ledger-db primary.",
        relevance: 0.98,
        cited: true,
        anomalyScore: 0.96,
      },
      {
        id: "EVID-C10",
        kind: "change",
        source: "MCP:get_recent_deployments",
        sourceRef: "git:sharma-prawal/opspilot-ai@9f1ee66",
        service: "ledger-service",
        timestamp: "09:39:00 UTC",
        title: "Deployment dep-ls-0291 rolled out",
        summary: "Query filter updated in balance calculation without covering composite index.",
        relevance: 0.93,
        cited: true,
        anomalyScore: 0.89,
      },
      {
        id: "EVID-M10",
        kind: "metric",
        source: "MCP:get_service_metrics",
        sourceRef: "prom:pg_stat_database_numbackends",
        service: "ledger-db",
        timestamp: "09:41:15 UTC",
        title: "Database connection pool utilization 94%",
        summary: "Active backends jumped from normal 12 to 47 in 120 seconds.",
        relevance: 0.95,
        cited: true,
        anomalyScore: 0.97,
      },
    ],
    safetyGates: [
      {
        id: "GATE-01",
        name: "Max Capacity Safety Bound (D25)",
        status: "blocked",
        rule: "Connection pool cannot be scaled beyond 50 connections on db.m5.large.",
        detail: "BLOCKED: Proposed scale_connection_pool(size=120) exceeds hardware RAM ceiling and would trigger OOM kill.",
        timestamp: "09:41:40 UTC",
      },
      {
        id: "GATE-02",
        name: "Fallback Plan Formulation",
        status: "passed",
        rule: "When capacity increase is blocked, agent must formulate safe software rollback.",
        detail: "Formulated fallback rollback to dep-ls-0290.",
        timestamp: "09:41:42 UTC",
      },
    ],
    remediationPlan: [
      {
        step: 1,
        action: "scale_connection_pool(120)",
        targetService: "ledger-db",
        riskLevel: "critical",
        requiresApproval: true,
        status: "blocked",
        idempotent: false,
        rationale: "Attempted to raise pool limit to absorb stuck transactions (BLOCKED BY SAFETY GATE).",
      },
      {
        step: 2,
        action: "rollback_deployment",
        targetService: "ledger-service",
        riskLevel: "medium",
        requiresApproval: true,
        status: "executed",
        idempotent: true,
        rationale: "Roll back dep-ls-0291 to restore indexed balance lookup pattern.",
      },
    ],
    eventsTimeline: [
      {
        timeOffset: "-02:15",
        absoluteTime: "09:39:00 UTC",
        type: "deploy",
        summary: "Deployment dep-ls-0291 promoted",
        details: "Changes balance lookup SQL query.",
        severity: "nominal",
      },
      {
        timeOffset: "+00:00",
        absoluteTime: "09:41:15 UTC",
        type: "telemetry",
        summary: "Connection saturation alarm fired",
        details: "Pool utilization reached 94%.",
        severity: "critical",
      },
      {
        timeOffset: "+00:25",
        absoluteTime: "09:41:40 UTC",
        type: "gate",
        summary: "SAFETY GATE TRIGGERED — Resize Action Blocked",
        details: "Deterministic rule D25 blocked scale_connection_pool. Agent replanned rollback.",
        severity: "critical",
      },
      {
        timeOffset: "+00:52",
        absoluteTime: "09:42:07 UTC",
        type: "recovery",
        summary: "Verified Recovery Confirmed",
        details: "Active connections normalized to 11 backends.",
        severity: "nominal",
      },
    ],
    rcaSummary: {
      rootCause: "Unindexed sequential table scan in dep-ls-0291 caused connection starvation. The autonomous agent attempted an unsafe pool resize, which was deterministically blocked by OpsPilot safety gates before rollback mitigated the issue.",
      category: "Performance Regression & Safety Gate Interception",
      primaryDeployment: "dep-ls-0291",
      recoveryConfirmed: true,
      meanTimeToResolve: "52s",
      provenanceTable: [
        { claim: "Connection saturation at 47/50", sourceExhibit: "EVID-M10", verifier: "MCP:get_service_metrics" },
        { claim: "Unsafe pool resize blocked by rule D25", sourceExhibit: "GATE-01", verifier: "SafetyKernel" },
        { claim: "Rollback restored pool to 11 connections", sourceExhibit: "EVID-M10", verifier: "MCP:verify_recovery" },
      ],
    },
  },

  "UPLOAD-01": {
    key: "UPLOAD-01",
    title: "Forensic Analysis of Uploaded Incident Logs & Metrics",
    service: "checkout-gateway",
    category: "mitigated",
    mode: "uploaded",
    description: "Operator uploaded 3 local files: checkout_logs_20261118.json, metrics_timeseries.csv, and jaeger_trace.json for offline investigation.",
    triggerTime: "Yesterday 18:30:00 UTC",
    ttdSeconds: 41,
    confidence: 0.91,
    hypotheses: [
      {
        id: "HYP-01",
        title: "Timeout cascade across payment microservices",
        probability: 0.91,
        supportingEvidence: ["EVID-UP-01", "EVID-UP-02"],
        contradictingEvidence: [],
        status: "confirmed",
        reasoning: "Uploaded trace shows HTTP 504 gateway timeout after 5,000ms waiting for checkout-worker.",
      },
    ],
    evidence: [
      {
        id: "EVID-UP-01",
        kind: "log",
        source: "Upload:checkout_logs.json",
        sourceRef: "checkout_logs.json#L842",
        service: "checkout-gateway",
        timestamp: "18:30:12 UTC",
        title: "GatewayTimeout: upstream payment-service timed out",
        summary: "504 Gateway Timeout on POST /api/v1/checkout. Response time: 5,002ms.",
        relevance: 0.95,
        cited: true,
      },
      {
        id: "EVID-UP-02",
        kind: "metric",
        source: "Upload:metrics_timeseries.csv",
        sourceRef: "metrics_timeseries.csv#row:142",
        service: "checkout-gateway",
        timestamp: "18:30:00 UTC",
        title: "P99 latency jumped from 140ms to 5,100ms",
        summary: "Telemetry snapshot records latency plateau matching 5s HTTP client timeout.",
        relevance: 0.92,
        cited: true,
      },
    ],
    safetyGates: [
      {
        id: "GATE-RO",
        name: "Read-Only Sandbox Enforcement",
        status: "passed",
        rule: "Uploaded evidence investigations are strictly read-only; no infrastructure actions permitted.",
        detail: "Remediation engine is disabled; recommendations only.",
        timestamp: "18:30:45 UTC",
      },
    ],
    remediationPlan: [
      {
        step: 1,
        action: "recommend_circuit_breaker_adjustment",
        targetService: "checkout-gateway",
        riskLevel: "low",
        requiresApproval: false,
        status: "pending",
        idempotent: true,
        rationale: "ADVISORY ONLY: Adjust client timeout from 5000ms to 2500ms with fail-fast fallback.",
      },
    ],
    eventsTimeline: [
      {
        timeOffset: "+00:00",
        absoluteTime: "18:30:00 UTC",
        type: "telemetry",
        summary: "Uploaded telemetry parsed",
        details: "1,240 log records and 450 metric samples ingested and normalized.",
        severity: "warning",
      },
      {
        timeOffset: "+00:41",
        absoluteTime: "18:30:41 UTC",
        type: "agent_node",
        node: "rca_synthesis",
        summary: "Offline RCA Generated",
        details: "Cited evidence generated with line-level file coordinates.",
        severity: "nominal",
      },
    ],
    rcaSummary: {
      rootCause: "Uploaded evidence confirms upstream timeout cascade in payment-service caused client thread exhaustion. (Read-only analysis: no remediation executed).",
      category: "Upstream Dependency Degradation",
      primaryDeployment: "Unknown (offline dataset)",
      recoveryConfirmed: false,
      meanTimeToResolve: "N/A (Read-only forensic audit)",
      provenanceTable: [
        { claim: "HTTP 504 Timeout on checkout", sourceExhibit: "EVID-UP-01", verifier: "checkout_logs.json#L842" },
        { claim: "P99 latency spike to 5,100ms", sourceExhibit: "EVID-UP-02", verifier: "metrics_timeseries.csv#row:142" },
      ],
    },
  },

  "CONN-01": {
    key: "CONN-01",
    title: "Connected Loki / Prometheus Telemetry Snapshot Investigation",
    service: "transaction-api",
    category: "mitigated",
    mode: "connected",
    description: "Read-only live connector ingested snapshots from local Grafana Loki (3.5.0) and Prometheus (v3.5.0) via approved GET-only query templates.",
    triggerTime: "10:15:00 UTC",
    ttdSeconds: 29,
    confidence: 0.93,
    hypotheses: [
      {
        id: "HYP-01",
        title: "Connection pool drop captured in Prometheus gauge",
        probability: 0.93,
        supportingEvidence: ["EVID-CONN-01", "EVID-CONN-02"],
        contradictingEvidence: [],
        status: "confirmed",
        reasoning: "Prometheus gauge db_pool_max dropped from 50 to 10 at 10:14:30 UTC.",
      },
    ],
    evidence: [
      {
        id: "EVID-CONN-01",
        kind: "connector",
        source: "Connector:Prometheus",
        sourceRef: "prom:db_pool_max{service='transaction-api'}",
        service: "transaction-api",
        timestamp: "10:14:30 UTC",
        title: "Gauge db_pool_max dropped from 50 → 10",
        summary: "Collected via template 'Prometheus Pool Metrics'. Confirms pool size shrinkage.",
        relevance: 0.97,
        cited: true,
      },
      {
        id: "EVID-CONN-02",
        kind: "connector",
        source: "Connector:Loki",
        sourceRef: "loki:{service='transaction-api'} |= 'timeout'",
        service: "transaction-api",
        timestamp: "10:15:02 UTC",
        title: "Loki stream captured 88 connection timeout errors",
        summary: "Collected via template 'Loki Error Streams'. Query completed in 18ms.",
        relevance: 0.94,
        cited: true,
      },
    ],
    safetyGates: [
      {
        id: "GATE-CONN",
        name: "Connected Mode Read-Only Gate (D113)",
        status: "passed",
        rule: "Connected Loki/Prometheus sources are strictly read-only. No mutating actions allowed.",
        detail: "Zero infrastructure mutations permitted; full evidence attribution preserved.",
        timestamp: "10:15:20 UTC",
      },
    ],
    remediationPlan: [
      {
        step: 1,
        action: "advisory_remediation_report",
        targetService: "transaction-api",
        riskLevel: "low",
        requiresApproval: false,
        status: "pending",
        idempotent: true,
        rationale: "Export cited RCA report with Prometheus/Loki query timestamps for operator execution.",
      },
    ],
    eventsTimeline: [
      {
        timeOffset: "+00:00",
        absoluteTime: "10:15:00 UTC",
        type: "telemetry",
        summary: "Snapshot queries executed against Loki & Prometheus",
        details: "Allowlisted GET queries verified with zero secret leaks.",
        severity: "nominal",
      },
      {
        timeOffset: "+00:29",
        absoluteTime: "10:15:29 UTC",
        type: "agent_node",
        node: "rca_synthesis",
        summary: "Connected RCA Synthesized",
        details: "Confidence flagged as uncalibrated (connected mode policy).",
        severity: "nominal",
      },
    ],
    rcaSummary: {
      rootCause: "Prometheus gauge indicates db_pool_max was dropped from 50 to 10, starving transaction-api workers. (Connected mode: read-only analysis without real infrastructure mutation).",
      category: "Configuration Drift / Telemetry Attributed",
      primaryDeployment: "Unknown (Change tools unconfigured for connected mode)",
      recoveryConfirmed: false,
      meanTimeToResolve: "29s analysis",
      provenanceTable: [
        { claim: "db_pool_max dropped to 10", sourceExhibit: "EVID-CONN-01", verifier: "prom:db_pool_max" },
        { claim: "88 timeout errors logged", sourceExhibit: "EVID-CONN-02", verifier: "loki:{service='transaction-api'}" },
      ],
    },
  },
};
