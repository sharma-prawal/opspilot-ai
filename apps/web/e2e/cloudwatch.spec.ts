import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { signIn } from "./auth";
import { assertIsolated } from "./isolation";

// v0.11 AWS CloudWatch journeys. With E2E_CLOUDWATCH=1 the E2E API reads the synthetic CloudWatch API fixture on
// loopback through the real AWS SDK (scripts/cloudwatch_fixture.py; synthetic keys, fictional account 111122223333,
// documented wire formats): connection test → service discovery → preview of Logs Insights events and metrics →
// read-only investigation by the real local model → cited report → export → snapshot deletion. Without it, CloudWatch
// must show as not configured. Contract fixture only: no AWS account, profile or endpoint is contacted.
const nav = { noWaitAfter: true } as const;

async function connectors(page: import("@playwright/test").Page) {
  return (await (await page.request.get("/api/ops/api/v1/connectors")).json()).connectors as
    { id: string; configured: boolean; fixture?: boolean; region?: string }[];
}

function cwCard(page: import("@playwright/test").Page) {
  return page.locator("div.rounded-xl").filter({ has: page.getByRole("checkbox", { name: "Use AWS CloudWatch" }) });
}

test("AWS CloudWatch is listed as implemented and explains how to configure it when it is not", async ({ page }) => {
  await signIn(page);
  const cw = (await connectors(page)).find((c) => c.id === "cloudwatch");
  expect(cw, "AWS CloudWatch is part of the connector list").toBeTruthy();
  test.skip(!!cw?.configured, "AWS CloudWatch is configured in this run (E2E_CLOUDWATCH=1)");
  await page.goto("/incidents/new?source=connected");
  const card = cwCard(page);
  if (await card.count()) {
    await expect(card.getByText("Not configured")).toBeVisible();
    await expect(card.getByText(/CLOUDWATCH_ENABLED=true/)).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Use AWS CloudWatch" })).toBeDisabled();
  }
  await page.goto("/integrations");
  await expect(page.locator(".planned-provider-list").getByText(/CloudWatch/)).toHaveCount(0);
  const row = page.locator("details.connector-provider").filter({ hasText: "AWS CloudWatch" });
  await expect(row.getByText("Not configured", { exact: true })).toBeVisible();
});

test("invalid credentials and insufficient permissions render clearly (intercepted responses)", async ({ page }) => {
  await signIn(page);
  const cw = (await connectors(page)).find((c) => c.id === "cloudwatch");
  test.skip(!cw?.configured, "run with E2E_CLOUDWATCH=1");
  let answer: object = {
    connector: "cloudwatch", status: "auth_error", checked_at: "2026-11-23T12:00:00Z", signals: null,
    message: "AWS credentials: sts:GetCallerIdentity: ExpiredToken — the temporary credentials have expired; refresh them (for a profile: aws sso login / renew)",
  };
  await page.route("**/api/ops/api/v1/connectors/cloudwatch/test", (r) => r.fulfill({ json: answer }));
  await page.goto("/incidents/new?source=connected");
  const card = cwCard(page);
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Authentication failed", { exact: true })).toBeVisible();
  await expect(card.getByRole("alert")).toContainText("temporary credentials have expired");
  await page.screenshot({ path: "test-results/cloudwatch-invalid-credentials.png", fullPage: false });

  const denied = { status: "permission_denied", message: "logs:StartQuery: AccessDeniedException — the identity is not allowed logs:StartQuery" };
  answer = {
    connector: "cloudwatch", status: "permission_denied", checked_at: "2026-11-23T12:00:00Z",
    message: "the identity cannot query CloudWatch Logs or metrics: see the IAM policy",
    identity: { account: "111122223333", principal: "assumed role", role: "OpsPilotNoAccess", region: "us-east-1" },
    signals: { log: denied, metric: { status: "permission_denied", message: "cloudwatch:GetMetricData: AccessDeniedException" } },
    log_groups: { "/ecs/shop-prod/inventory-service": denied },
  };
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Permission missing", { exact: true })).toBeVisible();
  await expect(card.getByRole("alert")).toContainText("IAM policy");
  await expect(card.getByText("/ecs/shop-prod/inventory-service: access denied", { exact: true })).toBeVisible();
  await expect(card.getByText(/account 111122223333/)).toBeVisible();
  await page.screenshot({ path: "test-results/cloudwatch-insufficient-permissions.png", fullPage: false });
});

