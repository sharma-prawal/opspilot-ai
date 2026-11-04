import { Suspense } from "react";
import { IncidentView } from "./view";

// The route param is runtime data: stream the client view in after the static shell.
export default function IncidentPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading incident…</p>}>
      <IncidentView />
    </Suspense>
  );
}
