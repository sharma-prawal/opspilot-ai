"use client";

import { useState } from "react";

export default function ConceptAGuidePage() {
  const [activeSection, setActiveSection] = useState<string>("quickstart");

  return (
    <div className="space-y-6">
      {/* Field Guide Masthead */}
      <div className="dossier-paper p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E2DFD5] pb-3">
          <div>
            <span className="exhibit-tag">EXHIBIT §05: OPERATOR MANUAL</span>
            <h2 className="font-serif-heading mt-1 text-2xl font-bold text-[#16191D]">
              Forensic Field Guide &amp; Operational Protocols
            </h2>
          </div>
          <div className="font-mono text-xs text-[#78828F]">
            MANUAL REVISION: <strong className="text-[#16191D]">v0.7.0 AUDIT EDITION</strong>
          </div>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-[#4A525D]">
          Operational handbook for incident responders and platform engineers deploying OpsPilot AI in localized infrastructure.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Navigation Sidebar (3 cols) */}
        <div className="lg:col-span-3 space-y-2">
          {[
            { id: "quickstart", title: "1. Rapid Bootstrap" },
            { id: "modes", title: "2. Choosing Operating Mode" },
            { id: "models", title: "3. Local Model Setup (Ollama)" },
            { id: "telemetry", title: "4. Connecting Loki/Prometheus" },
            { id: "safety", title: "5. Safety Gates & Fencing" },
          ].map((sec) => (
            <button
              key={sec.id}
              onClick={() => setActiveSection(sec.id)}
              className={`w-full rounded border px-3 py-2 text-left font-mono text-xs transition-colors ${
                activeSection === sec.id
                  ? "border-[#16191D] bg-[#16191D] text-white font-bold"
                  : "border-[#E2DFD5] bg-[#FBFBF8] text-[#4A525D] hover:bg-white"
              }`}
            >
              {sec.title}
            </button>
          ))}
        </div>

        {/* Content Body (9 cols) */}
        <div className="lg:col-span-9 dossier-paper p-6 space-y-6">
          {activeSection === "quickstart" && (
            <div className="space-y-4">
              <h3 className="font-serif-heading text-xl font-bold text-[#16191D] border-b border-[#E2DFD5] pb-2">
                Rapid Bootstrap &amp; Verification
              </h3>
              <p className="text-xs text-[#4A525D] leading-relaxed">
                OpsPilot requires zero external cloud API keys. All inference runs locally on Apple Silicon or Linux GPUs via Ollama.
              </p>

              <div className="space-y-2">
                <div className="font-mono text-xs font-bold text-[#16191D]">1. Install system prerequisites</div>
                <pre className="rounded border border-[#E2DFD5] bg-[#F4F3EC] p-3 font-mono text-xs text-[#16191D]">
                  brew install ollama colima docker docker-compose{`\n`}
                  brew services start ollama{`\n`}
                  ollama pull qwen3:8b{`\n`}
                  ollama pull qwen3-embedding:0.6b
                </pre>
              </div>

              <div className="space-y-2">
                <div className="font-mono text-xs font-bold text-[#16191D]">2. Initialize environment &amp; run doctor check</div>
                <pre className="rounded border border-[#E2DFD5] bg-[#F4F3EC] p-3 font-mono text-xs text-[#16191D]">
                  make bootstrap{`\n`}
                  make doctor
                </pre>
              </div>

              <div className="space-y-2">
                <div className="font-mono text-xs font-bold text-[#16191D]">3. Launch local services</div>
                <pre className="rounded border border-[#E2DFD5] bg-[#F4F3EC] p-3 font-mono text-xs text-[#16191D]">
                  make dev
                </pre>
                <p className="text-[11px] text-[#78828F]">
                  FastAPI backend opens at <code>http://127.0.0.1:8000</code>; Next.js frontend at <code>http://127.0.0.1:3000</code>.
                </p>
              </div>
            </div>
          )}

          {activeSection === "modes" && (
            <div className="space-y-4">
              <h3 className="font-serif-heading text-xl font-bold text-[#16191D] border-b border-[#E2DFD5] pb-2">
                Choosing an Operating Mode
              </h3>
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="rounded border border-[#E2DFD5] bg-[#FBFBF8] p-4 text-xs">
                  <span className="exhibit-tag">MODE 01</span>
                  <h4 className="mt-2 font-serif-heading font-bold text-[#16191D]">Simulator &amp; Sandboxed HITL</h4>
                  <p className="mt-1 text-[#4A525D]">
                    Six built-in failure scenarios. Evaluates full loop: triage, multi-hypothesis formulation, safety gates, authenticated operator approval, and containerized remediation execution.
                  </p>
                </div>
                <div className="rounded border border-[#E2DFD5] bg-[#FBFBF8] p-4 text-xs">
                  <span className="exhibit-tag">MODE 02</span>
                  <h4 className="mt-2 font-serif-heading font-bold text-[#16191D]">Uploaded Evidence Audit</h4>
                  <p className="mt-1 text-[#4A525D]">
                    Upload raw JSON/CSV incident files. Strictly read-only analysis. Agent indexes exhibits and generates cited Markdown postmortems without running infrastructure actions.
                  </p>
                </div>
                <div className="rounded border border-[#E2DFD5] bg-[#FBFBF8] p-4 text-xs">
                  <span className="exhibit-tag">MODE 03</span>
                  <h4 className="mt-2 font-serif-heading font-bold text-[#16191D]">Connected Loki/Prometheus</h4>
                  <p className="mt-1 text-[#4A525D]">
                    Pulls live telemetry snapshots using GET-only templates. Preserves exact query provenance while strictly blocking any state mutation on connected infrastructure.
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeSection === "models" && (
            <div className="space-y-4">
              <h3 className="font-serif-heading text-xl font-bold text-[#16191D] border-b border-[#E2DFD5] pb-2">
                Local Model Configuration
              </h3>
              <p className="text-xs text-[#4A525D]">
                OpsPilot supports any local model via Ollama. By default, <code>qwen3:8b</code> is utilized for structured reasoning and <code>qwen3-embedding:0.6b</code> (1024 dims) for pgvector hybrid RAG.
              </p>
              <pre className="rounded border border-[#E2DFD5] bg-[#F4F3EC] p-3 font-mono text-xs text-[#16191D]">
                # .env configuration{`\n`}
                OLLAMA_BASE_URL=http://127.0.0.1:11434{`\n`}
                LLM_MODEL=qwen3:8b{`\n`}
                EMBEDDING_MODEL=qwen3-embedding:0.6b{`\n`}
                EMBEDDING_DIMENSIONS=1024
              </pre>
            </div>
          )}

          {activeSection === "telemetry" && (
            <div className="space-y-4">
              <h3 className="font-serif-heading text-xl font-bold text-[#16191D] border-b border-[#E2DFD5] pb-2">
                Telemetry Connectors (Loki &amp; Prometheus)
              </h3>
              <p className="text-xs text-[#4A525D]">
                Launch the local telemetry test profile containing Grafana Loki 3.5.0 and Prometheus v3.5.0 seeded with synthetic metrics:
              </p>
              <pre className="rounded border border-[#E2DFD5] bg-[#F4F3EC] p-3 font-mono text-xs text-[#16191D]">
                make telemetry-up{`\n`}
                python scripts/generate_telemetry.py{`\n`}
                make telemetry-down
              </pre>
            </div>
          )}

          {activeSection === "safety" && (
            <div className="space-y-4">
              <h3 className="font-serif-heading text-xl font-bold text-[#16191D] border-b border-[#E2DFD5] pb-2">
                Deterministic Safety Gates &amp; HITL Fencing
              </h3>
              <p className="text-xs text-[#4A525D]">
                Safety is not an LLM prompt. Pure Python logic verifies preconditions before any action token is generated:
              </p>
              <ul className="list-disc pl-4 text-xs text-[#4A525D] space-y-1">
                <li><strong>D25:</strong> Database connection pool resizes capped at hardware RAM maximum.</li>
                <li><strong>D26:</strong> Deployments older than 24 hours cannot be rolled back autonomously.</li>
                <li><strong>D28:</strong> Poison message isolation must move messages to quarantine, never discard.</li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
