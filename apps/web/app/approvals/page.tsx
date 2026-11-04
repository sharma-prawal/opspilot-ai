"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApprovalCard } from "@/components/approval-card";
import { Card, Empty, ErrorNote, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

const FILTERS = ["pending", "all"] as const;

export default function ApprovalsPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("pending");
  const q = useQuery({ queryKey: ["approvals", filter], queryFn: () => api.approvals(filter), refetchInterval: 4000 });
  return (
    <>
      <PageHeader title="Action approvals" subtitle="Every state-changing action requires an explicit, backend-verified decision."
        actions={
          <div role="group" aria-label="Filter" className="flex gap-1">
            {FILTERS.map((f) => (
              <button key={f} aria-pressed={filter === f} onClick={() => setFilter(f)}
                className={`rounded-md border px-2.5 py-1 text-sm ${filter === f ? "border-accent bg-accent-soft text-accent" : "border-border text-muted"}`}>
                {f}
              </button>
            ))}
          </div>
        } />
      <ErrorNote error={q.error} />
      {q.data?.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {q.data.map((a) => <Card key={a.id}><ApprovalCard action={a} showLink /></Card>)}
        </div>
      ) : <Card><Empty>{filter === "pending" ? "No actions awaiting approval." : "No actions yet."}</Empty></Card>}
    </>
  );
}
