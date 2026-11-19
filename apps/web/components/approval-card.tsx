"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, getSession } from "@/lib/api";
import { humanize, utcTime } from "@/lib/format";
import type { ActionRequest } from "@/lib/types";
import { Badge, Button, ErrorNote, KV, StatusBadge } from "./ui";

function useSession(): { sub?: string; role?: string } {
  const q = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
    staleTime: 60_000,
  });
  return q.data ?? {};
}

export function ApprovalCard({
  action,
  showLink = false,
}: {
  action: ActionRequest;
  showLink?: boolean;
}) {
  const qc = useQueryClient();
  const session = useSession();
  const canDecide = session.role === "operator";
  const [comment, setComment] = useState("");

  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api.decide(action.id, {
        decision,
        params_hash: action.params_hash,
        comment: comment || undefined,
      }),
    onSuccess: () => qc.invalidateQueries(),
  });

  const pending = action.status === "pending";
  const riskTone =
    action.risk === "high"
      ? "danger"
      : action.risk === "medium"
      ? "warn"
      : "neutral";

  return (
    <div className="rounded-xl border border-border bg-panel-2/70 p-4 shadow-xs transition-all">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/80 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-bold text-accent">
            {action.action_type}
          </span>
          <Badge tone={riskTone}>risk: {action.risk}</Badge>
          <StatusBadge status={action.status} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="cyan">simulated sandbox</Badge>
          <span className="text-[11px] font-mono text-muted">
            ID: {action.id.slice(0, 8)}
          </span>
        </div>
      </div>

      <div className="mt-3">
        <KV
          dense
          items={[
            ...Object.entries(action.parameters).map(
              ([k, v]) =>
                [
                  humanize(k),
                  <code key={k} className="font-mono text-xs font-semibold text-text">
                    {v}
                  </code>,
                ] as [string, React.ReactNode]
            ),
            ["Rationale", action.rationale || "—"],
            [
              "Params hash",
              <code
                key="h"
                className="font-mono text-xs text-muted"
                title={action.params_hash}
              >
                {action.params_hash.slice(0, 16)}…
              </code>,
            ],
            ["Requested at", utcTime(action.requested_at)],
            ...(action.decided_by
              ? ([
                  [
                    "Decided",
                    `${
                      action.decision_comment ? `“${action.decision_comment}” — ` : ""
                    }${action.decided_by} at ${utcTime(action.decided_at)}`,
                  ],
                ] as [string, string][])
              : []),
            ...(action.verification
              ? ([
                  [
                    "Verification",
                    action.verification.recovered
                      ? `Recovered — ${action.verification.notes}`
                      : `Not recovered — ${action.verification.notes}`,
                  ],
                ] as [string, string][])
              : []),
          ]}
        />
      </div>

      {showLink && (
        <div className="mt-3 border-t border-border/80 pt-2 text-xs">
          <Link
            className="font-semibold text-accent hover:underline"
            href={`/investigations/${action.investigation_id}`}
          >
            Open investigation workspace →
          </Link>
        </div>
      )}

      {pending && (
        <form
          className="mt-4 space-y-3 rounded-lg border border-warn/30 bg-warn-soft/40 p-3.5"
          onSubmit={(e) => e.preventDefault()}
          aria-label="Approval decision"
        >
          <p className="text-xs leading-relaxed text-text-muted"><strong>Approve this exact action and its parameters.</strong> Execution is limited to the simulator.</p>
          <details className="compact-disclosure"><summary>How approval is enforced</summary><p className="mt-2 text-xs text-text-muted">The backend checks the pending action and workflow interrupt. A signed, expiring token binds approval to the action ID and parameter hash; the action server verifies it before execution. Lifetime is configured on the backend.</p></details>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <label className="flex-1 text-xs text-muted">
              <span className="font-medium text-text">Comment (optional)</span>
              <input
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                maxLength={1000}
                placeholder="Reason for approval or specific instructions..."
                className="mt-1 h-8.5 w-full rounded-md border border-border bg-panel px-3 text-xs text-text placeholder:text-muted/60 focus:border-accent focus:outline-hidden"
              />
            </label>
            <div className="text-xs text-muted sm:text-right">
              {canDecide ? (
                <span>
                  Deciding as <strong className="text-text">{session.sub}</strong>
                </span>
              ) : (
                <span className="text-danger font-medium">
                  Operator privilege required.
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={!canDecide || decide.isPending}
              onClick={() => decide.mutate("approve")}
            >
              {decide.isPending ? "Executing…" : "Approve & execute in sandbox"}
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              disabled={!canDecide || decide.isPending}
              onClick={() => decide.mutate("reject")}
            >
              Reject
            </Button>
          </div>
          <ErrorNote error={decide.error} />
        </form>
      )}
    </div>
  );
}
