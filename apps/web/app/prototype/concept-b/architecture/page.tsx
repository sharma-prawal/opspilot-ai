"use client";

import { useState } from "react";

interface Subsystem {
  id: string;
  name: string;
  busType: "SENSOR_INGEST" | "REASONING_CORE" | "HYBRID_STORAGE" | "SAFETY_FENCE" | "ACTUATOR";
  status: "ONLINE" | "PLANNED";
  file: string;
  role: string;
  inputs: string[];
  outputs: string[];
  safetyBoundary: string;
  errorPathways: string;
}

const SUBSYSTEMS: Subsystem[] = [
  {
    id: "SYS-01",
    name: "FastAPI BFF & Session Fence",
    busType: "SENSOR_INGEST",
    status: "ONLINE",
    file: "apps/api/opspilot_api/main.py",
    role: "Secures external client boundary with strict CSRF token validation and session secret redaction.",
    inputs: ["HTTP /incidents", "HTTP /investigations", "Operator Auth Tokens"],
    outputs: ["JSON Telemetry Frames", "SSE Stream", "Signed Action Tokens"],
    safetyBoundary: "No credential or unredacted environment variable leaks into client response frames.",
    errorPathways: "Returns HTTP 401 on unauthenticated access; 503 if MCP child exits unexpectedly.",
  },
  {
    id: "SYS-02",
    name: "LangGraph StateGraph Core",
    busType: "REASONING_CORE",
    status: "ONLINE",
    file: "packages/agents/opspilot_agents/graph.py",
    role: "Executes stateful LangGraph loop with local Ollama structured output and checkpoint resume.",
    inputs: ["Incident Symptom Stream", "Tool Outputs", "Runbook Embeddings"],
    outputs: ["Multi-Hypothesis Array", "Remediation Step Plan", "Cited RCA Postmortem"],
    safetyBoundary: "Halts at interrupt() gate prior to mutating state; serialized via strict msgpack fencing.",
    errorPathways: "Escalates to human operator if max tool iterations exceeded or contradictory evidence occurs.",
  },
  {
    id: "SYS-03",
    name: "pgvector Hybrid RAG Bank",
    busType: "HYBRID_STORAGE",
    status: "ONLINE",
    file: "packages/rag/opspilot_rag/retrieval.py",
    role: "Dense vector search (1024 dims) + PostgreSQL tsvector full-text search for runbooks and postmortems.",
    inputs: ["Diagnostic Query String", "Service Filter"],
    outputs: ["Ranked Runbook Chunks with Source Line Offsets"],
    safetyBoundary: "Read-only database roles; excludes draft or superseded runbook revisions.",
    errorPathways: "Degrades gracefully to keyword-only search if local Ollama embedding service is offline.",
  },
  {
    id: "SYS-04",
    name: "Deterministic Safety Gate Kernel",
    busType: "SAFETY_FENCE",
    status: "ONLINE",
    file: "packages/agents/opspilot_agents/gates.py",
    role: "Pure Python invariant validator (rules D24-D28) guarding against dangerous autonomous actions.",
    inputs: ["Proposed Action", "Execution Arguments", "Persisted Telemetry Evidence"],
    outputs: ["PASS or BLOCKED Decision Frame"],
    safetyBoundary: "Hardware ceiling enforcement; completely immutable by LLM prompt injection.",
    errorPathways: "Forces plan re-formulation or safe escalation upon boundary violation.",
  },
  {
    id: "SYS-05",
    name: "Loki & Prometheus Connectors",
    busType: "SENSOR_INGEST",
    status: "ONLINE",
    file: "packages/shared/opspilot_shared/connectors/telemetry.py",
    role: "Allowlisted GET-only query templates for live Grafana Loki 3.5.0 and Prometheus v3.5.0.",
    inputs: ["Allowlisted Metric/Log Query Templates", "Time Window"],
    outputs: ["Normalized Evidence Records with Source Attribution"],
    safetyBoundary: "Strict read-only GET requests; zero credential propagation to target endpoints.",
    errorPathways: "Times out after 5000ms with explicit tool error message.",
  },
  {
    id: "SYS-06",
    name: "Datadog & CloudWatch Adapters",
    busType: "SENSOR_INGEST",
    status: "PLANNED",
    file: "docs/integrations/CONNECTORS.md",
    role: "Enterprise telemetry connectors for cloud observability systems.",
    inputs: ["CloudWatch Metric Queries", "Datadog Log Streams"],
    outputs: ["OpsPilot Normalized Telemetry"],
    safetyBoundary: "Read-only IAM role policy enforcement with bounded query limits.",
    errorPathways: "Fallback to offline CSV/JSON evidence ingestion.",
  },
];

