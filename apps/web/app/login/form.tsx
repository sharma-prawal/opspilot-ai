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
      const res = await fetch("/api/session", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, passphrase }) });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? "sign-in failed");
      clearSession();
      qc.clear(); // never reuse data cached under a previous (or no) identity
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <PageHeader title="Sign in" subtitle="Local operator access. The passphrase is configured in .env." />
      <Card>
        <form onSubmit={submit} className="space-y-3" aria-label="Sign in">
          <label className="flex flex-col text-sm">Name
            <input required value={name} onChange={(e) => setName(e.target.value)} autoComplete="username"
              className="mt-1 h-9 rounded-md border border-border bg-panel px-2" />
          </label>
          <label className="flex flex-col text-sm">Passphrase
            <input required type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)}
              autoComplete="current-password" className="mt-1 h-9 rounded-md border border-border bg-panel px-2" />
          </label>
          <Button variant="primary" type="submit" disabled={pending} className="w-full">{pending ? "Signing in…" : "Sign in"}</Button>
          <ErrorNote error={error} />
        </form>
      </Card>
    </div>
  );
}
