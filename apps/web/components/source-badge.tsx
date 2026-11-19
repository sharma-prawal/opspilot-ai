import { Badge } from "./ui";
import { SignalIcon } from "./brand";
import type { EvidenceSource } from "@/lib/types";
export function SourceBadge({
  source,
}: {
  source: EvidenceSource | null | undefined;
}) {
  if (!source) return <Badge>Source unavailable</Badge>;
  return (
    <Badge
      tone={
        source === "connector"
          ? "info"
          : source === "upload"
            ? "purple"
            : "neutral"
      }
      className="text-[10px]"
    >
      <SignalIcon
        name={
          source === "connector"
            ? "connector"
            : source === "upload"
              ? "upload"
              : "simulator"
        }
        className="size-3"
      />
      {source === "connector"
        ? "Connected telemetry"
        : source === "upload"
          ? "Uploaded evidence"
          : "Demo · simulator"}
    </Badge>
  );
}
