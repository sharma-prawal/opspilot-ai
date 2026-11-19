"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

export default function PrototypeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [showMetaBar, setShowMetaBar] = useState(true);

  const isConceptA = pathname.includes("/concept-a");
  const isConceptB = pathname.includes("/concept-b");
  const isMasterHub = pathname === "/prototype";

  return (
    <div className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-black text-white antialiased">
      {/* Design Reviewer Switcher Header */}
      {showMetaBar && (
        <header className="z-50 flex shrink-0 items-center justify-between border-b border-neutral-800 bg-neutral-950 px-4 py-2 text-xs">
          <div className="flex items-center gap-3">
            <Link
              href="/prototype"
              className="flex items-center gap-2 font-mono font-bold tracking-tight text-white hover:text-amber-400 transition-colors"
            >
              <span className="grid size-5 place-items-center rounded bg-amber-500 font-mono text-[10px] font-black text-black">
                OP
              </span>
              <span>OpsPilot v0.7.0 Design Lab</span>
            </Link>
            <span className="text-neutral-600">|</span>
            <div className="flex items-center gap-1 rounded bg-neutral-900 p-0.5">
              <Link
                href="/prototype"
                className={`rounded px-2.5 py-1 transition-all ${
                  isMasterHub
                    ? "bg-neutral-800 font-semibold text-white shadow-xs"
                    : "text-neutral-400 hover:text-neutral-200"
                }`}
              >
                Evaluation Matrix
              </Link>
              <Link
                href="/prototype/concept-a/home"
                className={`rounded px-2.5 py-1 transition-all ${
                  isConceptA
                    ? "bg-amber-600 font-semibold text-white shadow-xs"
                    : "text-neutral-400 hover:text-neutral-200"
                }`}
              >
                Concept A: Forensics Lab
              </Link>
              <Link
                href="/prototype/concept-b/home"
                className={`rounded px-2.5 py-1 transition-all ${
                  isConceptB
                    ? "bg-cyan-600 font-semibold text-white shadow-xs"
                    : "text-neutral-400 hover:text-neutral-200"
                }`}
              >
                Concept B: Flight Recorder
              </Link>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="hidden text-[11px] text-neutral-400 md:inline">
              {isConceptA && "Concept A: Warm Editorial • Evidence Dossier • Light-First"}
              {isConceptB && "Concept B: Cockpit Telemetry • Black Box Tape • Multi-Sensor"}
              {isMasterHub && "Side-by-side Architectural & Visual Identity Evaluation"}
            </span>
            <Link
              href="/"
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-[11px] text-neutral-300 hover:bg-neutral-800 transition-colors"
              title="Return to production v0.6.0 application"
            >
              ← Back to App
            </Link>
            <button
              onClick={() => setShowMetaBar(false)}
              className="text-neutral-500 hover:text-neutral-300"
              title="Hide switcher for clean screenshot capture"
            >
              ✕
            </button>
          </div>
        </header>
      )}

      {/* Floating restore pill if meta bar is hidden */}
      {!showMetaBar && (
        <button
          onClick={() => setShowMetaBar(true)}
          className="fixed bottom-3 right-3 z-50 rounded-full border border-neutral-700 bg-neutral-900/90 px-3 py-1.5 text-xs font-mono text-neutral-300 shadow-xl backdrop-blur-md hover:bg-neutral-800"
        >
          ⚙ OpsPilot Design Lab Switcher
        </button>
      )}

      {/* Interactive Prototype Viewport */}
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