test("operator previews CloudWatch logs and metrics and gets a cited read-only RCA, exports and deletes it", async ({ page }) => {
  test.setTimeout(600_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page);
  assertIsolated(await (await page.request.get("/api/ops/api/v1/system/identity")).json(), "browser session");
  const cw = (await connectors(page)).find((c) => c.id === "cloudwatch");
  test.skip(!cw?.configured || !cw.fixture, "run with E2E_CLOUDWATCH=1 (synthetic CloudWatch fixture)");

  await page.goto("/incidents/new?source=connected");
  const card = cwCard(page);
  await expect(card.getByText("synthetic fixture", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Test connection" }).click();
  // the real fixture: one log group does not exist and one may not be read, so the connection is partly readable
  await expect(card.getByText("Partly readable", { exact: true })).toBeVisible({ timeout: 60_000 });
  for (const s of ["Logs Insights events: readable", "CloudWatch metrics: readable",
    "/ecs/shop-prod/inventory-service: readable", "/ecs/shop-prod/audit-worker: access denied",
    "/ecs/shop-prod/pricing-service: not found"]) await expect(card.getByText(s, { exact: true })).toBeVisible();
  await expect(card.getByText(/account 111122223333/).first()).toBeVisible();
  for (const name of ["Grafana Loki", "Prometheus", "Datadog", "Azure Monitor"]) {
    const other = page.getByRole("checkbox", { name: `Use ${name}` });
    if ((await other.count()) && (await other.isEnabled())) await other.uncheck();
  }
  await card.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "test-results/cloudwatch-connection.png", fullPage: false });

  await page.getByRole("button", { name: "Use the CloudWatch fixture incident" }).click();
  await expect(page.getByLabel("Window start (UTC)")).toHaveValue("2026-11-18T11:12");
  await page.getByRole("button", { name: "Find services in this window" }).click();
  await expect(page.getByRole("button", { name: "pricing-service", exact: true })).toBeVisible();
  await expect(page.getByText(/never inferred from resource names/)).toBeVisible();
  await expect(page.getByText(/pricing-service: log group\(s\) not found/)).toBeVisible();

  await page.getByRole("button", { name: "Preview returned evidence" }).click();
  await expect(page.getByRole("heading", { name: "3. Returned evidence" })).toBeVisible({ timeout: 120_000 });
  const queries = page.getByRole("table", { name: "Queries" });
  await expect(queries.getByText("cloudwatch/cw_errors/inventory-service", { exact: true })).toBeVisible();
  await expect(queries.getByText("cloudwatch/custom_metrics/inventory-service", { exact: true })).toBeVisible();
  await expect(queries.getByText("not queried (no mapping)").first()).toBeVisible();
  await expect(queries.getByText(/billed by scanned volume/).first()).toBeVisible();
  await expect(queries.getByText(/absent, never filled with zero/).first()).toBeVisible();
  await expect(queries.getByText(/Complete, 2 polls/).first()).toBeVisible();
  await expect(page.getByText(/^cloudwatch\/(cw_errors|cw_timeouts|cw_lifecycle)\/[a-z-]+:entry \d+$/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Returned metric series" })).toBeVisible();
  await page.screenshot({ path: "test-results/cloudwatch-preview.png", fullPage: true });
  await page.getByRole("tab", { name: /^Metrics/ }).click();
  await expect(page.getByText(/^cloudwatch\/[a-z0-9_]+\/[a-z-]+:point \d+$/).first()).toBeVisible();
  await page.screenshot({ path: "test-results/cloudwatch-preview-metrics.png", fullPage: false });

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
  await expect(report).toContainText("snapshot of AWS CloudWatch telemetry");
  await page.screenshot({ path: "test-results/cloudwatch-analysis.png", fullPage: true });

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
  writeFileSync("test-results/cloudwatch-report.md", md); // the real model's RCA, for review
  expect(md).toContain("## Telemetry queries (provenance)");
  expect(md).toContain("## Evidence coverage");
  expect(md).toMatch(/\| Observed events \|[^\n]*(3\.8\.0|max_size=8)/);
  expect(md).toContain("its absence is not evidence that nothing changed");
  expect(md).toContain("## How to read this report");
  expect(md).toContain("**Verified causal conclusions:** none");
  expect(md).toContain("was not queried (no mapped CloudWatch resource)");
  expect(md).toMatch(/AWS CloudWatch \(us-east-1, log, \/ecs\/shop-prod\/[a-z-]+, query [0-9a-f-]{36}\)/);
  expect(md).toContain("_(source: cloudwatch/");
  expect(md).toContain("AWS CloudTrail");
  expect(md).not.toContain("AKIA");
  expect(md).not.toContain("opspilot-synthetic-fixture-secret");
  expect(md).not.toContain("Fixture-Pa55word");

  const incidentHref = await page.getByRole("link", { name: "incident view" }).getAttribute("href");
  const incidentId = incidentHref!.split("/").pop()!;
  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByText("Connected telemetry snapshot")).toBeVisible();
  await expect(page.getByText(/AWS us-east-1 · account 111122223333/).first()).toBeVisible();
  await page.getByRole("button", { name: "Delete snapshot" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click(nav);
  await page.waitForURL("**/incidents");
  expect((await page.request.get(`/api/ops/api/v1/incidents/${incidentId}`)).status()).toBe(404);
  expect(errors, `uncaught page errors: ${errors.join("; ")}`).toEqual([]);
});

test("catalogue and mobile intake show AWS CloudWatch (synthetic fixture screenshots)", async ({ page }) => {
  await signIn(page);
  const cw = (await connectors(page)).find((c) => c.id === "cloudwatch");
  test.skip(!cw?.configured || !cw.fixture, "run with E2E_CLOUDWATCH=1 (synthetic CloudWatch fixture)");
  await page.goto("/integrations");
  const row = page.locator("details.connector-provider").filter({ hasText: "AWS CloudWatch" });
  await row.locator("summary").click();
  await row.getByRole("button", { name: "Test connection" }).click();
  await expect(row.getByText("Logs Insights events: readable")).toBeVisible({ timeout: 60_000 });
  await expect(row.getByText("/ecs/shop-prod/audit-worker: access denied", { exact: true })).toBeVisible();
  await expect(row.getByText("Synthetic fixture", { exact: true })).toBeVisible();
  await expect(row.getByText(/logs:StopQuery/).first()).toBeVisible();
  await expect(page.locator(".planned-provider-list").getByText(/CloudWatch/)).toHaveCount(0);
  await row.locator("summary").evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "test-results/cloudwatch-integrations.png", fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/incidents/new?source=connected");
  await page.getByRole("button", { name: "Use the CloudWatch fixture incident" }).click();
  const card = cwCard(page);
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText("Partly readable", { exact: true })).toBeVisible({ timeout: 60_000 });
  const main = await page.evaluate(() => {
    const m = document.querySelector("main");
    return m ? { scroll: m.scrollWidth, client: m.clientWidth } : null;
  });
  expect(main).not.toBeNull();
  expect(main!.scroll).toBeLessThanOrEqual(main!.client + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391); // no page scroll
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/cloudwatch-mobile-intake.png", fullPage: false });
});
