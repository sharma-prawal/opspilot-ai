"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Button, ErrorNote } from "./ui";

export function SimulateButton({ scenario: initial = "INC-001", picker = false }: { scenario?: string; picker?: boolean }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [scenario, setScenario] = useState(initial);
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios, enabled: picker });
  const m = useMutation({
    mutationFn: () => api.simulate(scenario),
    onSuccess: (inc) => { qc.invalidateQueries({ queryKey: ["incidents"] }); router.push(`/incidents/${inc.id}`); },
  });
  return (
    <div className="flex items-center gap-2">
      {picker && (
        <>
          <label htmlFor="scenario" className="sr-only">Scenario</label>
          <select id="scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}
            className="h-8 max-w-64 rounded-md border border-border bg-panel px-2 text-sm">
            {(scenarios.data ?? [{ key: initial, title: "" }]).map((s) => (
              <option key={s.key} value={s.key}>{s.key}{s.title ? ` — ${s.title}` : ""}</option>
            ))}
          </select>
        </>
      )}
      <Button variant="primary" onClick={() => m.mutate()} disabled={m.isPending}>
        {m.isPending ? "Generating…" : picker ? "Simulate" : `Simulate ${scenario}`}
      </Button>
      <ErrorNote error={m.error} />
    </div>
  );
}
