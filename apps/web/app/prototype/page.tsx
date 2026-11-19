"use client";

import Link from "next/link";

export default function PrototypeHubPage() {

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 p-6 md:p-10 font-sans">
      <div className="mx-auto max-w-7xl space-y-12">
        {/* Header */}
        <div className="space-y-3 border-b border-neutral-800 pb-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 font-mono text-xs text-amber-400">
            <span className="size-2 rounded-full bg-amber-400 animate-pulse" />
            <span>OPSPILOT AI // v0.7.0 DESIGN EXPLORATION MILESTONE</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white md:text-5xl">
            Visual Identity &amp; Product Experience Redesign
          </h1>
          <p className="max-w-3xl text-sm leading-relaxed text-neutral-400 md:text-base">
            Replacing generic AI-dashboard tropes (dark navy backgrounds, cyan accents, 4 KPI cards, rounded boxes) with two radically differentiated, purpose-built product experiences for autonomous incident response and forensic investigation.
          </p>
        </div>

        {/* Side-by-side Concept Showcase Cards */}
        <div className="grid gap-8 lg:grid-cols-2">
          {/* Concept A Card */}
          <div className="flex flex-col justify-between rounded-xl border border-neutral-700 bg-neutral-900/80 p-6 shadow-xl transition-all hover:border-amber-500/60">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
                <span className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-xs font-bold text-amber-400">
                  CONCEPT A
                </span>
                <span className="font-mono text-xs text-neutral-400">
                  EDITORIAL FORENSICS LAB
                </span>
              </div>
              <h2 className="text-2xl font-bold text-white">
                Incident Forensics Lab
              </h2>
              <p className="text-xs leading-relaxed text-neutral-300">
                Inspiration: Scientific forensic investigation workspaces, editorial investigative journalism, and legal inquiry dossiers. Light-first warm ivory surfaces, archival typography, stamped evidence exhibits, and chronological cross-examination chains.
              </p>

              <div className="space-y-2 rounded-lg border border-neutral-800 bg-neutral-950 p-4 font-mono text-xs text-neutral-400">
                <div className="flex justify-between">
                  <span>CANVAS / TONE:</span>
                  <strong className="text-amber-200">Warm Ivory (#FBFBF8) / Archival</strong>
                </div>
                <div className="flex justify-between">
                  <span>SIGNATURE ACCENT:</span>
                  <strong className="text-amber-500">Forensic Ochre (#C05621) / Cobalt</strong>
                </div>
                <div className="flex justify-between">
                  <span>TYPOGRAPHY:</span>
                  <strong className="text-neutral-200">Serif Headlines + Tabular Mono Exhibits</strong>
                </div>
                <div className="flex justify-between">
                  <span>CORE MOTIF:</span>
                  <strong className="text-neutral-200">Evidence Binders &amp; Verification Stamps</strong>
                </div>
              </div>
            </div>

            <div className="mt-6 space-y-2 pt-4 border-t border-neutral-800">
              <Link
                href="/prototype/concept-a/home"
                className="block w-full rounded bg-amber-600 py-2.5 text-center font-mono text-xs font-bold text-white hover:bg-amber-500 transition-colors shadow-md"
              >
                Launch Concept A Interactive Prototype →
              </Link>
            </div>
          </div>

          {/* Concept B Card */}
          <div className="flex flex-col justify-between rounded-xl border border-neutral-700 bg-neutral-900/80 p-6 shadow-xl transition-all hover:border-cyan-500/60">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
                <span className="rounded bg-cyan-500/20 px-2 py-0.5 font-mono text-xs font-bold text-cyan-400">
                  CONCEPT B
                </span>
                <span className="font-mono text-xs text-neutral-400">
                  AVIONICS MISSION CONTROL
                </span>
              </div>
              <h2 className="text-2xl font-bold text-white">
                Flight Recorder / Mission Control
              </h2>
              <p className="text-xs leading-relaxed text-neutral-300">
                Inspiration: Aircraft black-box flight recorders, cockpit avionics consoles, industrial telemetry instrumentation. Deep carbon neutrals (never generic navy), phosphor green/cyan signals, master caution amber, and synchronized multi-sensor strip charts.
              </p>

              <div className="space-y-2 rounded-lg border border-neutral-800 bg-neutral-950 p-4 font-mono text-xs text-neutral-400">
                <div className="flex justify-between">
                  <span>CANVAS / TONE:</span>
                  <strong className="text-neutral-200">Radar Carbon (#0A0C0E) / High-Contrast</strong>
                </div>
                <div className="flex justify-between">
                  <span>SIGNATURE ACCENT:</span>
                  <strong className="text-amber-400">Avionics Amber (#F59E0B) / Phosphor Cyan</strong>
                </div>
                <div className="flex justify-between">
                  <span>TYPOGRAPHY:</span>
                  <strong className="text-neutral-200">Industrial Technical Monospace</strong>
                </div>
                <div className="flex justify-between">
                  <span>CORE MOTIF:</span>
                  <strong className="text-neutral-200">Time-Scrubber Ribbons &amp; 4-Channel Separation</strong>
                </div>
              </div>
            </div>

            <div className="mt-6 space-y-2 pt-4 border-t border-neutral-800">
              <Link
                href="/prototype/concept-b/home"
                className="block w-full rounded bg-cyan-600 py-2.5 text-center font-mono text-xs font-bold text-white hover:bg-cyan-500 transition-colors shadow-md"
              >
                Launch Concept B Interactive Prototype →
              </Link>
            </div>
          </div>
        </div>

        {/* 5-Screen Interactive Quick Launch Grid */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-6 space-y-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-neutral-800 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white">
                Core Screens Navigation Matrix
              </h3>
              <p className="text-xs text-neutral-400">
                Compare both concepts across all five required product screens with public simulator and telemetry data.
              </p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {[
              {
                num: "01",
                title: "Screen 1: Home Intake",
                desc: "Replaces 4-KPI cards with real 3-mode intake and recent activity.",
                linkA: "/prototype/concept-a/home",
                linkB: "/prototype/concept-b/home",
              },
              {
                num: "02",
                title: "Screen 2: Workbench",
                desc: "Flagship incident screen with timeline, hypotheses, safety gates, and HITL.",
                linkA: "/prototype/concept-a/workbench",
                linkB: "/prototype/concept-b/workbench",
              },
              {
                num: "03",
                title: "Screen 3: Causal Explorer",
                desc: "Chronological anomaly correlation, competing causes, and uncertainty bounds.",
                linkA: "/prototype/concept-a/explorer",
                linkB: "/prototype/concept-b/explorer",
              },
              {
                num: "04",
                title: "Screen 4: Architecture",
                desc: "System cartography, RAG pipeline, and telemetry connectors.",
                linkA: "/prototype/concept-a/architecture",
                linkB: "/prototype/concept-b/architecture",
              },
              {
                num: "05",
                title: "Screen 5: Dev Guide",
                desc: "First-time setup commands, local Ollama config, and safety boundaries.",
                linkA: "/prototype/concept-a/guide",
                linkB: "/prototype/concept-b/guide",
              },
            ].map((sc) => (
              <div
                key={sc.num}
                className="flex flex-col justify-between rounded-lg border border-neutral-800 bg-neutral-950 p-4 text-xs"
              >
                <div>
                  <span className="font-mono text-[10px] font-bold text-amber-500">
                    SCREEN {sc.num}
                  </span>
                  <h4 className="mt-1 font-bold text-white text-sm">{sc.title}</h4>
                  <p className="mt-1.5 text-neutral-400 leading-relaxed text-[11px]">{sc.desc}</p>
                </div>

                <div className="mt-4 space-y-2 border-t border-neutral-800 pt-3 font-mono text-[11px]">
                  <Link
                    href={sc.linkA}
                    className="flex items-center justify-between rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-amber-300 hover:bg-amber-500/20"
                  >
                    <span>Concept A</span>
                    <span>→</span>
                  </Link>
                  <Link
                    href={sc.linkB}
                    className="flex items-center justify-between rounded border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-cyan-300 hover:bg-cyan-500/20"
                  >
                    <span>Concept B</span>
                    <span>→</span>
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Detailed 8-Dimension Evaluation Matrix */}
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-6 space-y-6">
          <div className="border-b border-neutral-800 pb-3">
            <h3 className="text-xl font-bold text-white">
              Comparative Evaluation Matrix (8 Dimensions)
            </h3>
            <p className="text-xs text-neutral-400">
              Rigorous side-by-side analysis assessing identity, readability, ergonomics, and implementation feasibility.
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-neutral-800 text-neutral-400">
                  <th className="py-2.5 px-3">Dimension</th>
                  <th className="py-2.5 px-3 text-amber-400">Concept A: Forensics Lab</th>
                  <th className="py-2.5 px-3 text-cyan-400">Concept B: Flight Recorder</th>
                  <th className="py-2.5 px-3 text-white">Analysis &amp; Contrast</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800 text-neutral-300">
                <tr>
                  <td className="py-3 px-3 font-bold text-white">1. Distinctiveness</td>
                  <td className="py-3 px-3">Exceptional. Completely diverges from dark SaaS dashboards with warm editorial ivory and scientific typography.</td>
                  <td className="py-3 px-3">High. Strong avionics cockpit aesthetic with deep radar carbon and annunciator warning lights.</td>
                  <td className="py-3 px-3 text-neutral-400">Concept A is radically more unexpected in the AI space; Concept B provides industrial instrumentation fidelity.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">2. Technical Evidence Readability</td>
                  <td className="py-3 px-3">Superb. High contrast black ink on ivory paper minimizes fatigue when reading long stack traces and logs.</td>
                  <td className="py-3 px-3">Very Good. High contrast white/cyan text on carbon black with prominent tabular numerals.</td>
                  <td className="py-3 px-3 text-neutral-400">Concept A excels at deep narrative RCA reading; Concept B excels at rapid telemetry anomaly scanning.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">3. Investigation Usability</td>
                  <td className="py-3 px-3">Dossier tab structure organizes complex evidence into clear exhibits; natural paper hierarchy.</td>
                  <td className="py-3 px-3">Time scrubber tape provides immediate temporal context for correlating deployments with faults.</td>
                  <td className="py-3 px-3 text-neutral-400">Concept B offers faster chronological correlation; Concept A provides superior evidence cross-examination.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">4. Visual Appeal &amp; Polish</td>
                  <td className="py-3 px-3">Sophisticated, editorial, premium. Feels like a technical research lab publication.</td>
                  <td className="py-3 px-3">Crisp, tactile, utilitarian. Feels like high-reliability avionics hardware.</td>
                  <td className="py-3 px-3 text-neutral-400">Both completely eliminate generic AI sparkle icons and neon gradients.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">5. Responsiveness &amp; Mobile</td>
                  <td className="py-3 px-3">Flows naturally into single-column editorial reading layout on mobile screens.</td>
                  <td className="py-3 px-3">Sensor ribbons collapse into compact vertical telemetry cards with preserved time ticks.</td>
                  <td className="py-3 px-3 text-neutral-400">Both concepts maintain high mobile readability without horizontal overflow.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">6. Accessibility &amp; Contrast</td>
                  <td className="py-3 px-3">WCAG AAA compliant contrast ratios (14.2:1 deep ink on ivory canvas).</td>
                  <td className="py-3 px-3">WCAG AAA compliant contrast (15.1:1 telemetry white on radar carbon).</td>
                  <td className="py-3 px-3 text-neutral-400">Both exceed accessibility baselines and avoid low-contrast grey-on-dark-navy.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">7. Mode Versatility</td>
                  <td className="py-3 px-3">Seamlessly handles Simulator, Uploaded Evidence, and Connected Telemetry via dossier stamps.</td>
                  <td className="py-3 px-3">Handles all 3 modes via 4-channel telemetry bus status indicators.</td>
                  <td className="py-3 px-3 text-neutral-400">Both cleanly prohibit implying remediation execution in read-only modes.</td>
                </tr>
                <tr>
                  <td className="py-3 px-3 font-bold text-white">8. Implementation Complexity</td>
                  <td className="py-3 px-3">Low-to-medium. Standard Tailwind classes, CSS tokens, and editorial component hierarchy.</td>
                  <td className="py-3 px-3">Medium. Requires custom telemetry ribbon styling, annunciator states, and grid backgrounds.</td>
                  <td className="py-3 px-3 text-neutral-400">Both integrate cleanly into existing Next.js 16 + React 19 architecture without heavy dependencies.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
