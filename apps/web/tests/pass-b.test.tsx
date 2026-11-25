// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EvidenceInspector, evidenceSourceRef, HypothesisReview } from "../components/evidence-inspector";
import { coverageState, EvidenceCoverage } from "../components/evidence-coverage";
import { dataset, evidence, hypotheses, investigationId, at } from "../e2e-pass-b/fixtures";
import { api } from "../lib/api";
import type { Incident, Investigation } from "../lib/types";
import { InvestigationView } from "../app/investigations/[id]/view";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "22222222-2222-4222-8222-222222222222" }) }));
vi.mock("../lib/api", () => ({ api: {
  investigation: vi.fn(), incident: vi.fn(), evidence: vi.fn(), dataset: vi.fn(), actions: vi.fn(),
  events: vi.fn(), toolCalls: vi.fn(), report: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
} }));
const incident: Incident = { id: dataset.incident_id, reference: "SYNTHETIC-001", title: "Checkout errors", service: "checkout-api",
  status: "open", severity: "SEV2", evidence_source: "connector", description: "Synthetic", detected_at: at, created_at: at, environment_id: null };
const investigation: Investigation = { id: investigationId, incident_id: incident.id, status: "completed", current_step: "report",
  model: "synthetic-model", started_at: at, completed_at: at, created_at: at, updated_at: at, error: null, error_class: null,
  result: { rca: { summary: "Original model assertion preserved.", hypotheses, evidence_gaps: ["Deployment history unknown"],
    evidence_warnings: ["Unsupported causal claim remains unverified."] }, suggested_remediation: [], window: { start: dataset.summary.start!, end: at } } };