export default function ConceptBArchitecturePage() {
  const [selectedSubsys, setSelectedSubsys] = useState<Subsystem>(SUBSYSTEMS[1]);

  return (
    <div className="space-y-4 font-mono">
      {/* Console Masthead */}
      <div className="avionics-frame p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#232A35] pb-2">
          <div>
            <div className="text-[10px] text-[#F59E0B] font-bold">
              AVIONICS ARCHITECTURE // BUS CARTOGRAPHY
            </div>
            <h2 className="text-base font-bold text-white">
              Subsystem Telemetry Bus &amp; Integration Matrix
            </h2>
          </div>
          <div className="text-[10px] text-[#8B97A8]">
            KERNEL TOPOLOGY: <span className="text-[#10B981]">5 ACTIVE // 1 PLANNED</span>
          </div>
        </div>
        <p className="mt-1 text-xs text-[#8B97A8]">
          Physical separation between telemetry ingress, local LLM reasoning, pgvector hybrid memory, and deterministic safety kernel boundaries.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        {/* Subsystems List (7 cols) */}
        <div className="lg:col-span-7 space-y-2.5">
          {SUBSYSTEMS.map((sub) => {
            const isSel = selectedSubsys.id === sub.id;
            const isOnline = sub.status === "ONLINE";
            return (
              <div
                key={sub.id}
                onClick={() => setSelectedSubsys(sub)}
                className={`cursor-pointer rounded border p-3 text-xs transition-all ${
                  isSel
                    ? "border-[#F59E0B] bg-[#181D24] shadow-[0_0_10px_rgba(245,158,11,0.15)]"
                    : "border-[#232A35] bg-[#111419] hover:border-[#3B4657]"
                }`}
              >
                <div className="flex items-center justify-between text-[10px]">
                  <span className="font-bold text-[#F59E0B]">[{sub.id}]</span>
                  <span className="text-[#8B97A8]">{sub.busType}</span>
                  <span
                    className={`font-bold ${isOnline ? "text-[#10B981]" : "text-[#525D6D]"}`}
                  >
                    [{sub.status}]
                  </span>
                </div>
                <h4 className="mt-1 font-bold text-white">{sub.name}</h4>
                <p className="mt-1 text-[11px] text-[#8B97A8] leading-relaxed">{sub.role}</p>
                <div className="mt-2 text-[10px] text-[#525D6D]">
                  FILE: <code>{sub.file}</code>
                </div>
              </div>
            );
          })}
        </div>

        {/* Selected Subsystem Detail (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>AVIONICS SPECIFICATION // {selectedSubsys.id}</span>
              <span className="text-[#F59E0B] font-bold">{selectedSubsys.status}</span>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="text-[10px] text-[#525D6D]">SUBSYSTEM NAME</span>
                <div className="text-white font-bold">{selectedSubsys.name}</div>
              </div>

              <div>
                <span className="text-[10px] text-[#525D6D]">SOURCE FILE TARGET</span>
                <div className="text-[#06B6D4] text-[11px]">{selectedSubsys.file}</div>
              </div>

              <div>
                <span className="text-[10px] text-[#525D6D]">INGRESS SIGNALS</span>
                <ul className="mt-1 list-disc pl-4 text-[#8B97A8] space-y-0.5 text-[11px]">
                  {selectedSubsys.inputs.map((inp, i) => (
                    <li key={i}>{inp}</li>
                  ))}
                </ul>
              </div>

              <div>
                <span className="text-[10px] text-[#525D6D]">EGRESS SIGNALS</span>
                <ul className="mt-1 list-disc pl-4 text-[#8B97A8] space-y-0.5 text-[11px]">
                  {selectedSubsys.outputs.map((out, i) => (
                    <li key={i}>{out}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2.5">
                <span className="text-[10px] text-[#EF4444] font-bold">SAFETY FENCE INVARIANT</span>
                <p className="mt-0.5 text-[10px] text-[#8B97A8]">
                  {selectedSubsys.safetyBoundary}
                </p>
              </div>

              <div>
                <span className="text-[10px] text-[#525D6D]">ERROR PATHWAYS</span>
                <p className="mt-0.5 text-[10px] text-[#8B97A8]">
                  {selectedSubsys.errorPathways}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
