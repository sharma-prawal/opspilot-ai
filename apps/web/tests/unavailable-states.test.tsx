// @vitest-environment jsdom
// Unknown stays unknown in the UI: when the backend overview is missing, model names read "unavailable" and the
// overview counters read "—", never a setting name or a zero that looks like a real value.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Overview } from "../lib/types";

const overviewMock = vi.fn<() => Promise<Overview>>();

vi.mock("@/lib/api", () => ({
  api: {
    overview: () => overviewMock(),
    dependencies: () => new Promise(() => {}),
    incidents: () => new Promise(() => {}),
    simulate: vi.fn(),
  },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const { ModelName } = await import("../lib/models");
const { default: OverviewPage } = await import("../app/page");

const OVERVIEW: Overview = {
  incidents: { open: 2, investigating: 1, resolved: 4 },
  investigations: { queued: 1, running: 2, completed: 5 },
  actions: { pending: 3 },
  knowledge: { documents: 4, chunks: 17 },
  runtime: {
    llm_model: "family-a:9b",
    embedding_model: "embed-b:1b",
    mcp_read_tools: [],
    mcp_action_tools: [],
    max_concurrent_investigations: 1,
    agent_budgets: {},
  },
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function counter(label: string): string | null {
  return screen.getByText((_, el) => el?.textContent?.startsWith(label) === true && el?.tagName === (label === "Open cases" ? "SPAN" : "A")).querySelector("strong")?.textContent ?? null;
}

beforeEach(() => {
  overviewMock.mockReset();
});
afterEach(() => {
  cleanup();
});

describe("ModelName", () => {
  it("shows an ellipsis while the overview is loading", () => {
    overviewMock.mockReturnValue(new Promise(() => {}));
    wrap(<ModelName />);
    expect(screen.getByText("…")).toBeDefined();
  });

  it("shows 'unavailable', not the setting name, when the backend call fails", async () => {
    overviewMock.mockRejectedValue(new Error("web authentication is not configured"));
    wrap(<ModelName kind="embedding" />);
    const el = await screen.findByText("unavailable");
    expect(el.getAttribute("title")).toBe("EMBEDDING_MODEL not reported by the backend");
    expect(screen.queryByText("EMBEDDING_MODEL")).toBeNull();
  });

  it("shows the reported model name", async () => {
    overviewMock.mockResolvedValue(OVERVIEW);
    wrap(<ModelName />);
    const el = await screen.findByText("family-a:9b");
    expect(el.getAttribute("title")).toBe("LLM_MODEL");
  });
});

describe("overview counters", () => {
  it("show '—' instead of 0 when the overview is unavailable", async () => {
    overviewMock.mockRejectedValue(new Error("web authentication is not configured"));
    wrap(<OverviewPage />);
    await waitFor(() => expect(overviewMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0));
    for (const label of ["Open cases", "Awaiting approval"]) {
      expect(counter(label)).toBe("—");
    }
  });

  it("show the backend's numbers, including real zeros", async () => {
    overviewMock.mockResolvedValue({ ...OVERVIEW, actions: { pending: 0 } });
    wrap(<OverviewPage />);
    await waitFor(() => expect(counter("Open cases")).toBe("3"));
    expect(counter("Awaiting approval")).toBe("0");
  });
});
