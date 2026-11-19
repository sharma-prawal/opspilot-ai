"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/prototype/concept-a/home", label: "Investigation Intake", num: "01" },
  { href: "/prototype/concept-a/workbench", label: "Active Dossier", num: "02" },
  { href: "/prototype/concept-a/explorer", label: "Causal Exhibit Explorer", num: "03" },
  { href: "/prototype/concept-a/architecture", label: "System Cartography", num: "04" },
  { href: "/prototype/concept-a/guide", label: "Forensic Field Guide", num: "05" },
];

export default function ConceptALayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="concept-forensics min-h-screen text-[#16191D]">
      {/* Editorial Masthead */}
      <header className="border-b border-[#E2DFD5] bg-[#FBFBF8] px-6 py-4">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex size-10 items-center justify-center rounded border border-[#C8C4B7] bg-[#F4F3EC] shadow-inner">
              <span className="font-serif-heading text-lg font-bold text-[#C05621]">OP</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#78828F]">
                  ARCHIVAL RECORD &amp; SRE AUDITING
                </span>
                <span className="h-2 w-px bg-[#C8C4B7]" />
                <span className="rounded bg-[#EFF6FF] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[#1E3A8A]">
                  CONCEPT A: FORENSICS LAB
                </span>
              </div>
              <h1 className="font-serif-heading text-xl font-bold tracking-tight text-[#16191D]">
                OpsPilot Incident Forensics Laboratory
              </h1>
            </div>
          </div>

          {/* Dossier status & active operator */}
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <div className="rounded border border-[#E2DFD5] bg-white px-3 py-1.5 font-mono text-[11px] text-[#4A525D]">
              <span className="text-[#78828F]">CHAIN OF CUSTODY:</span>{" "}
              <strong className="text-[#047857]">VERIFIED (CRYPTOGRAPHIC)</strong>
            </div>
            <div className="rounded border border-[#E2DFD5] bg-white px-3 py-1.5 font-mono text-[11px] text-[#4A525D]">
              <span className="text-[#78828F]">LOCAL MODEL:</span>{" "}
              <strong className="text-[#16191D]">QWEN3-8B (OLLAMA 127.0.0.1)</strong>
            </div>
          </div>
        </div>

        {/* Editorial Navigation Tabs */}
        <nav className="mx-auto mt-4 flex max-w-7xl border-t border-[#EAE7DF] pt-3 text-xs">
          <div className="flex flex-wrap gap-1">
            {NAV_ITEMS.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`group flex items-center gap-2 rounded px-3 py-1.5 font-medium transition-all ${
                    isActive
                      ? "bg-[#16191D] text-white shadow-xs"
                      : "text-[#4A525D] hover:bg-[#F4F3EC] hover:text-[#16191D]"
                  }`}
                >
                  <span
                    className={`font-mono text-[10px] ${
                      isActive ? "text-[#C05621]" : "text-[#78828F]"
                    }`}
                  >
                    §{item.num}
                  </span>
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </nav>
      </header>

      {/* Main Content Area */}
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">{children}</div>
    </div>
  );
}
