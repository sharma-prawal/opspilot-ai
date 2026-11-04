import { Suspense } from "react";
import { InvestigationView } from "./view";

export default function InvestigationPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading investigation…</p>}>
      <InvestigationView />
    </Suspense>
  );
}
