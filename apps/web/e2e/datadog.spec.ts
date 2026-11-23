import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { signIn } from "./auth";
import { assertIsolated } from "./isolation";

// v0.9 Datadog journeys. With E2E_DATADOG=1 the E2E API reads the synthetic Datadog fixture on loopback
// (scripts/datadog_fixture.py; synthetic keys, fictional services): connection test → service discovery → preview of
// logs, metrics and spans → read-only investigation by the real local model → cited report → snapshot deletion.
// Without it, Datadog must show as not configured. Contract fixture only: no live Datadog organization is contacted.
const nav = { noWaitAfter: true } as const;

async function connectors(page: import("@playwright/test").Page) {
  return (await (await page.request.get("/api/ops/api/v1/connectors")).json()).connectors as
    { id: string; configured: boolean; fixture?: boolean }[];
}

test("Datadog is listed as implemented and explains how to configure it when it is not", async ({ page }) => {
  await signIn(page);
  const dd = (await connectors(page)).find((c) => c.id === "datadog");
  test.skip(!!dd?.configured, "Datadog is configured in this run (E2E_DATADOG=1)");
  await page.goto("/incidents/new?source=connected");
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: "Use Datadog" }) });
  if (await card.count()) {
    await expect(card.getByText("Not configured")).toBeVisible();
    await expect(card.getByText(/DATADOG_ENABLED=true/)).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Use Datadog" })).toBeDisabled();
  }
  await page.goto("/integrations");
  await expect(page.getByText("Datadog", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Planned adapters" })).toBeVisible();
  await expect(page.locator(".planned-provider-list").getByText("Datadog", { exact: true })).toHaveCount(0);
});

test("connection-test error states render per signal (intercepted responses)", async ({ page }) => {
  await signIn(page);
  const dd = (await connectors(page)).find((c) => c.id === "datadog");
  test.skip(!dd?.configured, "run with E2E_DATADOG=1");
  let answer: object = {
    connector: "datadog", status: "auth_error", checked_at: "2026-11-19T12:00:00Z",
    message: "the API key was rejected for site datadoghq.com: HTTP 403: Forbidden", signals: null,
  };
  await page.route("**/api/ops/api/v1/connectors/datadog/test", (r) => r.fulfill({ json: answer }));
  await page.goto("/incidents/new?source=connected");
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: "Use Datadog" }) });
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Authentication failed", { exact: true })).toBeVisible();
  await expect(card.getByRole("alert")).toContainText("API key was rejected");
  answer = {
    connector: "datadog", status: "partial", checked_at: "2026-11-19T12:00:00Z",
    message: "Datadog (datadoghq.com): log, metric readable; span: permission denied",
    signals: {
      log: { status: "ok", message: "Log Management readable (logs_read_data)" },
      metric: { status: "ok", message: "Metrics readable (timeseries_query)" },
      span: { status: "permission_denied", message: "HTTP 403: Forbidden. The application key lacks apm_read" },
    },
  };
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Partly readable", { exact: true })).toBeVisible();
  await expect(card.getByText("APM spans: permission missing")).toBeVisible();
  await expect(card.getByText("Logs: readable")).toBeVisible();
  await page.screenshot({ path: "test-results/datadog-partial-permissions.png", fullPage: false });
});

