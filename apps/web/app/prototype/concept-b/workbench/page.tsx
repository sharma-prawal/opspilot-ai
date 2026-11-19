"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PROTOTYPE_SCENARIOS, ScenarioDetail } from "../../shared/data";

function FlightRecorderContent() {
  const searchParams = useSearchParams();
  const scenarioParam = searchParams.get("scenario") || "INC-002";
  const modeParam = searchParams.get("mode");

  const [activeScenarioKey, setActiveScenarioKey] = useState<string>(
    modeParam === "uploaded" ? "UPLOAD-01" : modeParam === "connected" ? "CONN-01" : scenarioParam
  );
  const [selectedHypothesis, setSelectedHypothesis] = useState<string>("HYP-01");

  const scenario: ScenarioDetail = PROTOTYPE_SCENARIOS[activeScenarioKey] || PROTOTYPE_SCENARIOS["INC-002"];

  return (
    <div className="space-y-4">
      {/* Top Telemetry Scrubber & Flight Mode Switcher */}
      <div className="avionics-frame p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between border-b border-[#232A35] pb-3">
          <div className="flex items-center gap-3">
            <span className="annunciator-pill annunciator-caution font-mono text-xs">
              REC // {scenario.key}
            </span>
            <div>
              <div className="flex items-center gap-2 font-mono text-[10px] text-[#8B97A8]">
                <span>ONSET: {scenario.triggerTime}</span>
                <span>·</span>
                <span>BUS: {scenario.service}</span>
                <span>·</span>
                <span className="text-[#06B6D4]">TTD: {scenario.ttdSeconds}s</span>
              </div>
              <h2 className="font-mono text-base font-bold text-white">
                {scenario.title}
              </h2>
            </div>
          </div>

          {/* Mode Switcher Buttons */}
          <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
            <button
              onClick={() => {
                setActiveScenarioKey("INC-002");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 transition-colors ${
                activeScenarioKey === "INC-002"
                  ? "border-[#F59E0B] bg-[#F59E0B] text-black font-bold"
                  : "border-[#232A35] bg-[#181D24] text-[#8B97A8] hover:text-white"
              }`}
            >
              INC-002 (Gate Intercept)
            </button>
            <button
              onClick={() => {
                setActiveScenarioKey("INC-003");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 transition-colors ${
                activeScenarioKey === "INC-003"
                  ? "border-[#F59E0B] bg-[#F59E0B] text-black font-bold"
                  : "border-[#232A35] bg-[#181D24] text-[#8B97A8] hover:text-white"
              }`}
            >
              INC-003 (4-Step HITL)
            </button>
            <button
              onClick={() => {
                setActiveScenarioKey("UPLOAD-01");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 transition-colors ${
                activeScenarioKey === "UPLOAD-01"
                  ? "border-[#06B6D4] bg-[#06B6D4] text-black font-bold"
                  : "border-[#232A35] bg-[#181D24] text-[#8B97A8] hover:text-white"
              }`}
            >
              UPLOAD-01 (Offline)
            </button>
            <button
              onClick={() => {
                setActiveScenarioKey("CONN-01");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 transition-colors ${
                activeScenarioKey === "CONN-01"
                  ? "border-[#10B981] bg-[#10B981] text-black font-bold"
                  : "border-[#232A35] bg-[#181D24] text-[#8B97A8] hover:text-white"
              }`}
            >
              CONN-01 (Loki/Prom)
            </button>
          </div>
        </div>

        {/* Multi-Channel Scrubber Tape */}
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 font-mono text-[11px]">
          <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2">
            <span className="text-[10px] text-[#525D6D]">CH-01 SENSOR TELEMETRY</span>
            <div className="font-bold text-[#06B6D4]">{scenario.evidence.length} STREAMS INGESTED</div>
          </div>
          <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2">
            <span className="text-[10px] text-[#525D6D]">CH-02 MODEL CONFIDENCE</span>
            <div className="font-bold text-[#F59E0B]">{(scenario.confidence * 100).toFixed(0)}% PROBABLE</div>
          </div>
          <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2">
            <span className="text-[10px] text-[#525D6D]">CH-03 SAFETY KERNEL</span>
            <div className="font-bold text-[#EF4444]">
              {scenario.safetyGates.some((g) => g.status === "blocked")
                ? "ACTION INTERCEPTED"
                : "GATES NOMINAL"}
            </div>
          </div>
          <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2">
            <span className="text-[10px] text-[#525D6D]">CH-04 ACTUATOR LEASE</span>
            <div className="font-bold text-[#10B981]">
              {scenario.mode === "simulator" ? "CRYPTOGRAPHIC HITL" : "READ-ONLY AUDIT"}
            </div>
          </div>
        </div>
      </div>

      {/* Main Mission Control 2-Column Console */}
      <div className="grid gap-4 lg:grid-cols-12 font-mono">
        {/* Left Column: Synchronized Flight Timeline Tape (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>SYNCHRONIZED FLIGHT RECORDER TAPE</span>
              <span>TIME TICK: Δt</span>
            </div>

            <div className="space-y-3">
              {scenario.eventsTimeline.map((ev, i) => (
                <div
                  key={i}
                  className={`rounded border p-2.5 text-xs ${
                    ev.severity === "critical"
                      ? "border-[#EF4444] bg-[#EF4444]/10"
                      : ev.severity === "warning"
                      ? "border-[#F59E0B] bg-[#F59E0B]/10"
                      : "border-[#232A35] bg-[#0A0C0E]"
                  }`}
                >
                  <div className="flex items-center justify-between text-[10px] text-[#8B97A8]">
                    <span className="font-bold text-[#F0F3F6]">{ev.timeOffset}</span>
                    <span>{ev.absoluteTime}</span>
                    <span
                      className={`font-bold uppercase ${
                        ev.severity === "critical"
                          ? "text-[#EF4444]"
                          : ev.severity === "warning"
                          ? "text-[#F59E0B]"
                          : "text-[#10B981]"
                      }`}
                    >
                      [{ev.type}]
                    </span>
                  </div>
                  <h4 className="mt-1 font-bold text-white text-[11px]">{ev.summary}</h4>
                  <p className="mt-0.5 text-[10px] text-[#8B97A8]">{ev.details}</p>
                </div>
              ))}
            </div>
          </div>

          {/* CH-03 Safety Gate Interceptor Console */}
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>CH-03 // DETERMINISTIC SAFETY GATE ENGINE</span>
              <span>PURE PYTHON KERNEL</span>
            </div>

            <div className="space-y-2.5">
              {scenario.safetyGates.map((gate) => (
                <div
                  key={gate.id}
                  className={`rounded border p-2.5 text-xs ${
                    gate.status === "blocked"
                      ? "border-[#EF4444] bg-[#EF4444]/15"
                      : "border-[#232A35] bg-[#0A0C0E]"
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-bold text-white">{gate.name}</span>
                    <span
                      className={`font-bold uppercase ${
                        gate.status === "blocked" ? "text-[#EF4444]" : "text-[#10B981]"
                      }`}
                    >
                      [{gate.status}]
                    </span>
                  </div>
                  <div className="mt-1 text-[10px] text-[#8B97A8]">
                    INVARIANT: <code>{gate.rule}</code>
                  </div>
                  <div className="mt-1 text-[10px] font-semibold text-[#F0F3F6]">
                    {gate.detail}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column: Analytics, Telemetry Streams & Actuator Actions (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          {/* CH-02 Analytics: Competing Hypotheses */}
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>CH-02 // ANALYTICS ENGINE // COMPETING HYPOTHESES</span>
              <span>LOCAL OLLAMA LLM</span>
            </div>

            <div className="space-y-2.5">
              {scenario.hypotheses.map((h) => {
                const isSel = selectedHypothesis === h.id;
                return (
                  <div
                    key={h.id}
                    onClick={() => setSelectedHypothesis(h.id)}
                    className={`cursor-pointer rounded border p-3 text-xs transition-all ${
                      isSel
                        ? "border-[#F59E0B] bg-[#F59E0B]/10 shadow-[0_0_10px_rgba(245,158,11,0.15)]"
                        : "border-[#232A35] bg-[#0A0C0E] hover:border-[#3B4657]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[#F59E0B] font-bold">[{h.id}]</span>
                        <span className="font-bold text-white">{h.title}</span>
                      </div>
                      <span className="font-bold text-[#F59E0B]">
                        {(h.probability * 100).toFixed(0)}% P
                      </span>
                    </div>

                    <p className="mt-1.5 text-[11px] text-[#8B97A8] leading-relaxed">
                      {h.reasoning}
                    </p>

                    <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-[#525D6D]">
                      <span>CORRELATED STREAMS:</span>
                      {h.supportingEvidence.map((ev) => (
                        <span key={ev} className="rounded bg-[#181D24] px-1.5 py-0.2 text-[#06B6D4] font-bold">
                          {ev}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* CH-01 Sensor Readings Ribbon */}
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>CH-01 // SENSOR BUS // NORMALIZED TELEMETRY EXHIBITS</span>
              <span>MCP STDIO + RAG</span>
            </div>

            <div className="space-y-2">
              {scenario.evidence.map((ev) => (
                <div
                  key={ev.id}
                  className={`rounded border p-2.5 text-xs ${
                    ev.cited
                      ? "border-[#F59E0B]/50 bg-[#181D24]"
                      : "border-[#232A35] bg-[#0A0C0E] opacity-75"
                  }`}
                >
                  <div className="flex items-center justify-between text-[10px]">
                    <div className="flex items-center gap-2">
                      <span className="text-[#06B6D4] font-bold">[{ev.id}]</span>
                      <span className="font-bold text-white uppercase">[{ev.kind}]</span>
                      <span className="text-[#8B97A8]">{ev.source}</span>
                    </div>
                    {ev.cited && <span className="font-bold text-[#F59E0B]">★ CITED IN RCA</span>}
                  </div>
                  <h5 className="mt-1 font-bold text-white text-[11px]">{ev.title}</h5>
                  <p className="mt-0.5 text-[10px] text-[#8B97A8]">{ev.summary}</p>
                </div>
              ))}
            </div>
          </div>

          {/* CH-04 Actuator Console & Post-Incident Provenance */}
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>CH-04 // ACTUATOR DISPATCH &amp; VERIFIED RECOVERY</span>
              {scenario.rcaSummary.recoveryConfirmed ? (
                <span className="text-[#10B981] font-bold">✓ RECOVERY CONFIRMED</span>
              ) : (
                <span className="text-[#06B6D4] font-bold">READ-ONLY AUDIT</span>
              )}
            </div>

            {scenario.mode === "simulator" && (
              <div className="space-y-2">
                <div className="rounded border border-[#F59E0B]/50 bg-[#F59E0B]/10 p-2 text-xs">
                  <div className="text-[10px] font-bold text-[#F59E0B]">
                    OPERATOR AUTHORIZATION LEASE: VALIDATED
                  </div>
                  <p className="mt-0.5 text-[10px] text-[#8B97A8]">
                    Lease token signed by <code>demo-operator</code>. Plan dispatched to sandboxed container runtime.
                  </p>
                </div>

                <div className="divide-y divide-[#232A35] rounded border border-[#232A35] bg-[#0A0C0E]">
                  {scenario.remediationPlan.map((step) => (
                    <div key={step.step} className="p-2.5 text-xs flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white">STEP {step.step}:</span>
                          <code className="text-[#06B6D4] font-bold">{step.action}</code>
                          <span className="text-[#8B97A8]">target: {step.targetService}</span>
                        </div>
                        <p className="mt-0.5 text-[10px] text-[#8B97A8]">{step.rationale}</p>
                      </div>
                      <span
                        className={`text-[10px] font-bold uppercase ${
                          step.status === "executed"
                            ? "text-[#10B981]"
                            : step.status === "blocked"
                            ? "text-[#EF4444]"
                            : "text-[#8B97A8]"
                        }`}
                      >
                        [{step.status}]
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {scenario.mode !== "simulator" && (
              <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-3 text-xs">
                <div className="text-[10px] font-bold text-[#06B6D4]">
                  READ-ONLY FORENSIC BUS ACTIVE
                </div>
                <p className="mt-1 text-[10px] text-[#8B97A8] leading-relaxed">
                  Incident artifacts were diagnosed passively without mutating live infrastructure. Remediation proposals are generated as advisory findings only.
                </p>
              </div>
            )}

            {/* Final Provenance Table */}
            <div className="mt-4 border-t border-[#232A35] pt-3">
              <div className="text-[10px] font-bold uppercase text-[#8B97A8]">
                ROOT-CAUSE POSTMORTEM PROVENANCE
              </div>
              <p className="mt-1 text-xs text-white leading-relaxed">
                {scenario.rcaSummary.rootCause}
              </p>

              <div className="mt-2.5 overflow-x-auto">
                <table className="w-full text-left text-[10px] font-mono">
                  <thead>
                    <tr className="border-b border-[#232A35] text-[#525D6D]">
                      <th className="py-1">FACT CLAIM</th>
                      <th className="py-1">EVIDENCE SOURCE</th>
                      <th className="py-1">INDEPENDENT VERIFIER</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#232A35]">
                    {scenario.rcaSummary.provenanceTable.map((p, i) => (
                      <tr key={i} className="text-[#F0F3F6]">
                        <td className="py-1">{p.claim}</td>
                        <td className="py-1 text-[#F59E0B] font-bold">{p.sourceExhibit}</td>
                        <td className="py-1 text-[#06B6D4]">{p.verifier}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ConceptBWorkbenchPage() {
  return (
    <Suspense fallback={<div className="p-8 font-mono text-xs text-[#8B97A8]">ENGAGING AVIONICS CONSOLE…</div>}>
      <FlightRecorderContent />
    </Suspense>
  );
}
