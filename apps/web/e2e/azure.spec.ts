import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { signIn } from "./auth";
import { assertIsolated } from "./isolation";

// v0.10 Azure Monitor journeys. With E2E_AZURE=1 the E2E API reads the synthetic Azure Monitor Logs API fixture on
// loopback (scripts/azure_monitor_fixture.py; fixture credential, fictional services, documented response shapes):
// connection test → service discovery → preview of traces, exceptions, requests/dependencies and KQL metrics →
// read-only investigation by the real local model → cited report → export → snapshot deletion. Without it, Azure
// Monitor must show as not configured. Contract fixture only: no Azure tenant or workspace is contacted.
const nav = { noWaitAfter: true } as const;

async function connectors(page: import("@playwright/test").Page) {
  return (await (await page.request.get("/api/ops/api/v1/connectors")).json()).connectors as
    { id: string; configured: boolean; fixture?: boolean; workspace_id?: string }[];
}

function azureCard(page: import("@playwright/test").Page) {
  return page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: "Use Azure Monitor" }) });
}

test("Azure Monitor is listed as implemented and explains how to configure it when it is not", async ({ page }) => {
  await signIn(page);
  const az = (await connectors(page)).find((c) => c.id === "azure_monitor");
  expect(az, "Azure Monitor is part of the connector list").toBeTruthy();
  test.skip(!!az?.configured, "Azure Monitor is configured in this run (E2E_AZURE=1)");
  await page.goto("/incidents/new?source=connected");
  const card = azureCard(page);
  if (await card.count()) {
    await expect(card.getByText("Not configured")).toBeVisible();
    await expect(card.getByText(/AZURE_MONITOR_ENABLED=true/)).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Use Azure Monitor" })).toBeDisabled();
  }
  await page.goto("/integrations");
  await expect(page.locator(".planned-provider-list").getByText("Azure Monitor & Application Insights")).toHaveCount(0);
  const row = page.locator("details.connector-provider").filter({ hasText: "Azure Monitor" });
  await expect(row.getByText("Not configured", { exact: true })).toBeVisible();
});

test("invalid credentials, missing RBAC and a missing table render clearly (intercepted responses)", async ({ page }) => {
  await signIn(page);
  const az = (await connectors(page)).find((c) => c.id === "azure_monitor");
  test.skip(!az?.configured, "run with E2E_AZURE=1");
  let answer: object = {
    connector: "azure_monitor", status: "auth_error", checked_at: "2026-11-20T12:00:00Z", signals: null, tables: null,
    message: "Microsoft Entra ID: Microsoft Entra ID rejected the credentials (AADSTS7000215): invalid client secret",
  };
  await page.route("**/api/ops/api/v1/connectors/azure_monitor/test", (r) => r.fulfill({ json: answer }));
  await page.goto("/incidents/new?source=connected");
  const card = azureCard(page);
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Authentication failed", { exact: true })).toBeVisible();
  await expect(card.getByRole("alert")).toContainText("invalid client secret");
  await page.screenshot({ path: "test-results/azure-invalid-credentials.png", fullPage: false });

  const denied = { status: "permission_denied", message: "HTTP 403: InsufficientAccessError" };
  answer = {
    connector: "azure_monitor", status: "permission_denied", checked_at: "2026-11-20T12:00:00Z",
    message: "no Application Insights table can be read: assign Log Analytics Data Reader (or Log Analytics Reader) on the workspace",
    signals: { log: denied, metric: denied, span: denied },
    tables: { AppTraces: denied, AppExceptions: denied, AppRequests: denied, AppDependencies: denied },
  };
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Permission missing", { exact: true })).toBeVisible();
  await expect(card.getByRole("alert")).toContainText("Log Analytics Data Reader");
  await expect(card.getByText("AppRequests: access denied")).toBeVisible();
  await page.screenshot({ path: "test-results/azure-insufficient-permissions.png", fullPage: false });

  const ok = { status: "ok", message: "present; records in the last 24 h" };
  answer = {
    connector: "azure_monitor", status: "partial", checked_at: "2026-11-20T12:00:00Z",
    message: "workspace …: AppTraces, AppRequests readable; AppExceptions: unsupported, AppDependencies: unsupported",
    signals: { log: { status: "ok", message: "from AppTraces" }, metric: { status: "ok", message: "from AppRequests" },
      span: { status: "ok", message: "from AppRequests" } },
    tables: { AppTraces: ok, AppExceptions: { status: "unsupported", message: "table not present in this workspace" },
      AppRequests: ok, AppDependencies: { status: "unsupported", message: "table not present in this workspace" } },
  };
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Partly readable", { exact: true })).toBeVisible();
  await expect(card.getByText("AppExceptions: not in workspace")).toBeVisible();
  await expect(card.getByText("AppTraces: present")).toBeVisible();
});

