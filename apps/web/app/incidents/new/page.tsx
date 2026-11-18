import { Suspense } from "react";
import { UploadView } from "./view";

export const metadata = { title: "Analyze incident files · OpsPilot AI" };

// Client-only workflow (file reading happens in the browser); stream it in after the static shell.
export default function UploadIncidentPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <UploadView />
    </Suspense>
  );
}
