"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PROTOTYPE_SCENARIOS, ScenarioDetail } from "../../shared/data";

function WorkbenchContent() {
  const searchParams = useSearchParams();
  const scenarioParam = searchParams.get("scenario") || "INC-003";
  const modeParam = searchParams.get("mode");

  const [activeScenarioKey, setActiveScenarioKey] = useState<string>(
    modeParam === "uploaded" ? "UPLOAD-01" : modeParam === "connected" ? "CONN-01" : scenarioParam
  );
  const [selectedHypothesis, setSelectedHypothesis] = useState<string>("HYP-01");
  const [evidenceFilter, setEvidenceFilter] = useState<string>("all");

  const scenario: ScenarioDetail = PROTOTYPE_SCENARIOS[activeScenarioKey] || PROTOTYPE_SCENARIOS["INC-003"];

  const filteredEvidence = scenario.evidence.filter((e) => {
    if (evidenceFilter === "cited") return e.cited;
    if (evidenceFilter === "all") return true;
    return e.kind === evidenceFilter;
  });

  return (
    <div className="space-y-6">
      {/* Dossier Header & Mode Selector */}
      <div className="dossier-paper p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between border-b border-[#E2DFD5] pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="exhibit-tag">CASE: {scenario.key}</span>
              <span className="font-mono text-xs font-semibold text-[#78828F]">
                ONSET: {scenario.triggerTime}
              </span>
              <span className="font-mono text-xs text-[#78828F]">·</span>
              <span className="font-mono text-xs font-semibold text-[#1E3A8A]">
                TARGET: {scenario.service}
              </span>
              {scenario.mode === "uploaded" && (
                <span className="rounded bg-[#EFF6FF] px-2 py-0.5 font-mono text-[10px] font-bold text-[#1E3A8A]">
                  READ-ONLY OFFLINE EVIDENCE
                </span>
              )}
              {scenario.mode === "connected" && (
                <span className="rounded bg-[#EFF6FF] px-2 py-0.5 font-mono text-[10px] font-bold text-[#1E3A8A]">
                  READ-ONLY LIVE TELEMETRY
                </span>
              )}
            </div>
            <h2 className="font-serif-heading mt-2 text-2xl font-bold text-[#16191D]">
              {scenario.title}
            </h2>
          </div>

          {/* Mode Switcher Pills */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-[#78828F]">Switch Case:</span>
            <button
              onClick={() => {
                setActiveScenarioKey("INC-003");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 font-mono text-xs transition-colors ${
                activeScenarioKey === "INC-003"
                  ? "border-[#16191D] bg-[#16191D] text-white"
                  : "border-[#C8C4B7] bg-[#F4F3EC] text-[#4A525D] hover:bg-white"
              }`}
            >
              INC-003 (Simulator HITL)
            </button>
            <button
              onClick={() => {
                setActiveScenarioKey("INC-002");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 font-mono text-xs transition-colors ${
                activeScenarioKey === "INC-002"
                  ? "border-[#16191D] bg-[#16191D] text-white"
                  : "border-[#C8C4B7] bg-[#F4F3EC] text-[#4A525D] hover:bg-white"
              }`}
            >
              INC-002 (Safety Gate Block)
            </button>
            <button
              onClick={() => {
                setActiveScenarioKey("UPLOAD-01");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 font-mono text-xs transition-colors ${
                activeScenarioKey === "UPLOAD-01"
                  ? "border-[#16191D] bg-[#16191D] text-white"
                  : "border-[#C8C4B7] bg-[#F4F3EC] text-[#4A525D] hover:bg-white"
              }`}
            >
              UPLOAD-01 (Offline Files)
            </button>
            <button
              onClick={() => {
                setActiveScenarioKey("CONN-01");
                setSelectedHypothesis("HYP-01");
              }}
              className={`rounded border px-2.5 py-1 font-mono text-xs transition-colors ${
                activeScenarioKey === "CONN-01"
                  ? "border-[#16191D] bg-[#16191D] text-white"
                  : "border-[#C8C4B7] bg-[#F4F3EC] text-[#4A525D] hover:bg-white"
              }`}
            >
              CONN-01 (Loki/Prom)
            </button>
          </div>
        </div>

        {/* Forensic Case Metrics Ribbon */}
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4 text-xs font-mono">
          <div>
            <div className="text-[#78828F]">CONFIDENCE SCORE</div>
            <div className="text-base font-bold text-[#047857]">
              {(scenario.confidence * 100).toFixed(0)}% PROBABLE
            </div>
          </div>
          <div>
            <div className="text-[#78828F]">TIME TO DIAGNOSIS</div>
            <div className="text-base font-bold text-[#16191D]">
              {scenario.ttdSeconds} SECONDS
            </div>
          </div>
          <div>
            <div className="text-[#78828F]">INDEXED EXHIBITS</div>
            <div className="text-base font-bold text-[#16191D]">
              {scenario.evidence.length} ARTIFACTS
            </div>
          </div>
          <div>
            <div className="text-[#78828F]">SAFETY STATUS</div>
            <div className="text-base font-bold text-[#047857]">
              DETERMINISTIC GATES GREEN
            </div>
          </div>
        </div>
      </div>

      {/* Main Forensic Examination Grid */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* Left Column: Chronological Causal Timeline (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="dossier-paper p-4">
            <div className="flex items-center justify-between border-b border-[#E2DFD5] pb-2">
              <h3 className="font-serif-heading text-base font-bold text-[#16191D]">
                Chronological Causal Chain
              </h3>
              <span className="font-mono text-[10px] text-[#78828F]">UTC CORRELATION</span>
            </div>

            <ol className="relative mt-4 space-y-4 border-l-2 border-[#E2DFD5] pl-4 text-xs">
              {scenario.eventsTimeline.map((ev, i) => (
                <li key={i} className="relative">
                  <span
                    className={`absolute -left-[21px] top-1 size-2.5 rounded-full border border-white ${
                      ev.severity === "critical"
                        ? "bg-[#B91C1C]"
                        : ev.severity === "warning"
                        ? "bg-[#C05621]"
                        : "bg-[#047857]"
                    }`}
                  />
                  <div className="flex items-center justify-between font-mono text-[11px] text-[#78828F]">
                    <span>{ev.absoluteTime}</span>
                    <span className="font-semibold text-[#16191D]">{ev.timeOffset}</span>
                  </div>
                  <h4 className="font-serif-heading mt-0.5 text-xs font-bold text-[#16191D]">
                    {ev.summary}
                  </h4>
                  <p className="mt-1 text-[11px] leading-relaxed text-[#4A525D]">
                    {ev.details}
                  </p>
                </li>
              ))}
            </ol>
          </div>

          {/* Deterministic Safety Gate Audit Card */}
          <div className="dossier-paper p-4">
            <h3 className="font-serif-heading text-sm font-bold text-[#16191D] border-b border-[#E2DFD5] pb-2">
              Deterministic Safety Gates Interceptor
            </h3>
            <div className="mt-3 space-y-2.5">
              {scenario.safetyGates.map((gate) => (
                <div
                  key={gate.id}
                  className={`rounded border p-2.5 text-xs ${
                    gate.status === "blocked"
                      ? "border-[#B91C1C] bg-[#FEE2E2]/30"
                      : "border-[#E2DFD5] bg-[#FBFBF8]"
                  }`}
                >
                  <div className="flex items-center justify-between font-mono text-[11px]">
                    <span className="font-bold text-[#16191D]">{gate.name}</span>
                    <span
                      className={`font-bold uppercase ${
                        gate.status === "blocked" ? "text-[#B91C1C]" : "text-[#047857]"
                      }`}
                    >
                      [{gate.status}]
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-[#78828F] font-mono">
                    RULE: {gate.rule}
                  </div>
                  <div className="mt-1 text-[11px] font-medium text-[#16191D]">
                    {gate.detail}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column: Hypotheses, Evidence Exhibits & Remediation (7 cols) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Competing Failure Hypotheses */}
          <div className="dossier-paper p-5">
            <div className="flex items-center justify-between border-b border-[#E2DFD5] pb-2">
              <h3 className="font-serif-heading text-base font-bold text-[#16191D]">
                Competing Root-Cause Hypotheses
              </h3>
              <span className="font-mono text-xs text-[#78828F]">CROSS-EXAMINATION</span>
            </div>

            <div className="mt-4 space-y-3">
              {scenario.hypotheses.map((h) => {
                const isSelected = selectedHypothesis === h.id;
                return (
                  <div
                    key={h.id}
                    onClick={() => setSelectedHypothesis(h.id)}
                    className={`cursor-pointer rounded border p-4 transition-all ${
                      isSelected
                        ? "border-[#C05621] bg-[#FFFBF5] shadow-xs"
                        : "border-[#E2DFD5] bg-white hover:bg-[#FBFBF8]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="exhibit-tag">{h.id}</span>
                        <span className="font-serif-heading text-sm font-bold text-[#16191D]">
                          {h.title}
                        </span>
                      </div>
                      <span className="font-mono text-xs font-bold text-[#C05621]">
                        {(h.probability * 100).toFixed(0)}% PROBABLE
                      </span>
                    </div>

                    <p className="mt-2 text-xs text-[#4A525D] leading-relaxed">
                      {h.reasoning}
                    </p>

                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-mono text-[#78828F]">
                      <span>Supporting Exhibits:</span>
                      {h.supportingEvidence.map((evId) => (
                        <span key={evId} className="rounded bg-[#F4F3EC] px-1.5 py-0.5 text-[#16191D] font-bold">
                          {evId}
                        </span>
                      ))}
                      {h.contradictingEvidence.length > 0 && (
                        <>
                          <span className="ml-2 text-[#B91C1C]">Contradicted By:</span>
                          {h.contradictingEvidence.map((evId) => (
                            <span key={evId} className="rounded bg-[#FEE2E2] px-1.5 py-0.5 text-[#B91C1C] font-bold">
                              {evId}
                            </span>
                          ))}
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Evidence Exhibit Binder */}
          <div className="dossier-paper p-5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E2DFD5] pb-3">
              <div>
                <h3 className="font-serif-heading text-base font-bold text-[#16191D]">
                  Evidence Exhibits Binder
                </h3>
                <span className="font-mono text-[11px] text-[#78828F]">
                  Indexed Telemetry, Logs, Metrics &amp; Runbook Chunks
                </span>
              </div>

              {/* Exhibit filter */}
              <div className="flex rounded border border-[#C8C4B7] bg-[#F4F3EC] p-0.5 text-xs">
                {["all", "cited", "log", "metric", "change"].map((f) => (
                  <button
                    key={f}
                    onClick={() => setEvidenceFilter(f)}
                    className={`rounded px-2.5 py-0.5 font-mono text-[11px] uppercase transition-all ${
                      evidenceFilter === f
                        ? "bg-white text-[#16191D] font-bold shadow-xs"
                        : "text-[#78828F] hover:text-[#16191D]"
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {filteredEvidence.map((ev) => (
                <div
                  key={ev.id}
                  className={`rounded border p-3.5 text-xs transition-colors ${
                    ev.cited
                      ? "border-[#C8C4B7] bg-[#FBFBF8]"
                      : "border-[#E2DFD5] bg-white opacity-80"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EAE7DF] pb-2 font-mono text-[11px]">
                    <div className="flex items-center gap-2">
                      <span className="exhibit-tag">{ev.id}</span>
                      <span className="font-bold text-[#16191D] uppercase">[{ev.kind}]</span>
                      <span className="text-[#78828F]">{ev.source}</span>
                    </div>
                    {ev.cited && (
                      <span className="font-bold text-[#047857]">✓ CITED IN RCA</span>
                    )}
                  </div>

                  <h4 className="mt-2 font-serif-heading text-xs font-bold text-[#16191D]">
                    {ev.title}
                  </h4>
                  <p className="mt-1 text-xs text-[#4A525D] leading-relaxed">
                    {ev.summary}
                  </p>

                  {ev.sourceRef && (
                    <div className="mt-2 font-mono text-[11px] text-[#1E3A8A]">
                      Exhibit Source Coordinate: <code>{ev.sourceRef}</code>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Remediation Action Plan & Verification Stamp */}
          <div className="dossier-paper p-5">
            <div className="flex items-center justify-between border-b border-[#E2DFD5] pb-2">
              <h3 className="font-serif-heading text-base font-bold text-[#16191D]">
                Remediation Actions &amp; Verification Stamp
              </h3>
              {scenario.rcaSummary.recoveryConfirmed ? (
                <div className="stamp-verified">RECOVERY VERIFIED</div>
              ) : (
                <div className="font-mono text-xs font-bold text-[#78828F]">READ-ONLY AUDIT</div>
              )}
            </div>

            {scenario.mode === "simulator" && (
              <div className="mt-4 space-y-3">
                <div className="rounded border border-[#C8C4B7] bg-[#F4F3EC] p-3 text-xs">
                  <div className="font-mono text-[11px] font-bold text-[#C05621]">
                    OPERATOR AUTHORIZATION LEASE ACTIVE
                  </div>
                  <p className="mt-1 text-xs text-[#4A525D]">
                    Cryptographic signature verified by <code>demo-operator</code>. Actions executed inside isolated container sandbox.
                  </p>
                </div>

                <div className="divide-y divide-[#E2DFD5] rounded border border-[#E2DFD5] bg-white">
                  {scenario.remediationPlan.map((step) => (
                    <div key={step.step} className="p-3 text-xs flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-[#16191D]">Step {step.step}:</span>
                          <code className="font-mono font-bold text-[#1E3A8A]">{step.action}</code>
                          <span className="text-[#78828F]">on {step.targetService}</span>
                        </div>
                        <p className="mt-1 text-[11px] text-[#4A525D]">{step.rationale}</p>
                      </div>
                      <span
                        className={`font-mono text-[11px] font-bold uppercase ${
                          step.status === "executed"
                            ? "text-[#047857]"
                            : step.status === "blocked"
                            ? "text-[#B91C1C]"
                            : "text-[#78828F]"
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
              <div className="mt-4 rounded border border-[#E2DFD5] bg-[#F4F3EC] p-4 text-xs">
                <div className="font-mono font-bold text-[#1E3A8A]">
                  READ-ONLY INVESTIGATION MODE ACTIVE
                </div>
                <p className="mt-1 text-xs leading-relaxed text-[#4A525D]">
                  OpsPilot executed in read-only forensic mode. Telemetry and artifacts were analyzed without initiating infrastructure modifications. Suggested remediation steps are published as advisory recommendations only.
                </p>
              </div>
            )}

            {/* Final Provenance Table */}
            <div className="mt-6 border-t border-[#EAE7DF] pt-4">
              <h4 className="font-mono text-xs font-bold uppercase tracking-wider text-[#16191D]">
                Root-Cause Provenance Audit Trail
              </h4>
              <p className="mt-1 text-xs text-[#4A525D] leading-relaxed">
                {scenario.rcaSummary.rootCause}
              </p>

              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left font-mono text-[11px]">
                  <thead>
                    <tr className="border-b border-[#E2DFD5] text-[#78828F]">
                      <th className="py-1.5">Fact Claim</th>
                      <th className="py-1.5">Source Exhibit</th>
                      <th className="py-1.5">Independent Verifier</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EAE7DF]">
                    {scenario.rcaSummary.provenanceTable.map((p, i) => (
                      <tr key={i} className="text-[#16191D]">
                        <td className="py-1.5">{p.claim}</td>
                        <td className="py-1.5 text-[#C05621] font-bold">{p.sourceExhibit}</td>
                        <td className="py-1.5 text-[#1E3A8A]">{p.verifier}</td>
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

export default function ConceptAWorkbenchPage() {
  return (
    <Suspense fallback={<div className="p-8 font-mono text-xs text-[#78828F]">Loading Forensics Workbench…</div>}>
      <WorkbenchContent />
    </Suspense>
  );
}
