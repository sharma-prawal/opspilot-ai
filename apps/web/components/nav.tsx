"use client";

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
    <nav aria-label="Primary" className="flex flex-wrap items-center gap-1">
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
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`group relative rounded-[4px] px-2.5 py-1.5 text-xs font-medium transition-all ${
              active
                ? "bg-text text-bg font-semibold shadow-2xs"
                : "text-text-muted hover:bg-panel-2 hover:text-text"
            }`}
          >
            <span
              className={`font-mono text-[10px] mr-1.5 ${
                active ? "text-accent" : "text-muted"
              }`}
            >
              §{l.sec}
            </span>
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
    </nav>
  );
}
