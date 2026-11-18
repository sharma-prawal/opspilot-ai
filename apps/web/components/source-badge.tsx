import { Badge } from "./ui";
import type { EvidenceSource } from "@/lib/types";

/** Demo (simulator) versus user-uploaded evidence, shown wherever an incident appears (v0.5). */
export function SourceBadge({ source }: { source: EvidenceSource | null | undefined }) {
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
