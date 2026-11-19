"use client";

import { useState } from "react";

interface CausalNode {
  id: string;
  category: "onset" | "anomaly" | "dependency" | "deployment" | "hypothesis" | "gate" | "action";
  label: string;
  sublabel: string;
  status: "confirmed" | "refuted" | "uncertain" | "verified";
  confidence?: number;
  exhibits: string[];
  uncertaintyNotes?: string;
  details: string;
}

const CAUSAL_NODES: CausalNode[] = [
  {
    id: "NODE-01",
    category: "deployment",
    label: "dep-sw-0819 Promoted",
    sublabel: "settlement-worker v2.14.0",
    status: "confirmed",
    confidence: 1.0,
    exhibits: ["EVID-C01", "git:011853f"],
    details: "Released 92s prior to incident onset. Added mandatory 'vat_code' parameter validation without DB schema fallback.",
  },
  {
    id: "NODE-02",
    category: "onset",
    label: "DLQ Message Explosion",
    sublabel: "1,420 errors in 180s",
    status: "confirmed",
    confidence: 0.99,
    exhibits: ["EVID-M01", "prom:rabbitmq_dlq"],
    details: "Ingress breached 50 msgs/s threshold. Worker thread pool stalled on unhandled deserialization exception.",
  },
  {
    id: "NODE-03",
    category: "dependency",
    label: "Upstream transaction-api Ingress",
    sublabel: "Payload Format Drift",
    status: "confirmed",
    confidence: 0.94,
    exhibits: ["EVID-L01", "logs#L4812"],
    details: "Legacy transaction producer emitted payloads lacking 'vat_code', triggering immediate consumer parsing crash.",
  },
  {
    id: "NODE-04",
    category: "hypothesis",
    label: "Hypothesis A: Backward Incompatible Validation Drift",
    sublabel: "Rank #1 (Primary Cause)",
    status: "confirmed",
    confidence: 0.96,
    exhibits: ["EVID-C01", "EVID-L01", "RB-SETTLE-004"],
    details: "Strict deserialization on unmigrated historical stream caused poison head-of-line blocking.",
  },
  {
    id: "NODE-05",
    category: "hypothesis",
    label: "Hypothesis B: RabbitMQ Cluster Network Split",
    sublabel: "Rank #2 (Refuted Red-Herring)",
    status: "refuted",
    confidence: 0.08,
    exhibits: ["EVID-M02"],
    uncertaintyNotes: "Uncertainty resolved: Broker heartbeat was never lost; broker logs confirm steady TCP connections.",
    details: "Broker cluster gossip protocols were nominal throughout the entire incident window.",
  },
  {
    id: "NODE-06",
    category: "gate",
    label: "Deterministic Safety Gate D28",
    sublabel: "Non-Destructive Quarantine Rule",
    status: "verified",
    confidence: 1.0,
    exhibits: ["GATE-01", "D28_SPEC"],
    details: "Deterministic check blocked automated message purge, enforcing safe quarantine to preserve all 1,420 transactions.",
  },
  {
    id: "NODE-07",
    category: "action",
    label: "4-Step Sandboxed HITL Remediation",
    sublabel: "Verified Recovery Confirmed",
    status: "verified",
    confidence: 1.0,
    exhibits: ["EVID-M01-POST", "AUTH_TOKEN_9F"],
    details: "Consumer paused → dep-sw-0818 rolled back → DLQ quarantined → consumer resumed. Zero data loss.",
  },
];

