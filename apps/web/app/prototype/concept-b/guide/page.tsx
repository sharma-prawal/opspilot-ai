"use client";

import { useState } from "react";

export default function ConceptBGuidePage() {
  const [activeChecklist, setActiveChecklist] = useState<string>("bootstrap");

  return (
    <div className="space-y-4 font-mono">
      {/* Console Masthead */}
      <div className="avionics-frame p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#232A35] pb-2">
          <div>
            <div className="text-[10px] text-[#F59E0B] font-bold">
              FLIGHT OPERATIONS MANUAL // PRE-FLIGHT CHECKLIST
            </div>
            <h2 className="text-base font-bold text-white">
              Incident Mission Control Operations Manual
            </h2>
          </div>
          <div className="text-[10px] text-[#8B97A8]">
            REVISION: <span className="text-white font-bold">v0.7.0 INSTRUMENTATION</span>
          </div>
        </div>
        <p className="mt-1 text-xs text-[#8B97A8]">
          Pre-flight procedures and configuration instructions for deploying OpsPilot AI on isolated engineering infrastructure.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        {/* Checklist Index (3 cols) */}
        <div className="lg:col-span-3 space-y-1.5">
          {[
            { id: "bootstrap", label: "[01] PRE-FLIGHT BOOTSTRAP" },
            { id: "modes", label: "[02] CHANNEL FLIGHT MODES" },
            { id: "models", label: "[03] LOCAL OLLAMA TELEMETRY" },
            { id: "connectors", label: "[04] LOKI/PROM SOCKETS" },
            { id: "safety", label: "[05] SAFETY KERNEL GATES" },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveChecklist(item.id)}
              className={`w-full rounded border px-3 py-2 text-left text-xs transition-colors ${
                activeChecklist === item.id
                  ? "border-[#F59E0B] bg-[#F59E0B] text-black font-bold"
                  : "border-[#232A35] bg-[#111419] text-[#8B97A8] hover:text-white"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Checklist Content (9 cols) */}
        <div className="lg:col-span-9 avionics-frame p-5 space-y-4 text-xs">
          {activeChecklist === "bootstrap" && (
            <div className="space-y-3">
              <div className="text-sm font-bold text-white border-b border-[#232A35] pb-2">
                CHECKLIST 01 // SYSTEM PREPARATION &amp; DOCTOR VERIFICATION
              </div>
              <p className="text-[#8B97A8] leading-relaxed">
                Zero paid cloud inference. Ensure local Colima Docker socket and Ollama daemon are armed:
              </p>
              <div className="space-y-1">
                <span className="text-[10px] text-[#525D6D]">1. PULL LOCAL REASONING &amp; EMBEDDING MODELS</span>
                <pre className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 text-[#F0F3F6]">
                  brew install ollama colima docker docker-compose{`\n`}
                  ollama pull qwen3:8b{`\n`}
                  ollama pull qwen3-embedding:0.6b
                </pre>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] text-[#525D6D]">2. RUN PRE-FLIGHT DOCTOR INSPECTION</span>
                <pre className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 text-[#F0F3F6]">
                  make bootstrap &amp;&amp; make doctor
                </pre>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] text-[#525D6D]">3. ENGAGE MISSION CONTROL DAEMONS</span>
                <pre className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 text-[#10B981]">
                  make dev
                </pre>
              </div>
            </div>
          )}

          {activeChecklist === "modes" && (
            <div className="space-y-3">
              <div className="text-sm font-bold text-white border-b border-[#232A35] pb-2">
                CHECKLIST 02 // THREE FLIGHT MODES
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 space-y-1">
                  <span className="text-[10px] font-bold text-[#F59E0B]">CHANNEL A</span>
                  <div className="font-bold text-white">Simulator &amp; Sandboxed HITL</div>
                  <p className="text-[10px] text-[#8B97A8]">
                    Six built-in scenarios. Validates automated triage, multi-hypothesis reasoning, safety gate blocks, and containerized rollback execution.
                  </p>
                </div>
                <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 space-y-1">
                  <span className="text-[10px] font-bold text-[#06B6D4]">CHANNEL B</span>
                  <div className="font-bold text-white">Black-Box File Uploads</div>
                  <p className="text-[10px] text-[#8B97A8]">
                    Upload raw incident logs, CSV metrics, and JSON traces. Strictly read-only offline synthesis. Zero mutating commands.
                  </p>
                </div>
                <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 space-y-1">
                  <span className="text-[10px] font-bold text-[#10B981]">CHANNEL C</span>
                  <div className="font-bold text-white">Connected Loki / Prometheus</div>
                  <p className="text-[10px] text-[#8B97A8]">
                    Ingests live snapshots via allowlisted GET-only query templates. Attributed provenance with 100% infrastructure protection.
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeChecklist === "models" && (
            <div className="space-y-3">
              <div className="text-sm font-bold text-white border-b border-[#232A35] pb-2">
                CHECKLIST 03 // LOCAL OLLAMA TELEMETRY CONFIGURATION
              </div>
              <p className="text-[#8B97A8]">
                Configure local inference endpoints in <code>.env</code>. OpsPilot connects to 127.0.0.1:11434 with zero external telemetry transmission:
              </p>
              <pre className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 text-[#06B6D4]">
                OLLAMA_BASE_URL=http://127.0.0.1:11434{`\n`}
                LLM_MODEL=qwen3:8b{`\n`}
                EMBEDDING_MODEL=qwen3-embedding:0.6b{`\n`}
                EMBEDDING_DIMENSIONS=1024
              </pre>
            </div>
          )}

          {activeChecklist === "connectors" && (
            <div className="space-y-3">
              <div className="text-sm font-bold text-white border-b border-[#232A35] pb-2">
                CHECKLIST 04 // LIVE TELEMETRY BUS (LOKI &amp; PROMETHEUS)
              </div>
              <p className="text-[#8B97A8]">
                Spin up isolated local telemetry containers (Loki 3.5.0 and Prometheus v3.5.0):
              </p>
              <pre className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 text-[#10B981]">
                make telemetry-up{`\n`}
                python scripts/generate_telemetry.py{`\n`}
                make telemetry-down
              </pre>
            </div>
          )}

          {activeChecklist === "safety" && (
            <div className="space-y-3">
              <div className="text-sm font-bold text-white border-b border-[#232A35] pb-2">
                CHECKLIST 05 // DETERMINISTIC SAFETY GATE ENGINE
              </div>
              <p className="text-[#8B97A8]">
                Deterministic Python rules execute prior to operator lease generation:
              </p>
              <ul className="list-disc pl-4 text-[#8B97A8] space-y-1">
                <li><strong className="text-white">RULE D25:</strong> Database connection pool resizing capped at physical container memory limits.</li>
                <li><strong className="text-white">RULE D26:</strong> Deployments older than 24 hours cannot be rolled back autonomously.</li>
                <li><strong className="text-white">RULE D28:</strong> DLQ message quarantine must preserve payloads, never drop.</li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