beforeEach(() => {
  vi.mocked(api.incident).mockResolvedValue(incident);
  vi.mocked(api.investigation).mockResolvedValue(investigation);
  vi.mocked(api.evidence).mockResolvedValue(evidence);
  vi.mocked(api.dataset).mockResolvedValue(dataset);
  vi.mocked(api.actions).mockResolvedValue([]);
  vi.mocked(api.events).mockResolvedValue([]);
  vi.mocked(api.toolCalls).mockResolvedValue([]);
  vi.mocked(api.report).mockResolvedValue({ markdown: "# Original report\nUnmodified model output", status: "completed" });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
function workspace() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><InvestigationView /></QueryClientProvider>);
}
it("keeps exact source references distinct from citation identifiers", () => {
  expect(evidenceSourceRef(evidence[1])).toBe("cloudwatch/lifecycle/checkout-api:entry 3");
  expect(evidenceSourceRef({ ...evidence[1], data: {} })).toBeNull();
});
it("opens supporting, contradicting and missing references without inventing records", () => {
  const select = vi.fn();
  render(<HypothesisReview hypotheses={hypotheses} evidence={evidence} selectedRank={1} selectedEvidenceId="ev-config" onHypothesis={vi.fn()} onEvidence={select} />);
  for (const id of ["ev-config", "ev-traffic", "ev-missing"]) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(id) }));
    expect(select).toHaveBeenLastCalledWith(id);
  }
  expect(screen.getByText("Corresponding evidence unavailable")).toBeDefined();
  expect(screen.getByRole("button", { name: /ev-config/ }).getAttribute("aria-pressed")).toBe("true");
});
it("distinguishes unique model citations from accessible records and updates when evidence becomes available", () => {
  const h = { ...hypotheses[0], supporting_evidence_ids: [...hypotheses[0].supporting_evidence_ids, "ev-config"],
    contradicting_evidence_ids: ["ev-traffic", "ev-unavailable-against", "ev-traffic"] };
  const props = { hypotheses: [h], selectedRank: 1, selectedEvidenceId: null, onHypothesis: vi.fn(), onEvidence: vi.fn() };
  const { rerender } = render(<HypothesisReview {...props} evidence={evidence} />);
  expect(screen.getByText("3 cited supports (2 accessible · 1 unavailable) · 2 cited contradictions (1 accessible · 1 unavailable)")).toBeDefined();
  rerender(<HypothesisReview {...props} evidence={[...evidence, { ...evidence[0], evidence_id: "ev-missing" }]} />);
  expect(screen.getByText("3 cited supports (3 accessible · 0 unavailable) · 2 cited contradictions (1 accessible · 1 unavailable)")).toBeDefined();
  expect(h.supporting_evidence_ids).toEqual([...hypotheses[0].supporting_evidence_ids, "ev-config"]);
});
it("synchronizes inspector relationship and retains raw details", () => {
  const props = { evidence, selectedId: "ev-config", hypothesis: hypotheses[0], onDismiss: vi.fn() };
  const { rerender } = render(<EvidenceInspector {...props} />);
  expect(screen.getByText("Supports hypothesis 1")).toBeDefined();
  expect(screen.getByText("cloudwatch/lifecycle/checkout-api:entry 3")).toBeDefined();
  expect(screen.getByText("First recorded occurrence (UTC)").nextElementSibling?.textContent).toBe("2026-11-20 11:55:00Z");
  fireEvent.click(screen.getByText("Raw evidence and citation details"));
  expect(screen.getByText(/"source_ref": "cloudwatch\/lifecycle/)).toBeDefined();
  rerender(<EvidenceInspector {...props} selectedId="ev-traffic" />);
  expect(screen.getByText("Contradicts hypothesis 1")).toBeDefined();
  expect(screen.getByText("Not recorded in this evidence item")).toBeDefined();
});
it("shows unavailable, loading and failed evidence states accurately", () => {
  const props = { evidence: [], selectedId: "ev-missing", hypothesis: hypotheses[0], onDismiss: vi.fn() };
  const { rerender } = render(<EvidenceInspector {...props} pending />);
  expect(screen.getByText("Loading evidence…")).toBeDefined();
  rerender(<EvidenceInspector {...props} error />);
  expect(screen.getByText(/Evidence collection unavailable/)).toBeDefined();
  rerender(<EvidenceInspector {...props} />);
  expect(screen.getByText(/No corresponding record was returned/)).toBeDefined();
});
it("announces selections, focuses the inspector and supports Escape", () => {
  const dismiss = vi.fn();
  render(<EvidenceInspector evidence={evidence} selectedId="ev-config" hypothesis={hypotheses[0]} onDismiss={dismiss} />);
  const heading = screen.getByRole("heading", { name: "Evidence inspector" });
  expect(document.activeElement).toBe(heading);
  expect(screen.getByRole("status").textContent).toContain("ev-config selected. Supports hypothesis 1");
  fireEvent.keyDown(heading, { key: "Escape" });
  expect(dismiss).toHaveBeenCalledOnce();
});
it("labels stored occurrence, anomaly and deployment times without conflating them", () => {
  render(<EvidenceInspector evidence={[{ ...evidence[1], data: { id: "source-42", first_seen: at, last_seen: at,
    onset: at, started_at: at, finished_at: at, changed_at: at, search_truncated: true } }]}
    selectedId="ev-config" hypothesis={hypotheses[0]} onDismiss={vi.fn()} />);
  for (const label of ["First recorded occurrence (UTC)", "Last recorded occurrence (UTC)", "Metric anomaly onset (UTC)",
    "Deployment started (UTC)", "Deployment finished (UTC)", "Configuration changed (UTC)"]) expect(screen.getByText(label)).toBeDefined();
  expect(screen.getByText("source-42")).toBeDefined();
  expect(screen.getByText(/Log search truncated/)).toBeDefined();
});
it("distinguishes collected, empty, partial, not attempted and unavailable queries", () => {
  expect(dataset.queries.map(coverageState)).toEqual(["No accessible matching records", "Not attempted", "Partial / limited", "Unavailable", "Collected", "No matching records returned"]);
  render(<EvidenceCoverage evidence={evidence} dataset={dataset} source="connector" gaps={["Unknown deployment history"]} />);
  expect(screen.getByText("No accessible matching records — access/coverage not independently verified.")).toBeDefined();
  expect(screen.getByText("Sampling coverage is limited; correlation is incomplete.")).toBeDefined();
  expect(screen.getByText("not_configured: No mapped resource", { exact: true })).toBeDefined();
  expect(screen.queryByText("No errors found")).toBeNull();
});
it("does not turn unavailable provenance into an empty successful query set", () => {
  render(<EvidenceCoverage source="connector" error />);
  expect(screen.getByText(/Collection completeness cannot be checked/)).toBeDefined();
  expect(screen.getByText("Collected record count unavailable")).toBeDefined();
});
it("presents incident source, historical state, snapshot window and export", async () => {
  workspace();
  await screen.findByRole("heading", { name: /SYNTHETIC-001: Checkout errors/ });
  expect(screen.getByText("checkout-api · open")).toBeDefined();
  expect(screen.getByText("2026-11-20 11:30:00Z → 2026-11-20 12:00:00Z")).toBeDefined();
  expect(screen.getByText("Historical evidence · not live operational health")).toBeDefined();
  expect(screen.getByRole("button", { name: "Export RCA report" })).toBeDefined();
  expect(screen.getByText(/Nothing executed; external recovery is unverified/)).toBeDefined();
  expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
});
it("keeps the hypothesis visible when citations select the shared inspector and restores focus", async () => {
  workspace();
  const citation = await within(screen.getByRole("region", { name: "Hypotheses and citations" })).findByRole("button", { name: /ev-config/ });
  citation.focus(); fireEvent.click(citation);
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Evidence inspector" })));
  expect(within(screen.getByRole("region", { name: "Hypotheses and citations" })).getByText(hypotheses[0].title)).toBeDefined();
  expect(screen.getByText("Supports hypothesis 1")).toBeDefined();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(document.activeElement).toBe(citation);
  expect(citation.getAttribute("aria-pressed")).toBe("false");
});
it("keeps warnings beside original hypothesis and summary text", async () => {
  workspace();
  await within(screen.getByRole("region", { name: "Hypotheses and citations" })).findByText(hypotheses[0].title);
  expect(screen.getByText(hypotheses[0].evidence_warnings![0])).toBeDefined();
  const summary = screen.getByText(/Model summary and report-reading notes/).closest("details")!;
  fireEvent.click(within(summary).getByText(/Model summary/));
  expect(within(summary).getByText("Original model assertion preserved.")).toBeDefined();
  expect(within(summary).getByText("Unsupported causal claim remains unverified.")).toBeDefined();
});
it("refocuses a repeated citation and falls back to the selected hypothesis after its trigger disappears", async () => {
  workspace();
  const review = within(screen.getByRole("region", { name: "Hypotheses and citations" }));
  const citation = await review.findByRole("button", { name: /ev-config/ });
  citation.focus(); fireEvent.click(citation);
  const heading = screen.getByRole("heading", { name: "Evidence inspector" });
  citation.focus(); fireEvent.click(citation);
  expect(document.activeElement).toBe(heading);
  const alternative = review.getByRole("button", { name: /Alternative · rank 2/ });
  fireEvent.click(alternative);
  fireEvent.click(screen.getByRole("button", { name: "Close inspector" }));
  expect(document.activeElement).toBe(alternative);
});
it("uses the same inspector from the collected-record list", async () => {
  workspace(); await within(screen.getByRole("region", { name: "Hypotheses and citations" })).findByText(hypotheses[0].title);
  fireEvent.click(screen.getByRole("button", { name: /Collected Evidence/ }));
  fireEvent.click(screen.getByRole("button", { name: "Cited only" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect ev-traffic" }));
  expect(screen.getByText("Contradicts hypothesis 1")).toBeDefined();
});
it("keeps simulator authorization unknown independently of successful execution and verification", async () => {
  vi.mocked(api.incident).mockResolvedValue({ ...incident, evidence_source: "simulator" });
  vi.mocked(api.investigation).mockResolvedValue({ ...investigation, result: { ...investigation.result,
    executions: [{ step: 1, status: "succeeded", message: "Synthetic", action_type: "restart_service" }],
    verification: { recovered: true, notes: "Synthetic sandbox verification" } } });
  vi.mocked(api.actions).mockResolvedValue([{ id: "a", investigation_id: investigationId, incident_id: incident.id,
    action_type: "restart_service", parameters: {}, params_hash: "abc", rationale: "Synthetic", risk: "low", status: "succeeded",
    authorization: null, requested_at: at, decided_at: at, decided_by: "execution-only", decision_comment: null, executed_at: at,
    execution_result: {}, verification: null }]);
  workspace();
  const sequence = await screen.findByRole("list", { name: "Remediation decision sequence" });
  await waitFor(() => expect(sequence.textContent).toContain("Authorization unknown"));
  expect(sequence.textContent).toContain("1 simulator results");
  expect(sequence.textContent).toContain("Simulator recovery verified");
  expect(api.dataset).not.toHaveBeenCalled();
});
