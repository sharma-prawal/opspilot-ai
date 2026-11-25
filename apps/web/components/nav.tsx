"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, clearSession, getSession } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Overview", sec: "01" },
  { href: "/incidents", label: "Incidents", sec: "02" },
  { href: "/incidents/new", label: "Analyze data", sec: "03" },
  { href: "/architecture", label: "Architecture", sec: "04" },
  { href: "/integrations", label: "Integrations", sec: "05" },
  { href: "/guide", label: "Guide", sec: "06" },
  { href: "/safety", label: "Safety", sec: "07" },
  { href: "/approvals", label: "Approvals", sec: "08" },
  { href: "/knowledge", label: "Knowledge", sec: "09" },
];

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const [openPath, setOpenPath] = useState<string | null>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const open = openPath === path;
  const qc = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
    staleTime: 60_000,
  });
  const signedIn = !!session.data?.authenticated;
  const pending = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => api.approvals("pending"),
    refetchInterval: 5000,
    enabled: signedIn,
  });

  async function signOut() {
    const csrf = session.data?.csrf ?? "";
    await fetch("/api/session", {
      method: "DELETE",
      headers: { "x-opspilot-csrf": csrf },
    });
    clearSession();
    qc.clear();
    router.replace("/login");
  }

  const count = pending.data?.length ?? 0;

  return (
    <nav aria-label="Primary" className="primary-nav" onKeyDown={(event) => {
      if (event.key === "Escape" && open) {
        event.preventDefault(); setOpenPath(null); toggle.current?.focus();
      }
    }}>
      <button ref={toggle} type="button" className="nav-toggle" aria-expanded={open}
        aria-controls="primary-navigation-links" onClick={() => setOpenPath(open ? null : path)}>
        {open ? "Close navigation" : "Open navigation"} · {LINKS.find(l => l.href === path)?.label ?? (path.startsWith("/investigations") || path.startsWith("/incidents/") ? "Incidents" : "Navigation")}
      </button>
      <div id="primary-navigation-links" className="primary-nav-links" data-open={open}>
      {LINKS.map((l) => {
        const active =
          l.href === "/"
            ? path === "/"
            : l.href === "/incidents"
            ? (path.startsWith("/incidents") && !path.startsWith("/incidents/new")) ||
              path.startsWith("/investigations")
            : path.startsWith(l.href);
        return (
          <Link
            key={l.href}
            onClick={() => setOpenPath(null)}
            href={l.href}
            aria-label={l.label}
            aria-current={active ? "page" : undefined}
            className={`group relative rounded-[4px] px-2.5 py-1.5 text-xs font-medium transition-all ${
              active
                ? "bg-text text-bg font-semibold shadow-2xs"
                : "text-text-muted hover:bg-panel-2 hover:text-text"
            }`}
          >
            <span>{l.label}</span>
            {l.href === "/approvals" && count > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center rounded-full bg-warn px-1.5 py-0.2 font-mono text-[10px] font-bold text-white tabular-nums">
                {count}
              </span>
            )}
          </Link>
        );
      })}
      {signedIn && (
        <span className="ml-2 flex items-center gap-2 border-l border-border pl-3 font-mono text-xs text-text-muted">
          <span className="flex items-center gap-1.5 font-medium text-text">
            <span aria-hidden className="size-2 rounded-full bg-success" />
            {session.data?.sub} · {session.data?.role}
          </span>
          <button
            onClick={signOut}
            className="rounded px-1.5 py-0.5 text-xs text-muted hover:text-danger hover:bg-panel-2 transition-colors cursor-pointer"
          >
            Sign out
          </button>
        </span>
      )}
      </div>
    </nav>
  );
}
