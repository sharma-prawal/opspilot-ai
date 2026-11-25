// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import IncidentsPage from "../app/incidents/page";
import { Nav } from "../components/nav";
import { api } from "../lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/incidents", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("../lib/api", () => ({
  api: { searchIncidents: vi.fn(), scenarios: vi.fn(async () => []), approvals: vi.fn(async () => []) },
  getSession: vi.fn(async () => ({ authenticated: true, sub: "synthetic-sre", role: "operator", csrf: "test" })),
  clearSession: vi.fn(),
}));
const cases = Array.from({ length: 75 }, (_, n) => ({
  id: String(n), reference: `SYNTHETIC-${n}`, title: n === 74 ? "Older needle" : "Saved case", service: "checkout-api",
  evidence_source: n % 3 ? "upload" as const : "simulator" as const, status: n % 2 ? "resolved" as const : "open" as const,
  severity: "SEV2", detected_at: "2026-11-20T12:00:00Z", created_at: "2026-11-20T12:00:00Z", description: "", environment_id: null,
}));
function view(children: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>);
}
beforeEach(() => {
  vi.mocked(api.searchIncidents).mockImplementation(async filters => {
    const matching = cases.filter(i => i.title.toLowerCase().includes((filters.q ?? "").toLowerCase()) &&
      (!filters.source || filters.source === "all" || i.evidence_source === filters.source) &&
      (!filters.status || filters.status === "all" || i.status === filters.status));
    const offset = filters.offset ?? 0, limit = filters.limit ?? 50;
    return { items: matching.slice(offset, offset + limit), total: matching.length, limit, offset };
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("queries beyond the initial page and resets pagination when a search changes", async () => {
  view(<IncidentsPage />);
  await screen.findByText("1–50 of 75");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("51–75 of 75");
  fireEvent.change(screen.getByLabelText("Search incidents"), { target: { value: "Older needle" } });
  await screen.findByText("1–1 of 1");
  expect(api.searchIncidents).toHaveBeenLastCalledWith({ q: "Older needle", source: "all", status: "all", limit: 50, offset: 0 });
  expect(screen.getByText("1 matching cases · complete history")).toBeDefined();
});
it("uses server source/state filters and clears an empty result", async () => {
  view(<IncidentsPage />);
  await screen.findByText("1–50 of 75");
  fireEvent.change(screen.getByLabelText("Search incidents"), { target: { value: "Older needle" } });
  fireEvent.change(screen.getByLabelText("Source"), { target: { value: "upload" } });
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "resolved" } });
  await screen.findByText("No incidents match these filters.");
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await screen.findByText("1–50 of 75");
});
it("exposes current-route disclosure and restores focus on Escape", async () => {
  view(<Nav />);
  const toggle = screen.getByRole("button", { name: "Open navigation · Incidents" });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("link", { name: "Incidents" }).getAttribute("aria-current")).toBe("page");
  await screen.findByText("synthetic-sre · operator");
  fireEvent.keyDown(screen.getByRole("button", { name: "Sign out" }), { key: "Escape" });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(toggle);
  fireEvent.click(toggle);
  const architecture = screen.getByRole("link", { name: "Architecture" });
  architecture.addEventListener("click", event => event.preventDefault());
  fireEvent.click(architecture);
  await waitFor(() => expect(toggle.getAttribute("aria-expanded")).toBe("false"));
});
