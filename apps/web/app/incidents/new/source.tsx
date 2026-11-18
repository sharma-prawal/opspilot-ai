"use client";

import { useSearchParams } from "next/navigation";
import { ConnectedView } from "./connected";
import { UploadView } from "./view";

/** Picks the evidence source from ?source= (rendered inside <Suspense> because it reads the search params). */
export function NewIncidentView() {
  const source = useSearchParams().get("source");
  return source === "connected" ? <ConnectedView /> : <UploadView />;
}
