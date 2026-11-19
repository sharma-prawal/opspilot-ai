"use client";

import Link from "next/link";
import { useState } from "react";

export default function ConceptAHomePage() {
  const [activeTab, setActiveTab] = useState<"simulator" | "uploaded" | "connected">("simulator");

  return (
    <div className="space-y-10">
      {/* Editorial Lab Intro / Intake Dispatch */}
      <section className="border-b border-[#E2DFD5] pb-8">
        <div className="grid gap-8 lg:grid-cols-12">
          <div className="lg:col-span-8 space-y-4">
            <div className="inline-flex items-center gap-2 rounded border border-[#C8C4B7] bg-[#F4F3EC] px-2.5 py-1 text-xs">
              <span className="size-1.5 rounded-full bg-[#C05621]" />
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-[#4A525D]">
                Forensic Case Intake &amp; Causal Analysis
              </span>
            </div>
            <h2 className="font-serif-heading text-3xl font-bold tracking-tight text-[#16191D] sm:text-4xl">
              Evidence-grounded root-cause forensics for distributed infrastructure.
            </h2>
            <p className="max-w-2xl text-base leading-relaxed text-[#4A525D]">
              OpsPilot functions like an independent forensics laboratory. Rather than hallucinating or executing unconstrained bash scripts, the AI agent ingests verifiable telemetry exhibits, cross-examines competing failure hypotheses against approved runbooks, and submits deterministic remediation plans to cryptographic human authorization.
            </p>
          </div>

          {/* Forensic Invariant Dossier Box */}
          <div className="lg:col-span-4 rounded-sm border border-[#C8C4B7] bg-[#F4F3EC] p-5 shadow-inner">
            <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-[#16191D] border-b border-[#E2DFD5] pb-2">
              Forensic Invariants
            </h3>
            <ul className="mt-3 space-y-2.5 text-xs text-[#4A525D]">
              <li className="flex items-start gap-2">
                <span className="font-mono font-bold text-[#C05621]">01.</span>
                <span><strong>No Paid Cloud Inference:</strong> 100% localized Ollama model execution behind strictly typed ports.</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="font-mono font-bold text-[#C05621]">02.</span>
                <span><strong>Deterministic Gates:</strong> Dangerous actions (e.g. pool resizing over hardware limits) are intercepted pre-execution.</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="font-mono font-bold text-[#C05621]">03.</span>
                <span><strong>Attributed RCA:</strong> Every root-cause assertion must cite indexed evidence rows or files.</span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* Investigation Intake Pathways (3 Real Modes) */}
      <section className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E2DFD5] pb-3">
          <div>
            <h3 className="font-serif-heading text-xl font-bold text-[#16191D]">
              Initiate Investigation Dossier
            </h3>
            <p className="text-xs text-[#78828F]">
              Select an investigation pathway: simulated fault injection, uploaded forensic artifacts, or read-only connected telemetry.
            </p>
          </div>

          <div className="flex rounded border border-[#C8C4B7] bg-[#F4F3EC] p-0.5 text-xs">
            <button
              onClick={() => setActiveTab("simulator")}
              className={`rounded px-3 py-1 font-medium transition-all ${
                activeTab === "simulator"
                  ? "bg-white text-[#16191D] shadow-xs font-semibold"
                  : "text-[#4A525D] hover:text-[#16191D]"
              }`}
            >
              1. Simulated Scenarios (6)
            </button>
            <button
              onClick={() => setActiveTab("uploaded")}
              className={`rounded px-3 py-1 font-medium transition-all ${
                activeTab === "uploaded"
                  ? "bg-white text-[#16191D] shadow-xs font-semibold"
                  : "text-[#4A525D] hover:text-[#16191D]"
              }`}
            >
              2. Uploaded Artifacts
            </button>
            <button
              onClick={() => setActiveTab("connected")}
              className={`rounded px-3 py-1 font-medium transition-all ${
                activeTab === "connected"
                  ? "bg-white text-[#16191D] shadow-xs font-semibold"
                  : "text-[#4A525D] hover:text-[#16191D]"
              }`}
            >
              3. Connected Loki/Prometheus
            </button>
          </div>
        </div>

        {/* Tab 1: Simulator Scenarios */}
        {activeTab === "simulator" && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[
              {
                id: "INC-001",
                title: "Incompatible schema migration",
                service: "transaction-api",
                tag: "Mitigated",
                tagTone: "emerald",
                summary: "HTTP 500 spike after unnotified column rename in ledger-service. Agent identifies regression in dep-ls-0042 and initiates rollback.",
                remediation: "Rollback dep-ls-0042 → Verified Recovery",
              },
              {
                id: "INC-002",
                title: "Connection pool exhaustion",
                service: "ledger-db",
                tag: "Gate Blocked",
                tagTone: "amber",
                summary: "Sequential table scan consumes 93% of database connections. Agent's unsafe resize proposal is blocked by safety gate D25; safely falls back to rollback.",
                remediation: "Unsafe pool resize blocked → Rollback dep-ls-0291",
              },
              {
                id: "INC-003",
                title: "Invalid settlement payloads",
                service: "settlement-worker",
                tag: "Multi-Step HITL",
                tagTone: "emerald",
                summary: "Poison messages flood Dead-Letter Queue. Agent formulates 4-step plan with cryptographic human approval for each stage.",
                remediation: "Pause → Rollback → Quarantine → Resume",
              },
              {
                id: "NEG-001",
                title: "Transient latency blip",
                service: "payment-service",
                tag: "No Action Required",
                tagTone: "slate",
                summary: "Brief packet burst cleared before investigation onset. Agent confirms affirmative recovery without modifying infrastructure.",
                remediation: "Confirmed nominal state · 0 mutations",
              },
              {
                id: "NEG-002",
                title: "External FX partner outage",
                service: "forex-gateway",
                tag: "Red-Herring Blocked",
                tagTone: "crimson",
                summary: "Third-party FX provider down. Recent internal deployment is a red herring. Safety gate prevents unauthorized rollback and escalates to SRE.",
                remediation: "Internal rollback blocked → Escalated to operator",
              },
              {
                id: "NEG-003",
                title: "Ambiguous changes & log outage",
                service: "ledger-service",
                tag: "Evidence Gaps",
                tagTone: "crimson",
                summary: "Two candidate deployments with log aggregator down. Insufficient evidence gate triggers to halt automated action.",
                remediation: "Safety gate halts action → Manual investigation",
              },
            ].map((sc) => (
              <div
                key={sc.id}
                className="dossier-paper flex flex-col justify-between p-5 transition-all hover:border-[#C8C4B7] hover:shadow-md"
              >
                <div>
                  <div className="flex items-center justify-between border-b border-[#E2DFD5] pb-2">
                    <span className="exhibit-tag">{sc.id}</span>
                    <span
                      className={`font-mono text-[10px] font-bold uppercase tracking-wider ${
                        sc.tagTone === "emerald"
                          ? "text-[#047857]"
                          : sc.tagTone === "amber"
                          ? "text-[#C05621]"
                          : sc.tagTone === "crimson"
                          ? "text-[#B91C1C]"
                          : "text-[#4A525D]"
                      }`}
                    >
                      {sc.tag}
                    </span>
                  </div>
                  <h4 className="font-serif-heading mt-3 text-base font-bold text-[#16191D]">
                    {sc.title}
                  </h4>
                  <p className="mt-1 font-mono text-[11px] text-[#78828F]">
                    Target Service: <strong>{sc.service}</strong>
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-[#4A525D]">
                    {sc.summary}
                  </p>
                </div>

                <div className="mt-4 border-t border-[#EAE7DF] pt-3">
                  <div className="text-[11px] text-[#78828F]">
                    Expected Resolution:
                    <div className="font-mono text-xs font-semibold text-[#16191D]">{sc.remediation}</div>
                  </div>
                  <Link
                    href={`/prototype/concept-a/workbench?scenario=${sc.id}`}
                    className="mt-3 block w-full rounded border border-[#16191D] bg-[#16191D] py-2 text-center text-xs font-semibold text-white hover:bg-[#333] transition-colors"
                  >
                    Open Forensic Dossier →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Tab 2: Uploaded Evidence Mode */}
        {activeTab === "uploaded" && (
          <div className="dossier-paper p-8">
            <div className="max-w-2xl space-y-4">
              <span className="exhibit-tag">MODE 02: READ-ONLY EVIDENCE AUDIT</span>
              <h3 className="font-serif-heading text-2xl font-bold text-[#16191D]">
                Examine Uploaded Diagnostic Files &amp; Traces
              </h3>
              <p className="text-sm leading-relaxed text-[#4A525D]">
                Drop raw incident logs, CSV metric series, or JSON event traces. OpsPilot parses, deduplicates, and normalizes evidence into an immutable dossier. The local LLM synthesizes root-cause hypotheses citing exact file names and line numbers.
              </p>
              <div className="rounded border-2 border-dashed border-[#C8C4B7] bg-[#FBFBF8] p-8 text-center">
                <div className="font-mono text-xs text-[#78828F]">DRAG &amp; DROP EVIDENCE ARTIFACTS</div>
                <div className="mt-2 font-serif-heading text-base font-semibold text-[#16191D]">
                  incident_20261118_logs.json, metrics.csv, traces.json
                </div>
                <div className="mt-4 flex justify-center gap-3">
                  <Link
                    href="/prototype/concept-a/workbench?mode=uploaded"
                    className="rounded bg-[#C05621] px-4 py-2 text-xs font-semibold text-white hover:bg-[#9c4217]"
                  >
                    Load Sample Forensic Audit Dataset →
                  </Link>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Connected Loki / Prometheus */}
        {activeTab === "connected" && (
          <div className="dossier-paper p-8">
            <div className="max-w-2xl space-y-4">
              <span className="exhibit-tag">MODE 03: LIVE OBSERVABILITY SNAPSHOT</span>
              <h3 className="font-serif-heading text-2xl font-bold text-[#16191D]">
                Audit Telemetry from Grafana Loki &amp; Prometheus
              </h3>
              <p className="text-sm leading-relaxed text-[#4A525D]">
                Execute allowlisted GET-only query templates against live telemetry providers. Captures an immutable snapshot window, attributes evidence to source query stamps, and generates a cited Markdown postmortem. Zero mutating actions are permitted.
              </p>
              <div className="rounded border border-[#E2DFD5] bg-[#F4F3EC] p-4 font-mono text-xs text-[#4A525D]">
                <div className="text-[#047857]">✓ Connected Loki 3.5.0 at 127.0.0.1:3100</div>
                <div className="text-[#047857]">✓ Connected Prometheus v3.5.0 at 127.0.0.1:9090</div>
                <div className="text-[#78828F] mt-2">Approved Templates: HTTP 5xx Rate, Connection Pool Saturation, DLQ Growth</div>
              </div>
              <Link
                href="/prototype/concept-a/workbench?mode=connected"
                className="inline-block rounded bg-[#1E3A8A] px-4 py-2 text-xs font-semibold text-white hover:bg-[#162a63]"
              >
                Inspect Live Telemetry Snapshot →
              </Link>
            </div>
          </div>
        )}
      </section>

      {/* Visual Explanation of the Forensic Architecture */}
      <section className="dossier-paper p-6">
        <h3 className="font-serif-heading text-lg font-bold text-[#16191D] border-b border-[#E2DFD5] pb-3">
          Forensic Workflow &amp; Evidence Custody Pipeline
        </h3>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[
            {
              step: "01",
              title: "Evidence Ingestion",
              desc: "MCP read tools collect logs, metrics, traces, and git diffs. RAG pulls relevant runbooks via pgvector hybrid search.",
            },
            {
              step: "02",
              title: "Hypothesis Formulation",
              desc: "Local Ollama evaluates competing causes with probability scores. Contradictory evidence explicitly reduces confidence.",
            },
            {
              step: "03",
              title: "Deterministic Safety Gate",
              desc: "Pure Python logic intercepts dangerous proposals (e.g. invalid parameter sizing, unverified changes) before execution.",
            },
            {
              step: "04",
              title: "Operator Authorization",
              desc: "Cryptographic human-in-the-loop signing. Multi-step plans are reviewed step by step with zero blind delegation.",
            },
            {
              step: "05",
              title: "Verified Recovery & RCA",
              desc: "Agent checks post-remediation telemetry against baselines before signing the final provenance postmortem.",
            },
          ].map((item) => (
            <div key={item.step} className="rounded border border-[#E2DFD5] bg-[#FBFBF8] p-4">
              <span className="font-mono text-xs font-bold text-[#C05621]">STAGE {item.step}</span>
              <h4 className="mt-1 font-serif-heading text-sm font-bold text-[#16191D]">{item.title}</h4>
              <p className="mt-1.5 text-xs text-[#4A525D] leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