test("operator previews Azure telemetry and gets a cited read-only RCA, exports and deletes it", async ({ page }) => {
  test.setTimeout(600_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page);
  assertIsolated(await (await page.request.get("/api/ops/api/v1/system/identity")).json(), "browser session");
  const az = (await connectors(page)).find((c) => c.id === "azure_monitor");
  test.skip(!az?.configured || !az.fixture, "run with E2E_AZURE=1 (synthetic Azure Monitor fixture)");

  await page.goto("/incidents/new?source=connected");
  const card = azureCard(page);
  await expect(card.getByText("synthetic fixture", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  for (const s of ["Traces & exceptions: readable", "KQL metrics: readable", "Requests & dependencies: readable",
    "AppExceptions: present", "AppDependencies: present"]) await expect(card.getByText(s)).toBeVisible();
  for (const name of ["Grafana Loki", "Prometheus", "Datadog", "AWS CloudWatch"]) { // v0.11: Azure only
    const other = page.getByRole("checkbox", { name: `Use ${name}` });
    if ((await other.count()) && (await other.isEnabled())) await other.uncheck();
  }

  await page.getByRole("button", { name: "Use the Azure fixture incident" }).click();
  await expect(page.getByLabel("Window start (UTC)")).toHaveValue("2026-11-16T07:35");
  await page.getByRole("button", { name: "Find services in this window" }).click();
  await expect(page.getByRole("button", { name: "billing.worker", exact: true })).toBeVisible();
  await expect(page.getByText(/Notification Worker/)).toBeVisible();
  await expect(page.getByText(/have no AppRoleName/)).toBeVisible();

  await page.getByRole("button", { name: "Preview returned evidence" }).click();
  await expect(page.getByRole("heading", { name: "3. Returned evidence" })).toBeVisible({ timeout: 60_000 });
  const queries = page.getByRole("table", { name: "Queries" });
  await expect(queries.getByText("azure_monitor/p95_latency_ms/payment-service", { exact: true })).toBeVisible();
  await expect(queries.getByText("azure_monitor/failed_requests/orders-api", { exact: true })).toBeVisible();
  await expect(queries.getByText(/ItemCount-weighted estimates/).first()).toBeVisible();
  await expect(queries.getByText(/absent, never filled with zero/).first()).toBeVisible();
  // v0.10: an empty Azure answer may be restricted data, so it is never shown as "no data"
  await expect(queries.getByText("no accessible records").first()).toBeVisible();
  await expect(queries.getByText(/access\/coverage not independently verified/).first()).toBeVisible();
  await expect(page.getByText(/^azure_monitor\/(trace_warnings|trace_lifecycle|exceptions)\/[a-z-]+:entry \d+$/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Returned metric series" })).toBeVisible();
  await page.screenshot({ path: "test-results/azure-preview.png", fullPage: true });
  await page.getByRole("tab", { name: /^Spans/ }).click();
  await expect(page.getByText(/^azure_monitor\/(failed_requests|failed_dependencies)\/[a-z-]+:span \d+$/).first()).toBeVisible();
  await page.screenshot({ path: "test-results/azure-preview-requests.png", fullPage: false });

  await page.getByRole("button", { name: "Create incident & start analysis" }).click(nav);
  await page.waitForURL(/\/investigations\/[0-9a-f-]{36}$/, { timeout: 120_000 });
  const investigationId = page.url().split("/").pop()!;
  await expect(page.getByText("Read-only analysis of connected telemetry.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "RCA Postmortem Report" })).toBeVisible({ timeout: 480_000 });
  await expect(page.getByText(/Analysis (complete|inconclusive)/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Expand Report" }).click();
  const report = page.locator(".prose-report");
  await expect(report).toContainText("Ranked hypotheses");
  await expect(report).toContainText("snapshot of Azure Monitor telemetry");
  await page.screenshot({ path: "test-results/azure-analysis.png", fullPage: true });

  const actions = await (await page.request.get(`/api/ops/api/v1/investigations/${investigationId}/actions`)).json();
  expect(actions).toEqual([]);
  const tools = await (await page.request.get(`/api/ops/api/v1/investigations/${investigationId}/tool-calls`)).json();
  const servers = new Set(tools.filter((t: { tool: string }) => t.tool === "search_logs").map((t: { server: string }) => t.server));
  expect([...servers]).toEqual(["opspilot-connected-telemetry"]);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download Markdown" }).click(),
  ]);
  const md = readFileSync(await download.path(), "utf-8");
  writeFileSync("test-results/azure-report.md", md); // the real model's RCA, for review
  expect(md).toContain("## Telemetry queries (provenance)");
  expect(md).toContain("## Evidence coverage");
  expect(md).toMatch(/\| Observed events \|[^\n]*(version=2\.14\.0|db\.pool\.max_size=5)/);
  expect(md).toContain("its absence is not evidence that nothing changed");
  expect(md).toContain("## How to read this report");
  expect(md).toContain("**Verified causal conclusions:** none");
  expect(md).toMatch(/Impact at the end of the collected snapshot window \(2026-11-16 11:05:00Z\)/);
  expect(md).not.toContain("Impact at analysis time");
  expect(md).toContain("| No accessible matching records — access/coverage not independently verified |");
  expect(md).toMatch(/Azure Monitor \(workspace 6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1001, (log|metric|span)/);
  expect(md).toContain("_(source: azure_monitor/");
  expect(md).not.toContain("opspilot-synthetic-fixture-token");
  expect(md).not.toContain("Fixture-Pa55word");

  const incidentHref = await page.getByRole("link", { name: "incident view" }).getAttribute("href");
  const incidentId = incidentHref!.split("/").pop()!;
  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByText("Connected telemetry snapshot")).toBeVisible();
  await expect(page.getByText(/workspace 6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1001/).first()).toBeVisible();
  await page.getByRole("button", { name: "Delete snapshot" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click(nav);
  await page.waitForURL("**/incidents");
  expect((await page.request.get(`/api/ops/api/v1/incidents/${incidentId}`)).status()).toBe(404);
  expect(errors, `uncaught page errors: ${errors.join("; ")}`).toEqual([]);
});

test("catalogue and mobile intake show Azure Monitor (synthetic fixture screenshots)", async ({ page }) => {
  await signIn(page);
  const az = (await connectors(page)).find((c) => c.id === "azure_monitor");
  test.skip(!az?.configured || !az.fixture, "run with E2E_AZURE=1 (synthetic Azure Monitor fixture)");
  await page.goto("/integrations");
  const row = page.locator("details.connector-provider").filter({ hasText: "Azure Monitor" });
  await row.locator("summary").click();
  await row.getByRole("button", { name: "Test connection" }).click();
  await expect(row.getByText("Requests & dependencies: readable")).toBeVisible();
  await expect(row.getByText("AppTraces: present")).toBeVisible();
  await expect(row.getByText("Synthetic fixture", { exact: true })).toBeVisible();
  await expect(row.getByText(/Log Analytics Data Reader/).first()).toBeVisible();
  await page.screenshot({ path: "test-results/azure-integrations.png", fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/incidents/new?source=connected");
  await page.getByRole("button", { name: "Use the Azure fixture incident" }).click();
  const card = azureCard(page);
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  const main = await page.evaluate(() => {
    const m = document.querySelector("main");
    return m ? { scroll: m.scrollWidth, client: m.clientWidth, right: m.getBoundingClientRect().right } : null;
  });
  expect(main).not.toBeNull();
  expect(main!.scroll).toBeLessThanOrEqual(main!.client + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391); // no page scroll
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/azure-mobile-intake.png", fullPage: false });
});