export default function ConceptAExplorerPage() {
  const [selectedNode, setSelectedNode] = useState<CausalNode>(CAUSAL_NODES[3]);

  return (
    <div className="space-y-6">
      {/* Explorer Masthead */}
      <div className="dossier-paper p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E2DFD5] pb-3">
          <div>
            <span className="exhibit-tag">EXHIBIT §03: CAUSAL GRAPH ANALYSIS</span>
            <h2 className="font-serif-heading mt-1 text-2xl font-bold text-[#16191D]">
              Evidence &amp; Causal Correlation Tree
            </h2>
          </div>
          <div className="font-mono text-xs text-[#78828F]">
            GRAPH KERNEL: <strong className="text-[#16191D]">EVIDENCE-GROUNDED STATEGRAPH</strong>
          </div>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-[#4A525D]">
          Trace the causal pathway from deployment trigger to telemetry anomalies, competing hypotheses, deterministic safety gates, and verified recovery. Select any node to inspect its supporting exhibits and uncertainty bounds.
        </p>
      </div>

      {/* Main Causal Graph Canvas & Detail Panel */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* Interactive Causal Flow Visualizer (8 cols) */}
        <div className="lg:col-span-8 dossier-paper p-6">
          <div className="flex items-center justify-between border-b border-[#E2DFD5] pb-2 text-xs font-mono text-[#78828F]">
            <span>CAUSAL GRAPH TOPOLOGY</span>
            <span>CHRONOLOGICAL PROPAGATION →</span>
          </div>

          <div className="mt-6 space-y-6">
            {/* Step 1: Upstream Root & Trigger */}
            <div>
              <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#78828F]">
                1. ROOT TRIGGER &amp; DEPLOYMENT
              </div>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                {[CAUSAL_NODES[0], CAUSAL_NODES[2]].map((node) => {
                  const isSel = selectedNode.id === node.id;
                  return (
                    <div
                      key={node.id}
                      onClick={() => setSelectedNode(node)}
                      className={`cursor-pointer rounded border p-3.5 transition-all ${
                        isSel
                          ? "border-[#C05621] bg-[#FFFBF5] shadow-xs"
                          : "border-[#E2DFD5] bg-[#FBFBF8] hover:bg-white"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="exhibit-tag">{node.id}</span>
                        <span className="font-mono text-[10px] font-bold text-[#047857]">CONFIRMED</span>
                      </div>
                      <h4 className="mt-2 font-serif-heading text-xs font-bold text-[#16191D]">
                        {node.label}
                      </h4>
                      <p className="mt-1 font-mono text-[11px] text-[#78828F]">{node.sublabel}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Downward Connector Arrow */}
            <div className="flex justify-center">
              <span className="font-mono text-xs text-[#C8C4B7]">↓ correlated with anomaly onset (Δt = 92s) ↓</span>
            </div>

            {/* Step 2: Telemetry Onset */}
            <div>
              <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#78828F]">
                2. OBSERVED TELEMETRY ANOMALY
              </div>
              <div className="mt-2">
                {[CAUSAL_NODES[1]].map((node) => {
                  const isSel = selectedNode.id === node.id;
                  return (
                    <div
                      key={node.id}
                      onClick={() => setSelectedNode(node)}
                      className={`cursor-pointer rounded border p-4 transition-all ${
                        isSel
                          ? "border-[#B91C1C] bg-[#FFF5F5] shadow-xs"
                          : "border-[#B91C1C]/40 bg-[#FEE2E2]/20 hover:bg-white"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="exhibit-tag">{node.id}</span>
                        <span className="font-mono text-[10px] font-bold text-[#B91C1C]">BREACHED THRESHOLD</span>
                      </div>
                      <h4 className="mt-2 font-serif-heading text-sm font-bold text-[#16191D]">
                        {node.label}
                      </h4>
                      <p className="mt-1 text-xs text-[#4A525D]">{node.details}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Downward Connector Arrow */}
            <div className="flex justify-center">
              <span className="font-mono text-xs text-[#C8C4B7]">↓ LLM hypothesis formulation with evidence citation ↓</span>
            </div>

            {/* Step 3: Competing Hypotheses */}
            <div>
              <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#78828F]">
                3. COMPETING CAUSAL HYPOTHESES &amp; UNCERTAINTY
              </div>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                {[CAUSAL_NODES[3], CAUSAL_NODES[4]].map((node) => {
                  const isSel = selectedNode.id === node.id;
                  const isConfirmed = node.status === "confirmed";
                  return (
                    <div
                      key={node.id}
                      onClick={() => setSelectedNode(node)}
                      className={`cursor-pointer rounded border p-3.5 transition-all ${
                        isSel
                          ? isConfirmed
                            ? "border-[#C05621] bg-[#FFFBF5] shadow-xs"
                            : "border-[#78828F] bg-[#F4F3EC] shadow-xs"
                          : "border-[#E2DFD5] bg-[#FBFBF8] hover:bg-white"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="exhibit-tag">{node.id}</span>
                        <span
                          className={`font-mono text-[10px] font-bold ${
                            isConfirmed ? "text-[#047857]" : "text-[#78828F] line-through"
                          }`}
                        >
                          {isConfirmed ? "PROVEN 96%" : "REFUTED 8%"}
                        </span>
                      </div>
                      <h4 className="mt-2 font-serif-heading text-xs font-bold text-[#16191D]">
                        {node.label}
                      </h4>
                      <p className="mt-1 text-xs text-[#4A525D]">{node.sublabel}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Downward Connector Arrow */}
            <div className="flex justify-center">
              <span className="font-mono text-xs text-[#C8C4B7]">↓ deterministic gate validation &amp; safe execution ↓</span>
            </div>

            {/* Step 4: Safety Gate & Resolution */}
            <div>
              <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#78828F]">
                4. DETERMINISTIC SAFETY GATE &amp; RECOVERY
              </div>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                {[CAUSAL_NODES[5], CAUSAL_NODES[6]].map((node) => {
                  const isSel = selectedNode.id === node.id;
                  return (
                    <div
                      key={node.id}
                      onClick={() => setSelectedNode(node)}
                      className={`cursor-pointer rounded border p-3.5 transition-all ${
                        isSel
                          ? "border-[#047857] bg-[#F0FDF4] shadow-xs"
                          : "border-[#E2DFD5] bg-[#FBFBF8] hover:bg-white"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="exhibit-tag">{node.id}</span>
                        <span className="font-mono text-[10px] font-bold text-[#047857]">GATES GREEN</span>
                      </div>
                      <h4 className="mt-2 font-serif-heading text-xs font-bold text-[#16191D]">
                        {node.label}
                      </h4>
                      <p className="mt-1 text-xs text-[#4A525D]">{node.sublabel}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Selected Node Exhibit Inspection Dossier (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="dossier-paper p-5">
            <span className="exhibit-tag">NODE EXHIBIT DOSSIER</span>
            <h3 className="font-serif-heading mt-2 text-lg font-bold text-[#16191D]">
              {selectedNode.label}
            </h3>
            <p className="font-mono text-xs text-[#78828F]">{selectedNode.sublabel}</p>

            <div className="mt-4 border-t border-[#E2DFD5] pt-3 text-xs space-y-3">
              <div>
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Causal Analysis &amp; Findings:
                </span>
                <p className="mt-1 text-xs text-[#4A525D] leading-relaxed">
                  {selectedNode.details}
                </p>
              </div>

              {selectedNode.uncertaintyNotes && (
                <div className="rounded border border-[#C8C4B7] bg-[#F4F3EC] p-3 text-xs">
                  <span className="font-mono text-[10px] font-bold uppercase text-[#C05621]">
                    Uncertainty Bounds Audit:
                  </span>
                  <p className="mt-1 text-[11px] text-[#4A525D]">
                    {selectedNode.uncertaintyNotes}
                  </p>
                </div>
              )}

              <div>
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Supporting Artifact Exhibits:
                </span>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {selectedNode.exhibits.map((ex) => (
                    <span
                      key={ex}
                      className="rounded border border-[#C8C4B7] bg-[#F4F3EC] px-2 py-0.5 font-mono text-[11px] font-bold text-[#16191D]"
                    >
                      {ex}
                    </span>
                  ))}
                </div>
              </div>

              <div className="border-t border-[#EAE7DF] pt-3">
                <span className="font-mono text-[10px] font-bold uppercase text-[#78828F]">
                  Classification Status:
                </span>
                <div className="mt-1 font-mono text-xs font-bold text-[#047857]">
                  {selectedNode.status.toUpperCase()}
                  {selectedNode.confidence ? ` (${(selectedNode.confidence * 100).toFixed(0)}% CONFIDENCE)` : ""}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
