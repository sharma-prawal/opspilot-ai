"use client";

import { useState } from "react";

interface ArchComponent {
  id: string;
  name: string;
  category: "ingestion" | "agent" | "rag" | "safety" | "actuator";
  role: string;
  status: "implemented" | "requires_adapter" | "planned";
  sourcePath: string;
  inputs: string[];
  outputs: string[];
  safetyBoundary: string;
  errorPathways: string;
}

const COMPONENTS: ArchComponent[] = [
  {
    id: "COMP-01",
    name: "FastAPI BFF & Session Gateway",
    category: "ingestion",
    role: "Provides typed REST endpoints, session cookies, and CSRF protection for operator interactions.",
    status: "implemented",
    sourcePath: "apps/api/opspilot_api/main.py",
    inputs: ["HTTP /incidents", "HTTP /investigations", "Operator Auth Tokens"],
    outputs: ["JSON API Responses", "Event Streams", "Signed Action Tokens"],
    safetyBoundary: "Strict CORS, CSRF token verification, and session redaction to prevent credential leaks.",
    errorPathways: "Returns HTTP 401 on missing session, 403 on invalid CSRF, 503 if MCP child dies.",
  },
  {
    id: "COMP-02",
    name: "LangGraph Multi-Node StateGraph",
    category: "agent",
    role: "Orchestrates iterative incident triage, tool invocation, hypothesis pruning, and recovery verification.",
    status: "implemented",
    sourcePath: "packages/agents/opspilot_agents/graph.py",
    inputs: ["Incident Symptom", "Persisted Evidence", "Runbook Chunks"],
    outputs: ["Root-Cause Hypotheses", "Multi-Step Remediation Plan", "Final RCA Postmortem"],
    safetyBoundary: "Strict msgpack serialization fencing; halts at interrupt() prior to executing any mutating action.",
    errorPathways: "Escalates to human operator if max iterations exceeded or contradictory evidence detected.",
  },
  {
    id: "COMP-03",
    name: "Hybrid pgvector RAG Engine",
    category: "rag",
    role: "Indexes operational runbooks and past postmortems using dense embeddings + sparse BM25 keyword matching.",
    status: "implemented",
    sourcePath: "packages/rag/opspilot_rag/retrieval.py",
    inputs: ["Query Text", "Service Scope"],
    outputs: ["Ranked Runbook Chunks", "Reciprocal Rank Fusion Scores"],
    safetyBoundary: "Read-only database permissions; excludes draft or superseded runbook revisions.",
    errorPathways: "Degrades gracefully to keyword-only search if local embedding model is unavailable.",
  },
  {
    id: "COMP-04",
    name: "Deterministic Safety Gate Kernel",
    category: "safety",
    role: "Evaluates pure Python safety rules (D24-D28) to intercept dangerous or ungrounded actions.",
    status: "implemented",
    sourcePath: "packages/agents/opspilot_agents/gates.py",
    inputs: ["Proposed Action", "Target Parameters", "Persisted Telemetry Evidence"],
    outputs: ["PASS or BLOCKED Decision", "Explanatory Violation Token"],
    safetyBoundary: "Deterministic code boundary; cannot be overridden by LLM prompt injection.",
    errorPathways: "Forces plan re-formulation or safe human escalation upon boundary violation.",
  },
  {
    id: "COMP-05",
    name: "Loki & Prometheus Telemetry Connectors",
    category: "ingestion",
    role: "Connects to Grafana Loki 3.5.0 and Prometheus v3.5.0 via allowlisted GET-only query templates.",
    status: "implemented",
    sourcePath: "packages/shared/opspilot_shared/connectors/telemetry.py",
    inputs: ["Allowlisted Metric/Log Query Templates", "Time Window"],
    outputs: ["Normalized Evidence Records with Source Attribution"],
    safetyBoundary: "GET-only HTTP client; trusts no environment proxies; strictly scrubs authorization headers.",
    errorPathways: "Times out after 5000ms with explicit tool error message.",
  },
  {
    id: "COMP-06",
    name: "Datadog & CloudWatch Adapters",
    category: "ingestion",
    role: "Direct cloud observability ingestion for AWS and Datadog enterprise environments.",
    status: "planned",
    sourcePath: "docs/integrations/CONNECTORS.md#roadmap",
    inputs: ["CloudWatch Metric Queries", "Datadog Log Streams"],
    outputs: ["Standardized OpsPilot Evidence Format"],
    safetyBoundary: "Read-only IAM role policy enforcement with bounded query limits.",
    errorPathways: "Fallback to offline CSV/JSON evidence ingestion.",
  },
];

