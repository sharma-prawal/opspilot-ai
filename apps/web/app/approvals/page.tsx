"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApprovalCard } from "@/components/approval-card";
import { Card, Empty, ErrorNote, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

const FILTERS = ["pending", "all"] as const;

export default function ApprovalsPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("pending");
  const q = useQuery({
    queryKey: ["approvals", filter],
    queryFn: () => api.approvals(filter),
    refetchInterval: 4000,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Action approvals"
        subtitle="Every state-changing action requires an explicit, authenticated operator decision verified by the backend."
        actions={
          <div role="group" aria-label="Filter" className="flex items-center gap-1.5 rounded-lg border border-border bg-panel p-1">
            {FILTERS.map((f) => (
              <button
                key={f}
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
                className={`rounded-md px-3 py-1 text-xs font-semibold capitalize transition-all cursor-pointer ${
                  filter === f
                    ? "bg-accent text-white shadow-xs"
                    : "text-muted hover:text-text"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        }
      />
      <ErrorNote error={q.error} />
      {q.data?.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {q.data.map((a) => (
            <Card key={a.id}>
              <ApprovalCard action={a} showLink />
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <Empty>
            {filter === "pending"
              ? "No actions awaiting approval. When an agent formulates an action, it will appear here for review."
              : "No actions recorded yet."}
          </Empty>
        </Card>
      )}
    </div>
  );
}
