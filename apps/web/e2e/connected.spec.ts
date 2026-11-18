import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { signIn } from "./auth";
import { assertIsolated } from "./isolation";

// v0.6: connection test → service discovery → preview of real Loki/Prometheus results → read-only investigation
// by the real local model → cited report download → snapshot deletion. Needs `make telemetry-up` and E2E_TELEMETRY=1
// (the E2E API then points at the local synthetic Loki/Prometheus); skipped otherwise.
const nav = { noWaitAfter: true } as const;

test("operator connects Loki and Prometheus, previews telemetry and gets a cited read-only RCA", async ({ page }) => {
  test.setTimeout(480_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await signIn(page);
  assertIsolated(await (await page.request.get("/api/ops/api/v1/system/identity")).json(), "browser session");
  const list = await (await page.request.get("/api/ops/api/v1/connectors")).json();
  test.skip(!list.connectors.every((c: { configured: boolean }) => c.configured), "run with E2E_TELEMETRY=1 after make telemetry-up");

  await page.goto("/incidents/new?source=connected");
  await expect(page.getByRole("heading", { name: "Investigate with connected telemetry" })).toBeVisible();
  for (const name of ["Grafana Loki", "Prometheus"]) {
    const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: `Use ${name}` }) });
    await card.getByRole("button", { name: "Test connection" }).click();
    await expect(card.getByText("Connected", { exact: true })).toBeVisible();
    await expect(card.getByText(/answered \(version 3\.5\.0\)/)).toBeVisible();
  }

  await page.getByRole("button", { name: "Use the local demo incident" }).click();
  await expect(page.getByLabel("Window start (UTC)")).toHaveValue("2026-11-12T06:16");
  await page.getByRole("button", { name: "Find services in this window" }).click();
  await expect(page.getByRole("button", { name: "search-api", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Preview returned evidence" }).click();
  await expect(page.getByRole("heading", { name: "3. Returned evidence" })).toBeVisible();
  const queries = page.getByRole("table", { name: "Queries" });
  await expect(queries.getByText("prometheus/http_5xx_ratio/checkout-api", { exact: true })).toBeVisible();
  await expect(queries.getByText("loki/errors_warnings/payment-service", { exact: true })).toBeVisible();
  await expect(page.getByText(/^loki\/(errors_warnings|lifecycle)\/[a-z-]+:entry \d+$/).first()).toBeVisible();
  await expect(page.getByText("1 credential-like value(s)")).toBeVisible();
  await page.getByRole("tab", { name: /^Metrics/ }).click();
  await expect(page.getByText(/^prometheus\/[a-z0-9_]+\/[a-z-]+:point \d+$/).first()).toBeVisible();
  await page.screenshot({ path: "test-results/connected-preview.png", fullPage: true });

  await page.getByRole("button", { name: "Create incident & start analysis" }).click(nav);
  await page.waitForURL(/\/investigations\/[0-9a-f-]{36}$/);
  const investigationId = page.url().split("/").pop()!;
  await expect(page.getByText("Read-only analysis of connected telemetry.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "RCA Postmortem Report" })).toBeVisible({ timeout: 420_000 });
  await expect(page.getByText(/Analysis (complete|inconclusive)/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0);
  const report = page.locator(".prose-report");
  await expect(report).toContainText("Ranked hypotheses");
  await expect(report).toContainText(/source: (loki|prometheus)\//);
  await page.screenshot({ path: "test-results/connected-analysis.png", fullPage: true });

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
  expect(md).toContain("Connected telemetry — read-only analysis");
  expect(md).toContain("## Telemetry queries (provenance)");
  expect(md).not.toContain("sk_test_EXAMPLE");

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
