"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Button, ErrorNote } from "./ui";

export function SimulateButton({ scenario = "INC-001" }: { scenario?: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const m = useMutation({
    mutationFn: () => api.simulate(scenario),
    onSuccess: (inc) => { qc.invalidateQueries({ queryKey: ["incidents"] }); router.push(`/incidents/${inc.id}`); },
  });
  return (
    <div className="flex items-center gap-2">
      <Button variant="primary" onClick={() => m.mutate()} disabled={m.isPending}>
        {m.isPending ? "Generating…" : `Simulate ${scenario}`}
      </Button>
      <ErrorNote error={m.error} />
    </div>
  );
}
