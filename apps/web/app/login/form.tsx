"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { clearSession } from "@/lib/api";
import { Button, Card, ErrorNote, PageHeader } from "@/components/ui";

export function LoginForm() {
  const router = useRouter();
  const qc = useQueryClient();
  const next = useSearchParams().get("next") || "/";
  const [name, setName] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, passphrase }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? "sign-in failed");
      clearSession();
      qc.clear(); // never reuse data cached under a previous identity
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-8">
      <PageHeader
        title="Sign in to OpsPilot AI"
        subtitle="Local operator authorization for incident triage and sandbox remediation."
      />
      <Card title="Operator Authentication">
        <form onSubmit={submit} className="space-y-4" aria-label="Sign in">
          <label className="flex flex-col gap-1 text-xs font-semibold text-text">
            <span>Name</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="username"
              placeholder="e.g. demo-operator"
              className="h-9 rounded-lg border border-border bg-panel-2 px-3 text-xs text-text placeholder:text-muted/60 focus:border-accent focus:outline-hidden"
            />
          </label>

          <label className="flex flex-col gap-1 text-xs font-semibold text-text">
            <span>Passphrase</span>
            <input
              required
              type="password"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              autoComplete="current-password"
              placeholder="Configured in .env"
              className="h-9 rounded-lg border border-border bg-panel-2 px-3 text-xs text-text placeholder:text-muted/60 focus:border-accent focus:outline-hidden"
            />
          </label>

          <div className="rounded-md border border-border/80 bg-panel-2/40 p-2.5 text-[11px] text-muted">
            Operator privileges grant ability to approve state-changing sandbox remediations. The passphrase is configured in your local <code className="font-mono text-text">.env</code> file.
          </div>

          <Button
            variant="primary"
            size="md"
            type="submit"
            disabled={pending}
            className="w-full"
          >
            {pending ? "Signing in…" : "Sign in"}
          </Button>

          <ErrorNote error={error} />
        </form>
      </Card>
    </div>
  );
}
