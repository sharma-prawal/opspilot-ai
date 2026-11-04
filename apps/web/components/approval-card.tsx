"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { humanize, utcTime } from "@/lib/format";
import type { ActionRequest } from "@/lib/types";
import { Badge, Button, ErrorNote, KV, StatusBadge } from "./ui";

const OPERATOR_KEY = "opspilot.operator";
const listeners = new Set<() => void>();

function readOperator(): string {
  try { return localStorage.getItem(OPERATOR_KEY) ?? ""; } catch { return ""; }
}

/** Operator display name, remembered per browser (a convenience; identity is not trusted from it). */
function useOperator(): [string, (v: string) => void] {
  const name = useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    readOperator,
    () => "",
  );
  const update = (v: string) => {
    try { localStorage.setItem(OPERATOR_KEY, v); } catch { /* storage unavailable */ }
    listeners.forEach((l) => l());
  };
  return [name, update];
}

export function ApprovalCard({ action, showLink = false }: { action: ActionRequest; showLink?: boolean }) {
  const qc = useQueryClient();
  const [operator, setOperator] = useOperator();
  const [comment, setComment] = useState("");
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api.decide(action.id, { decision, params_hash: action.params_hash, decided_by: operator.trim(), comment: comment || undefined }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const pending = action.status === "pending";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">{action.action_type}</span>
        <Badge tone={action.risk === "high" ? "danger" : action.risk === "medium" ? "warn" : "neutral"}>risk: {action.risk}</Badge>
        <StatusBadge status={action.status} />
        <Badge>sandbox only</Badge>
      </div>
      <KV items={[
        ...Object.entries(action.parameters).map(([k, v]) => [humanize(k), <code key={k} className="font-mono text-xs">{v}</code>] as [string, React.ReactNode]),
        ["Rationale", action.rationale || "—"],
        ["Action ID", <code key="id" className="font-mono text-xs">{action.id}</code>],
        ["Params hash", <code key="h" className="font-mono text-xs" title={action.params_hash}>{action.params_hash.slice(0, 16)}…</code>],
        ["Requested", utcTime(action.requested_at)],
        ...(action.decided_by ? [["Decided", `${action.decision_comment ? `“${action.decision_comment}” — ` : ""}${action.decided_by} at ${utcTime(action.decided_at)}`] as [string, string]] : []),
        ...(action.verification ? [["Verification", action.verification.recovered ? `Recovered — ${action.verification.notes}` : `Not recovered — ${action.verification.notes}`] as [string, string]] : []),
      ]} />
      {showLink && <Link className="text-sm text-accent hover:underline" href={`/investigations/${action.investigation_id}`}>Open investigation →</Link>}
      {pending && (
        <form
          className="space-y-2 rounded-md border border-border bg-panel-2 p-3"
          onSubmit={(e) => e.preventDefault()}
          aria-label="Approval decision"
        >
          <p className="text-xs text-muted">
            The backend verifies that this exact action (params hash) is still pending and that the workflow is paused on it.
            Approval issues a signed, expiring token that the sandbox executor checks independently.
          </p>
          <div className="flex flex-wrap gap-2">
            <label className="flex flex-col text-xs text-muted">
              Operator
              <input required value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="your name"
                className="mt-1 h-8 w-44 rounded-md border border-border bg-panel px-2 text-sm text-text" />
            </label>
            <label className="flex min-w-48 flex-1 flex-col text-xs text-muted">
              Comment (optional)
              <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000}
                className="mt-1 h-8 rounded-md border border-border bg-panel px-2 text-sm text-text" />
            </label>
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="primary" disabled={!operator.trim() || decide.isPending} onClick={() => decide.mutate("approve")}>
              Approve &amp; execute in sandbox
            </Button>
            <Button type="button" variant="danger" disabled={!operator.trim() || decide.isPending} onClick={() => decide.mutate("reject")}>
              Reject
            </Button>
          </div>
          <ErrorNote error={decide.error} />
        </form>
      )}
    </div>
  );
}
