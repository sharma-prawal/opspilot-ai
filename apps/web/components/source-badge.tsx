import { Badge } from "./ui";
import type { EvidenceSource } from "@/lib/types";

/** Demo (simulator), user-uploaded files (v0.5) or a connected-telemetry snapshot (v0.6), wherever an incident appears. */
export function SourceBadge({ source }: { source: EvidenceSource | null | undefined }) {
  if (source === "connector")
    return (
      <Badge tone="cyan" className="text-[10px]">
        <span aria-hidden>⇄</span> Connected telemetry
      </Badge>
    );
  return source === "upload" ? (
    <Badge tone="purple" className="text-[10px]">
      <span aria-hidden>⇪</span> Uploaded evidence
    </Badge>
  ) : (
    <Badge tone="neutral" className="text-[10px]">
      <span aria-hidden>◇</span> Demo · simulator
    </Badge>
  );
}
