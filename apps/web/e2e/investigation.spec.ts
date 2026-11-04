import { expect, test } from "@playwright/test";
import { signIn } from "./auth";
import { assertIsolated } from "./isolation";

// Client-side (router) navigations: we assert the resulting URL explicitly instead of relying on
// Playwright's implicit post-click navigation wait, which does not settle with Next 16 prefetching.
const nav = { noWaitAfter: true } as const;

test("operator investigates INC-001, approves the rollback and sees verified recovery", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await signIn(page);
  // This spec creates incidents and executes a sandbox remediation: verify the stack before any mutation.
  assertIsolated(await (await page.request.get("/api/ops/api/v1/system/identity")).json(), "browser session");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "System overview" })).toBeVisible();
  await expect(page.getByText("mcp read")).toBeVisible();

  await page.getByRole("link", { name: "Incidents", exact: true }).click(nav);
  await page.waitForURL("**/incidents");
  await page.getByLabel("Scenario").selectOption("INC-001");
  await page.getByRole("button", { name: "Simulate", exact: true }).click(nav);
  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: /Elevated HTTP 5xx ratio on transaction-api/ })).toBeVisible();

  await page.getByRole("button", { name: "Start investigation" }).click(nav);
  await page.waitForURL(/\/investigations\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("list", { name: "Workflow progress" })).toBeVisible();

  // The agent pauses for approval; the proposed action must be the migration rollback.
  const approve = page.getByRole("button", { name: /Approve & execute in sandbox/ });
  await expect(approve).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText("rollback_deployment").first()).toBeVisible();
  await expect(page.getByText("dep-ls-0042").first()).toBeVisible();
  // The reviewer sees the ranked hypotheses (with confidence) *before* deciding.
  await expect(page.getByLabel(/^confidence \d+ percent/).first()).toBeVisible();
  await expect(page.getByText(/migration/i).first()).toBeVisible();
  await page.screenshot({ path: "test-results/awaiting-approval.png", fullPage: true });

  await page.getByLabel("Comment (optional)").fill("approved by Playwright");
  await approve.click();

  await expect(page.getByRole("heading", { name: "RCA report" })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/^Recovered —/).first()).toBeVisible();
  await expect(page.locator(".prose-report")).toContainText("Ranked hypotheses");
  await expect(page.locator(".prose-report")).toContainText(/migration/i);
  await page.screenshot({ path: "test-results/completed.png", fullPage: true });
  expect(errors, `uncaught page errors: ${errors.join("; ")}`).toEqual([]);
});
