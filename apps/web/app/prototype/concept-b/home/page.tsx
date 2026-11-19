"use client";

import Link from "next/link";
import { useState } from "react";

export default function ConceptBHomePage() {
  const [selectedChannel, setSelectedChannel] = useState<"simulator" | "uploaded" | "connected">("simulator");

  return (
    <div className="space-y-6">
      {/* Cockpit Status Banner & Telemetry Readout */}
      <div className="avionics-frame p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between border-b border-[#232A35] pb-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2 font-mono text-[11px] text-[#8B97A8]">
              <span className="size-2 rounded-full bg-[#F59E0B] animate-pulse" />
              <span>BLACK-BOX TELEMETRY DISPATCH</span>
              <span>{"//"}</span>
              <span className="text-[#06B6D4]">SYS_STATUS: ARMED</span>
            </div>
            <h2 className="font-mono text-xl font-bold tracking-tight text-white sm:text-2xl">
              MISSION CONTROL // INCIDENT FLIGHT DECK
            </h2>
            <p className="max-w-2xl text-xs text-[#8B97A8] leading-relaxed">
              Continuous operational telemetry recording, automated failure anomaly attribution, and cryptographic human authorization for high-stakes distributed systems.
            </p>
          </div>

          {/* Real-time Telemetry Gauges */}
          <div className="grid grid-cols-3 gap-2 font-mono text-center">
            <div className="rounded border border-[#232A35] bg-[#181D24] p-2.5">
              <div className="text-[10px] text-[#8B97A8]">SIM RUNS</div>
              <div className="text-base font-bold text-[#F0F3F6]">6 ACTIVE</div>
            </div>
            <div className="rounded border border-[#232A35] bg-[#181D24] p-2.5">
              <div className="text-[10px] text-[#8B97A8]">GATE INTERCEPT</div>
              <div className="text-base font-bold text-[#10B981]">0 BREACH</div>
            </div>
            <div className="rounded border border-[#232A35] bg-[#181D24] p-2.5">
              <div className="text-[10px] text-[#8B97A8]">INFERENCE</div>
              <div className="text-base font-bold text-[#06B6D4]">LOCAL 100%</div>
            </div>
          </div>
        </div>

        {/* Telemetry Flight Tape Scrubber Strip */}
        <div className="mt-4 border-t border-[#232A35] pt-3">
          <div className="flex items-center justify-between font-mono text-[10px] text-[#8B97A8] mb-1.5">
            <span>FLIGHT DATA RECORDER TIME RIBBON</span>
            <span className="text-[#F59E0B]">CRITICAL INCIDENT WINDOW: T-02:00 → T+01:30</span>
          </div>
          <div className="relative h-6 w-full rounded border border-[#232A35] bg-[#0A0C0E] flex items-center px-2 font-mono text-[10px]">
            <div className="absolute inset-y-0 left-[25%] w-0.5 bg-[#F59E0B]" />
            <div className="absolute inset-y-0 left-[25%] -top-1 font-bold text-[#F59E0B] text-[9px] translate-x-1">
              FAULT INJECTION (T+00:00)
            </div>
            <div className="absolute inset-y-0 left-[55%] w-0.5 bg-[#EF4444]" />
            <div className="absolute inset-y-0 left-[55%] -top-1 font-bold text-[#EF4444] text-[9px] translate-x-1">
              GATE INTERCEPT (T+00:25)
            </div>
            <div className="absolute inset-y-0 left-[85%] w-0.5 bg-[#10B981]" />
            <div className="absolute inset-y-0 left-[85%] -top-1 font-bold text-[#10B981] text-[9px] translate-x-1">
              RECOVERY (T+00:52)
            </div>
            <div className="w-full flex justify-between text-[#525D6D] text-[9px]">
              <span>T-02:00</span>
              <span>T-01:00</span>
              <span>T+00:00</span>
              <span>T+00:30</span>
              <span>T+01:00</span>
              <span>T+01:30</span>
            </div>
          </div>
        </div>
      </div>

      {/* Investigation Entry Pathways (3 Modes) */}
      <div className="avionics-frame p-5 space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#232A35] pb-3">
          <div>
            <h3 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
              TELEMETRY INTAKE BUS // SELECT RECORDING CHANNEL
            </h3>
            <p className="text-[11px] text-[#8B97A8]">
              Switch between simulator fault injection, black-box file ingestion, or live Prometheus/Loki telemetry.
            </p>
          </div>

          <div className="flex rounded border border-[#232A35] bg-[#181D24] p-0.5 font-mono text-xs">
            <button
              onClick={() => setSelectedChannel("simulator")}
              className={`rounded px-3 py-1 transition-all ${
                selectedChannel === "simulator"
                  ? "bg-[#F59E0B] text-black font-bold shadow-xs"
                  : "text-[#8B97A8] hover:text-white"
              }`}
            >
              [CH-A] SIMULATOR MISSIONS (6)
            </button>
            <button
              onClick={() => setSelectedChannel("uploaded")}
              className={`rounded px-3 py-1 transition-all ${
                selectedChannel === "uploaded"
                  ? "bg-[#06B6D4] text-black font-bold shadow-xs"
                  : "text-[#8B97A8] hover:text-white"
              }`}
            >
              [CH-B] BLACK-BOX UPLOADS
            </button>
            <button
              onClick={() => setSelectedChannel("connected")}
              className={`rounded px-3 py-1 transition-all ${
                selectedChannel === "connected"
                  ? "bg-[#10B981] text-black font-bold shadow-xs"
                  : "text-[#8B97A8] hover:text-white"
              }`}
            >
              [CH-C] CONNECTED LOKI/PROM
            </button>
          </div>
        </div>

        {/* Channel A: Flight Missions */}
        {selectedChannel === "simulator" && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                id: "INC-002",
                title: "Connection Pool Exhaustion & Safety Gate Block",
                service: "ledger-db",
                status: "SAFETY GATE BLOCKED",
                tone: "amber",
                summary: "Sequential table scan consumes 93% of database pool. Agent's unsafe resize proposal is blocked by safety gate D25; safely falls back to rollback.",
                resolution: "Unsafe scale_connection_pool blocked → Rollback dep-ls-0291",
              },
              {
                id: "INC-003",
                title: "Invalid Settlement Payloads Flooding DLQ",
                service: "settlement-worker",
                status: "MULTI-STEP HITL",
                tone: "green",
                summary: "Poison messages flood Dead-Letter Queue due to schema drift. 4-step remediation executed with step-by-step cryptographic approval.",
                resolution: "Pause → Rollback → Quarantine → Resume",
              },
              {
                id: "INC-001",
                title: "Incompatible Schema Migration",
                service: "transaction-api",
                status: "MITIGATED",
                tone: "green",
                summary: "HTTP 500 spike after column rename in ledger-service. Agent attributes root cause to dep-ls-0042 and verifies post-rollback recovery.",
                resolution: "Rollback dep-ls-0042 → Verified Recovery",
              },
              {
                id: "NEG-002",
                title: "External FX Outage & Red-Herring Deploy",
                service: "forex-gateway",
                status: "ESCALATED (NO ACTION)",
                tone: "red",
                summary: "Third-party FX provider down. Recent internal deployment is a red herring. Safety gate prevents unauthorized rollback and escalates to human SRE.",
                resolution: "Red-herring rollback blocked → Zero mutations",
              },
              {
                id: "NEG-001",
                title: "Transient Latency Blip",
                service: "payment-service",
                status: "NO ACTION REQUIRED",
                tone: "cyan",
                summary: "Brief packet burst cleared before investigation onset. Agent confirms affirmative recovery without modifying infrastructure.",
                resolution: "Confirmed nominal state · 0 actions",
              },
              {
                id: "NEG-003",
                title: "Ambiguous Changes & Log Aggregator Outage",
                service: "ledger-service",
                status: "EVIDENCE GAPS HALT",
                tone: "red",
                summary: "Two candidate deployments with log aggregator down. Insufficient evidence gate triggers to halt automated action.",
                resolution: "Safety gate halts action → Manual investigation",
              },
            ].map((m) => (
              <div
                key={m.id}
                className="rounded border border-[#232A35] bg-[#111419] p-4 flex flex-col justify-between hover:border-[#3B4657] transition-all"
              >
                <div>
                  <div className="flex items-center justify-between border-b border-[#232A35] pb-2 text-[10px] font-mono">
                    <span className="font-bold text-[#F59E0B]">[{m.id}]</span>
                    <span
                      className={`font-bold ${
                        m.tone === "amber"
                          ? "text-[#F59E0B]"
                          : m.tone === "green"
                          ? "text-[#10B981]"
                          : m.tone === "red"
                          ? "text-[#EF4444]"
                          : "text-[#06B6D4]"
                      }`}
                    >
                      {m.status}
                    </span>
                  </div>
                  <h4 className="mt-2 font-mono text-xs font-bold text-white">
                    {m.title}
                  </h4>
                  <div className="mt-1 font-mono text-[10px] text-[#8B97A8]">
                    TARGET_BUS: <strong>{m.service}</strong>
                  </div>
                  <p className="mt-2 text-[11px] text-[#8B97A8] leading-relaxed">
                    {m.summary}
                  </p>
                </div>

                <div className="mt-4 border-t border-[#232A35] pt-3">
                  <div className="font-mono text-[10px] text-[#525D6D]">
                    RESOLUTION_TARGET:
                    <div className="text-[#F0F3F6] font-semibold">{m.resolution}</div>
                  </div>
                  <Link
                    href={`/prototype/concept-b/workbench?scenario=${m.id}`}
                    className="mt-3 block w-full rounded border border-[#F59E0B] bg-[#F59E0B]/10 py-1.5 text-center font-mono text-xs font-bold text-[#F59E0B] hover:bg-[#F59E0B] hover:text-black transition-colors"
                  >
                    ENGAGE FLIGHT RECORDER →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Channel B: Uploads */}
        {selectedChannel === "uploaded" && (
          <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-6 text-center space-y-3 font-mono">
            <span className="annunciator-pill border border-[#06B6D4] bg-[#06B6D4]/10 text-[#06B6D4]">
              CHANNEL B: OFFLINE BLACK-BOX CRASH DUMP
            </span>
            <h4 className="text-sm font-bold text-white">Ingest Logs, Metrics CSV, or Distributed Traces</h4>
            <p className="text-xs text-[#8B97A8] max-w-lg mx-auto leading-relaxed">
              Drop recorded flight data files. Ingestion normalizes time-series arrays and correlates crash traces offline. Zero telemetry emissions or real mutations.
            </p>
            <Link
              href="/prototype/concept-b/workbench?mode=uploaded"
              className="inline-block rounded border border-[#06B6D4] bg-[#06B6D4] px-4 py-2 text-xs font-bold text-black hover:bg-[#06B6D4]/80"
            >
              Analyze Uploaded Black-Box Data →
            </Link>
          </div>
        )}

        {/* Channel C: Connected */}
        {selectedChannel === "connected" && (
          <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-6 text-center space-y-3 font-mono">
            <span className="annunciator-pill border border-[#10B981] bg-[#10B981]/10 text-[#10B981]">
              CHANNEL C: LIVE TELEMETRY BUS (READ-ONLY)
            </span>
            <h4 className="text-sm font-bold text-white">Grafana Loki &amp; Prometheus Telemetry Stream</h4>
            <p className="text-xs text-[#8B97A8] max-w-lg mx-auto leading-relaxed">
              Synchronize live metrics and structured log streams over local sockets (Loki 3.5.0:3100, Prometheus v3.5.0:9090). Strict GET-only allowlist ensures complete infrastructure immunity.
            </p>
            <Link
              href="/prototype/concept-b/workbench?mode=connected"
              className="inline-block rounded border border-[#10B981] bg-[#10B981] px-4 py-2 text-xs font-bold text-black hover:bg-[#10B981]/80"
            >
              Connect to Live Telemetry Stream →
            </Link>
          </div>
        )}
      </div>

      {/* 4-Channel Structural Telemetry Blueprint */}
      <div className="avionics-frame p-5">
        <div className="avionics-header mb-4">
          <span>OPERATIONAL ARCHITECTURE // 4-CHANNEL ISOLATION</span>
          <span>STRICT UNIDIRECTIONAL BUS</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 font-mono text-xs">
          <div className="rounded border border-[#232A35] bg-[#111419] p-3.5">
            <span className="text-[10px] font-bold text-[#06B6D4]">[CH-01: SENSOR INGEST]</span>
            <h4 className="mt-1 font-bold text-white">Passive Telemetry</h4>
            <p className="mt-1.5 text-[11px] text-[#8B97A8] leading-relaxed">
              Read-only MCP tools collect metrics, structured logs, and git diffs. Ingests without mutating target environment.
            </p>
          </div>
          <div className="rounded border border-[#232A35] bg-[#111419] p-3.5">
            <span className="text-[10px] font-bold text-[#A855F7]">[CH-02: ANALYTICS]</span>
            <h4 className="mt-1 font-bold text-white">Local LLM Reasoning</h4>
            <p className="mt-1.5 text-[11px] text-[#8B97A8] leading-relaxed">
              Local LLM StateGraph formulates ranked hypotheses. Cross-checks against pgvector runbook embeddings.
            </p>
          </div>
          <div className="rounded border border-[#232A35] bg-[#111419] p-3.5">
            <span className="text-[10px] font-bold text-[#EF4444]">[CH-03: SAFETY KERNEL]</span>
            <h4 className="mt-1 font-bold text-white">Deterministic Gates</h4>
            <p className="mt-1.5 text-[11px] text-[#8B97A8] leading-relaxed">
              Pure Python rules intercept dangerous sizing, stale rollbacks, or unsafe queue discard commands before execution.
            </p>
          </div>
          <div className="rounded border border-[#232A35] bg-[#111419] p-3.5">
            <span className="text-[10px] font-bold text-[#10B981]">[CH-04: ACTUATOR]</span>
            <h4 className="mt-1 font-bold text-white">Human-Signed Dispatch</h4>
            <p className="mt-1.5 text-[11px] text-[#8B97A8] leading-relaxed">
              Requires valid cryptographic operator token. Multi-step plans execute inside sandboxed container scopes.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
