"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, clearSession, getSession } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/incidents", label: "Incidents" },
  { href: "/architecture", label: "Architecture" },
  { href: "/integrations", label: "Integrations" },
  { href: "/guide", label: "Guide" },
  { href: "/safety", label: "Safety" },
  { href: "/approvals", label: "Approvals" },
  { href: "/knowledge", label: "Knowledge" },
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
            : path.startsWith(l.href) ||
              (l.href === "/incidents" && path.startsWith("/investigations"));
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`relative rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
              active
                ? "bg-panel-2 text-text font-semibold shadow-xs"
                : "text-muted hover:bg-panel-2/50 hover:text-text"
            }`}
          >
            {l.label}
            {l.href === "/approvals" && count > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center rounded-full bg-warn px-1.5 py-0.2 text-[10px] font-bold text-black tabular-nums">
                {count}
              </span>
            )}
            {active && (
              <span
                aria-hidden
                className="absolute inset-x-2 -bottom-1 h-0.5 rounded-full bg-accent"
              />
            )}
          </Link>
        );
      })}
      {signedIn && (
        <span className="ml-2 flex items-center gap-2.5 border-l border-border pl-3 text-xs text-muted">
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
