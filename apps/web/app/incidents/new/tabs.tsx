"use client";

import Link from "next/link";

/** Switch between the two read-only evidence sources of a new incident (v0.5 files, v0.6 connectors). */
export function SourceTabs({ active }: { active: "upload" | "connected" }) {
  const tabs = [
    { key: "upload", href: "/incidents/new", label: "Upload files", hint: ".log .txt .json .csv" },
    { key: "connected", href: "/incidents/new?source=connected", label: "Connected telemetry", hint: "Loki · Prometheus · Datadog · Azure Monitor" },
  ] as const;
  return (
    <nav aria-label="Evidence source" className="flex flex-wrap gap-2">
      {tabs.map((t) => (
        <Link key={t.key} href={t.href} aria-current={active === t.key ? "page" : undefined}
          className={`rounded-lg border px-3 py-2 text-xs transition-colors ${
            active === t.key ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:border-border-strong hover:text-text"
          }`}>
          <span className="font-semibold">{t.label}</span> <span className="opacity-70">· {t.hint}</span>
        </Link>
      ))}
    </nav>
  );
}