test("operator previews Datadog logs, metrics and spans and gets a cited read-only RCA", async ({ page }) => {
  test.setTimeout(480_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page);
  assertIsolated(await (await page.request.get("/api/ops/api/v1/system/identity")).json(), "browser session");
  const dd = (await connectors(page)).find((c) => c.id === "datadog");
  test.skip(!dd?.configured || !dd.fixture, "run with E2E_DATADOG=1 (synthetic Datadog fixture)");

  await page.goto("/incidents/new?source=connected");
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: "Use Datadog" }) });
  await expect(card.getByText("synthetic fixture")).toBeVisible();
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  for (const s of ["Logs: readable", "Metrics: readable", "APM spans: readable"]) await expect(card.getByText(s)).toBeVisible();
  for (const name of ["Grafana Loki", "Prometheus", "Azure Monitor", "AWS CloudWatch"]) { // v0.10/v0.11: Datadog only
    const other = page.getByRole("checkbox", { name: `Use ${name}` });
    if ((await other.count()) && (await other.isEnabled())) await other.uncheck();
  }

  await page.getByRole("button", { name: "Use the Datadog fixture incident" }).click();
  await expect(page.getByLabel("Window start (UTC)")).toHaveValue("2026-11-15T11:05");
  await page.getByRole("button", { name: "Find services in this window" }).click();
  await expect(page.getByRole("button", { name: "notification-worker", exact: true })).toBeVisible();
  await expect(page.getByText(/no service tag; they cannot be queried/)).toBeVisible();

  await page.getByRole("button", { name: "Preview returned evidence" }).click();
  await expect(page.getByRole("heading", { name: "3. Returned evidence" })).toBeVisible();
  const queries = page.getByRole("table", { name: "Queries" });
  await expect(queries.getByText("datadog/http_5xx_ratio/orders-api", { exact: true })).toBeVisible();
  await expect(queries.getByText("datadog/error_spans/inventory-service", { exact: true })).toBeVisible();
  await expect(page.getByText(/^datadog\/(errors_warnings|lifecycle)\/[a-z-]+:entry \d+$/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Returned metric series" })).toBeVisible();
  await expect(page.getByText(/gap\(s\) with no returned value, not filled in/).first()).toBeVisible();
  await page.screenshot({ path: "test-results/datadog-preview.png", fullPage: true });
  await page.getByRole("tab", { name: /^Spans/ }).click();
  await expect(page.getByText(/^datadog\/error_spans\/[a-z-]+:span \d+$/).first()).toBeVisible();
  await page.screenshot({ path: "test-results/datadog-preview-spans.png", fullPage: false });

  await page.getByRole("button", { name: "Create incident & start analysis" }).click(nav);
  await page.waitForURL(/\/investigations\/[0-9a-f-]{36}$/);
  const investigationId = page.url().split("/").pop()!;
  await expect(page.getByText("Read-only analysis of connected telemetry.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "RCA Postmortem Report" })).toBeVisible({ timeout: 420_000 });
  await expect(page.getByText(/Analysis (complete|inconclusive)/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Expand Report" }).click();
  const report = page.locator(".prose-report");
  await expect(report).toContainText("Ranked hypotheses");
  await expect(report).toContainText("snapshot of Datadog telemetry");
  await page.screenshot({ path: "test-results/datadog-analysis.png", fullPage: true });

  const actions = await (await page.request.get(`/api/ops/api/v1/investigations/${investigationId}/actions`)).json();
  expect(actions).toEqual([]); // nothing proposed for approval, nothing executed
  const tools = await (await page.request.get(`/api/ops/api/v1/investigations/${investigationId}/tool-calls`)).json();
  const servers = new Set(tools.filter((t: { tool: string }) => t.tool === "search_logs").map((t: { server: string }) => t.server));
  expect([...servers]).toEqual(["opspilot-connected-telemetry"]);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download Markdown" }).click(),
  ]);
  const md = readFileSync(await download.path(), "utf-8");
  writeFileSync("test-results/datadog-report.md", md); // the real model's RCA, for review
  expect(md).toContain("## Telemetry queries (provenance)");
  // v0.9 correction: unknown change history and the observed version start are stated, whatever the model wrote
  expect(md).toContain("## Evidence coverage");
  expect(md).toMatch(/\| Observed events \|[^\n]*version=3\.8\.0/);
  expect(md).toContain("its absence is not evidence that nothing changed");
  expect(md).toContain("Datadog (datadoghq.com, span)");
  expect(md).not.toContain("fixture-api-key");
  expect(md).not.toContain("fixture-app-key");
  expect(md).not.toContain("sk_live_FIXTURE");

  const incidentHref = await page.getByRole("link", { name: "incident view" }).getAttribute("href");
  const incidentId = incidentHref!.split("/").pop()!;
  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByText("Connected telemetry snapshot")).toBeVisible();
  await page.getByRole("button", { name: "Delete snapshot" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click(nav);
  await page.waitForURL("**/incidents");
  expect((await page.request.get(`/api/ops/api/v1/incidents/${incidentId}`)).status()).toBe(404);
  expect(errors, `uncaught page errors: ${errors.join("; ")}`).toEqual([]);
});

test("catalogue and mobile intake show Datadog (synthetic fixture screenshots)", async ({ page }) => {
  await signIn(page);
  const dd = (await connectors(page)).find((c) => c.id === "datadog");
  test.skip(!dd?.configured || !dd.fixture, "run with E2E_DATADOG=1 (synthetic Datadog fixture)");
  await page.goto("/integrations");
  const row = page.locator("details.connector-provider").filter({ hasText: "Datadog" });
  await row.locator("summary").click();
  await row.getByRole("button", { name: "Test connection" }).click();
  await expect(row.getByText("APM spans: readable")).toBeVisible();
  await expect(row.getByText("Synthetic fixture", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/datadog-integrations.png", fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/incidents/new?source=connected");
  await page.getByRole("button", { name: "Use the Datadog fixture incident" }).click();
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: "Use Datadog" }) });
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  // The intake content must fit a phone: nothing inside <main> may force it wider than the viewport.
  const main = await page.evaluate(() => {
    const m = document.querySelector("main");
    return m ? { scroll: m.scrollWidth, client: m.clientWidth, right: m.getBoundingClientRect().right } : null;
  });
  expect(main).not.toBeNull();
  expect(main!.scroll).toBeLessThanOrEqual(main!.client + 1);
  expect(main!.right).toBeLessThanOrEqual(391);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391); // no page scroll
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/datadog-mobile-intake.png", fullPage: false });
});
