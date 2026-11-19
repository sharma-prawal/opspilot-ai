// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Composition,
  DecisionFlow,
  EvidenceMap,
  HypothesisComparison,
  MetricComparison,
  SourceTimeline,
} from "../components/visuals";
import { sourceCounts, metricValues, sourceChronology } from "../lib/visuals";
import { SourceBadge } from "../components/source-badge";
import type { Evidence, Hypothesis, Incident } from "../lib/types";

afterEach(cleanup);
const metric: Evidence = {
  evidence_id: "ev-metric",
  kind: "metric_anomaly",
  source_tool: "query_metrics",
  collected_by: "telemetry",
  service: "api",
  summary: "Observed error ratio",
  data: {
    metric: "5xx_ratio",
    baseline: 0,
    extreme: 0.4,
    current: 0.3,
    unit: "ratio",
  },
  citation: null,
  relevance: 0.9,
  observed_at: "2026-11-19T12:00:00Z",
};
const hyp: Hypothesis = {
  rank: 1,
  title: "Schema incompatibility",
  category: "deployment",
  description: "Review the cited source.",
  confidence: 0.9,
  supporting_evidence_ids: ["ev-metric", "missing"],
  contradicting_evidence_ids: [],
};

describe("data fidelity", () => {
  it("keeps unknown sources separate from simulator", () => {
    expect(
      sourceCounts([
        { evidence_source: "upload" },
        { evidence_source: undefined },
      ] as Incident[]).map((i) => i.count),
    ).toEqual([0, 1, 0, 1]);
  });
  it("preserves zero, excludes non-numeric and non-finite metric values", () => {
    expect(
      metricValues({
        ...metric,
        data: { baseline: 0, current: "12", peak: Infinity },
      }),
    ).toEqual([{ label: "Baseline", value: 0 }]);
  });
  it("orders real timestamps and excludes invalid source times", () => {
    expect(
      sourceChronology([
        { ...metric, observed_at: "bad" },
        {
          ...metric,
          evidence_id: "older",
          observed_at: "2026-11-18T12:00:00Z",
        },
        metric,
      ]).map((e) => e.evidence_id),
    ).toEqual(["older", "ev-metric"]);
  });
  it("renders unknown source explicitly", () => {
    render(<SourceBadge source={undefined} />);
    expect(screen.getByText("Source unavailable")).toBeDefined();
  });
});

describe("visual interactions", () => {
  it("distinguishes unavailable and empty composition", () => {
    const { rerender } = render(<Composition label="Evidence" />);
    expect(screen.getByText(/Evidence unavailable/)).toBeDefined();
    rerender(<Composition label="Evidence" items={[]} />);
    expect(screen.getByText(/No records yet/)).toBeDefined();
  });
  it("opens the selected evidence category", () => {
    const select = vi.fn();
    render(
      <Composition
        label="Evidence"
        items={[{ key: "Logs", label: "Logs", count: 4 }]}
        onSelect={select}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Logs/ }));
    expect(select).toHaveBeenCalledWith("Logs");
  });
  it("shows source values with units and an accessible alternative", () => {
    const select = vi.fn();
    render(<MetricComparison evidence={[metric]} onSelect={select} />);
    expect(screen.getByText("0%")).toBeDefined();
    expect(screen.getByText("40%")).toBeDefined();
    expect(screen.getByText("30%")).toBeDefined();
    expect(screen.getByText(/not a time series/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "5xx_ratio" }));
    expect(select).toHaveBeenCalledWith("ev-metric");
  });
  it("does not draw series from absent numeric summaries", () => {
    render(<MetricComparison evidence={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/No numeric metric summaries/)).toBeDefined();
  });
  it("only counts persisted hypothesis links and reveals unavailable references", () => {
    const select = vi.fn();
    const evidenceSelect = vi.fn();
    render(
      <HypothesisComparison
        hypotheses={[hyp]}
        evidence={[metric]}
        selected={1}
        onSelect={select}
        onEvidence={evidenceSelect}
      />,
    );
    expect(screen.getByText("1 supporting")).toBeDefined();
    expect(
      screen.getByText(/Some referenced evidence is unavailable/),
    ).toBeDefined();
    fireEvent.click(
      screen.getByRole("button", { name: /Schema incompatibility/ }),
    );
    expect(select).toHaveBeenCalledWith(1);
    fireEvent.click(
      screen.getByRole("button", { name: /ev-metric · supports/ }),
    );
    expect(evidenceSelect).toHaveBeenCalledWith("ev-metric");
  });
  it("links evidence relationships without claiming causal proof", () => {
    const select = vi.fn();
    render(
      <EvidenceMap hypothesis={hyp} evidence={[metric]} onSelect={select} />,
    );
    expect(screen.getByText(/not causal proof/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /Metrics/ }));
    expect(select).toHaveBeenCalledWith("ev-metric");
  });
  it("preserves exact source timestamp when selecting chronology", () => {
    const select = vi.fn();
    render(<SourceTimeline evidence={[metric]} onSelect={select} />);
    expect(screen.getByText("2026-11-19 12:00:00Z")).toBeDefined();
    fireEvent.click(screen.getByRole("button"));
    expect(select).toHaveBeenCalledWith("ev-metric");
  });
  it("does not imply approval, execution or verification when no plan ran", () => {
    render(
      <DecisionFlow
        result={{ rejected_proposals: [{ proposal: {}, reason: "Unsafe" }] }}
      />,
    );
    expect(screen.getByText("Blocked")).toBeDefined();
    expect(screen.getByText("No approval recorded")).toBeDefined();
    expect(screen.getByText("Not executed")).toBeDefined();
    expect(screen.getByText("Not verified")).toBeDefined();
  });
  it("renders read-only advice without an execution sequence", () => {
    render(
      <DecisionFlow
        readOnly
        result={{
          verification: {
            recovered: true,
            notes: "must not be shown as simulator recovery",
          },
        }}
      />,
    );
    expect(screen.getByText("Nothing executed")).toBeDefined();
    expect(screen.queryByText("Simulator recovery verified")).toBeNull();
  });
});
