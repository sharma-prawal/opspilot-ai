"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/incidents", label: "Incidents" },
  { href: "/approvals", label: "Approvals" },
  { href: "/knowledge", label: "Knowledge" },
];

export function Nav() {
  const path = usePathname();
  const pending = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => api.approvals("pending"), refetchInterval: 5000 });
  const count = pending.data?.length ?? 0;
  return (
    <nav aria-label="Primary" className="flex flex-wrap items-center gap-1">
      {LINKS.map((l) => {
        const active = l.href === "/" ? path === "/" : path.startsWith(l.href) || (l.href === "/incidents" && path.startsWith("/investigations"));
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-2.5 py-1.5 text-sm font-medium ${active ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}
          >
            {l.label}
            {l.href === "/approvals" && count > 0 && (
              <span className="ml-1.5 rounded-full bg-warn px-1.5 py-px text-[11px] font-semibold text-white tabular-nums">{count}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
