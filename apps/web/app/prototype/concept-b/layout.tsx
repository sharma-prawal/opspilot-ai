"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const FLIGHT_CHANNELS = [
  { href: "/prototype/concept-b/home", label: "FLIGHT DECK", ch: "CH-01" },
  { href: "/prototype/concept-b/workbench", label: "FLIGHT RECORDER", ch: "CH-02" },
  { href: "/prototype/concept-b/explorer", label: "SENSOR MATRIX", ch: "CH-03" },
  { href: "/prototype/concept-b/architecture", label: "AVIONICS BUS", ch: "CH-04" },
  { href: "/prototype/concept-b/guide", label: "OPS MANUAL", ch: "CH-05" },
];

export default function ConceptBLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="concept-mission-control min-h-screen text-[#F0F3F6] telemetry-grid">
      {/* Avionics Annunciator Top Bar */}
      <div className="border-b border-[#232A35] bg-[#0A0C0E] px-4 py-2 font-mono text-[10px]">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="annunciator-pill annunciator-nominal">
              <span className="size-1.5 rounded-full bg-[#10B981] animate-pulse" />
              FLIGHT RECORDER ACTIVE
            </span>
            <span className="annunciator-pill annunciator-caution">
              SAFETY KERNEL ARMED
            </span>
            <span className="hidden sm:inline-flex annunciator-pill border border-[#232A35] bg-[#111419] text-[#8B97A8]">
              BUS: LOCAL-FIRST 127.0.0.1
            </span>
          </div>

          <div className="flex items-center gap-3 text-[#8B97A8]">
            <span>UTC: 12:14:02</span>
            <span>·</span>
            <span>FREQ: 44.1kHz MCP</span>
            <span>·</span>
            <span className="text-[#06B6D4]">ENGINE: QWEN3-8B</span>
          </div>
        </div>
      </div>

      {/* Cockpit Instrument Console Masthead */}
      <header className="border-b border-[#232A35] bg-[#111419] px-6 py-3.5">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex size-9 items-center justify-center rounded border border-[#F59E0B]/50 bg-[#1A150B] text-[#F59E0B] shadow-[0_0_12px_rgba(245,158,11,0.2)]">
              <span className="font-mono text-sm font-black">OP</span>
            </div>
            <div>
              <div className="flex items-center gap-2 font-mono text-[10px] tracking-wider text-[#8B97A8]">
                <span>INCIDENT MISSION CONTROL</span>
                <span>/</span>
                <span className="text-[#F59E0B]">CONCEPT B: FLIGHT RECORDER</span>
              </div>
              <h1 className="font-mono text-lg font-bold tracking-tight text-white">
                OpsPilot Flight Recorder &amp; Telemetry Control
              </h1>
            </div>
          </div>

          {/* Instrument Channel Tabs */}
          <nav className="flex flex-wrap gap-1 font-mono text-xs">
            {FLIGHT_CHANNELS.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-1.5 rounded border px-3 py-1.5 transition-all ${
                    isActive
                      ? "border-[#F59E0B] bg-[#F59E0B]/15 text-[#F59E0B] shadow-[0_0_8px_rgba(245,158,11,0.2)] font-bold"
                      : "border-[#232A35] bg-[#181D24] text-[#8B97A8] hover:border-[#3B4657] hover:text-white"
                  }`}
                >
                  <span className="text-[10px] opacity-75">{item.ch}:</span>
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Main Console Viewport */}
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</div>
    </div>
  );
}
