import { Suspense } from "react";
import { NewIncidentView } from "./source";

export const metadata = { title: "New read-only incident · OpsPilot AI" };

// Client-only workflow (files are read in the browser; connector previews go through the BFF); stream it in after
// the static shell. ?source=connected selects Loki/Prometheus (v0.6) or Datadog (v0.9), otherwise file upload (v0.5).
export default function UploadIncidentPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <NewIncidentView />
    </Suspense>
  );
}