export default function ConceptAArchitecturePage() {
  const [selectedComp, setSelectedComp] = useState<ArchComponent>(COMPONENTS[1]);
  const [activeDiagram, setActiveDiagram] = useState<"system" | "sources">("system");

  return (
    <div className="space-y-6">
      {/* Masthead */}
      <div className="dossier-paper p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E2DFD5] pb-3">
          <div>
            <span className="exhibit-tag">EXHIBIT §04: SYSTEM CARTOGRAPHY</span>
            <h2 className="font-serif-heading mt-1 text-2xl font-bold text-[#16191D]">
              Architectural Cartography &amp; Integration Anatomy
            </h2>
          </div>
          <div className="flex rounded border border-[#C8C4B7] bg-[#F4F3EC] p-0.5 text-xs">
            <button
              onClick={() => setActiveDiagram("system")}
              className={`rounded px-3 py-1 font-medium transition-all ${
                activeDiagram === "system"
                  ? "bg-white text-[#16191D] font-bold shadow-xs"
                  : "text-[#78828F] hover:text-[#16191D]"
              }`}
            >
              System &amp; Safety Pipeline
            </button>
            <button
              onClick={() => setActiveDiagram("sources")}
              className={`rounded px-3 py-1 font-medium transition-all ${
                activeDiagram === "sources"
                  ? "bg-white text-[#16191D] font-bold shadow-xs"
                  : "text-[#78828F] hover:text-[#16191D]"
              }`}
            >
              Telemetry Sources (3 Modes)
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-[#4A525D]">
          Inspect the physical architecture boundaries of OpsPilot AI. Pure local inference, pgvector RAG retrieval, and deterministic safety kernel gates ensure zero unverified mutating actions reach production.
        </p>
      </div>

      {/* Main Cartography Canvas & Detail Inspector */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* Architectural Visual Map (7 cols) */}
        <div className="lg:col-span-7 dossier-paper p-6">
          <div className="flex items-center justify-between border-b border-[#E2DFD5] pb-2 font-mono text-xs text-[#78828F]">
            <span>ENGINEERING SUBSYSTEMS</span>
            <span>STATUS: 5 IMPLEMENTED · 1 PLANNED</span>
          </div>

          <div className="mt-6 space-y-4">
            {COMPONENTS.map((comp) => {
              const isSel = selectedComp.id === comp.id;
              const isImpl = comp.status === "implemented";
              return (
                <div
                  key={comp.id}
                  onClick={() => setSelectedComp(comp)}
                  className={`cursor-pointer rounded border p-4 transition-all ${
                    isSel
                      ? "border-[#C05621] bg-[#FFFBF5] shadow-xs"
                      : "border-[#E2DFD5] bg-[#FBFBF8] hover:bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between font-mono text-[11px]">
                    <div className="flex items-center gap-2">
                      <span className="exhibit-tag">{comp.id}</span>
                      <span className="font-bold text-[#16191D]">{comp.name}</span>
                    </div>
                    <span
                      className={`font-bold uppercase ${
                        isImpl ? "text-[#047857]" : "text-[#78828F]"
                      }`}
                    >
                      [{comp.status}]
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-[#4A525D] leading-relaxed">
                    {comp.role}
                  </p>
                  <div className="mt-2 font-mono text-[10px] text-[#78828F]">
                    Source: <code>{comp.sourcePath}</code>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Component Technical Dossier (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="dossier-paper p-5">
            <span className="exhibit-tag">SUBSYSTEM SPECIFICATION</span>
            <h3 className="font-serif-heading mt-2 text-xl font-bold text-[#16191D]">
              {selectedComp.name}
            </h3>
            <p className="font-mono text-xs text-[#78828F]">Module: {selectedComp.sourcePath}</p>

            <div className="mt-4 border-t border-[#E2DFD5] pt-3 text-xs space-y-4">
              <div>
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Subsystem Role:
                </span>
                <p className="mt-1 text-xs text-[#4A525D] leading-relaxed">
                  {selectedComp.role}
                </p>
              </div>

              <div>
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Inputs &amp; Ingress:
                </span>
                <ul className="mt-1 list-disc pl-4 text-[#4A525D] space-y-0.5">
                  {selectedComp.inputs.map((inp, i) => (
                    <li key={i}>{inp}</li>
                  ))}
                </ul>
              </div>

              <div>
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Outputs &amp; Egress:
                </span>
                <ul className="mt-1 list-disc pl-4 text-[#4A525D] space-y-0.5">
                  {selectedComp.outputs.map((out, i) => (
                    <li key={i}>{out}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded border border-[#C8C4B7] bg-[#F4F3EC] p-3">
                <span className="font-mono text-[10px] font-bold uppercase text-[#C05621]">
                  Safety Boundary Enforcement:
                </span>
                <p className="mt-1 text-[11px] text-[#4A525D] leading-relaxed">
                  {selectedComp.safetyBoundary}
                </p>
              </div>

              <div>
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Error Pathways &amp; Failure Modes:
                </span>
                <p className="mt-1 text-[11px] text-[#4A525D]">
                  {selectedComp.errorPathways}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
