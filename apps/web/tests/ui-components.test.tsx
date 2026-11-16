// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  Badge,
  ConfidenceBar,
  SeverityBadge,
  StatCard,
  StatusBadge,
} from "../components/ui";

describe("UI Design System Components", () => {
  it("renders Badge with default and custom tones", () => {
    const { rerender } = render(<Badge>Default Badge</Badge>);
    expect(screen.getByText("Default Badge")).toBeDefined();

    rerender(<Badge tone="success">Healthy</Badge>);
    const successBadge = screen.getByText("Healthy");
    expect(successBadge).toBeDefined();
    expect(successBadge.className).toContain("text-success");
  });

  it("renders StatusBadge with humanized text and active pulse", () => {
    const { rerender } = render(<StatusBadge status="awaiting_approval" />);
    expect(screen.getByText("Awaiting approval")).toBeDefined();
    expect(screen.getByText("Awaiting approval").previousElementSibling?.className).toContain("animate-pulse");

    rerender(<StatusBadge status="mitigated" />);
    expect(screen.getByText("Mitigated")).toBeDefined();
    expect(screen.getByText("Mitigated").previousElementSibling?.className).not.toContain("animate-pulse");
  });

  it("renders SeverityBadge correctly for critical, high, medium, and low", () => {
    const { rerender } = render(<SeverityBadge severity="CRITICAL" />);
    expect(screen.getByText("CRITICAL")).toBeDefined();
    expect(screen.getByText("CRITICAL").className).toContain("text-danger");

    rerender(<SeverityBadge severity="MEDIUM" />);
    expect(screen.getByText("MEDIUM")).toBeDefined();
    expect(screen.getByText("MEDIUM").className).toContain("text-warn");
  });

  it("renders StatCard with value, label, and subtitle", () => {
    render(
      <StatCard
        label="Open Incidents"
        value={5}
        subtitle="Active investigations"
        tone="warn"
      />
    );
    expect(screen.getByText("Open Incidents")).toBeDefined();
    expect(screen.getByText("5")).toBeDefined();
    expect(screen.getByText("Active investigations")).toBeDefined();
  });

  it("renders ConfidenceBar with percentage and quartile label", () => {
    render(<ConfidenceBar value={0.88} />);
    expect(screen.getByText("88%")).toBeDefined();
    expect(screen.getByText("high")).toBeDefined();
    expect(screen.getByLabelText("confidence 88 percent (high)")).toBeDefined();
  });
});
