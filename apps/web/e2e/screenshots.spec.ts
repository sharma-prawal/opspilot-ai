import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./auth";

// Portfolio screenshots of the real running app (synthetic data only). Opt-in:
//   SCREENSHOTS=1 pnpm exec playwright test e2e/screenshots.spec.ts
const nav = { noWaitAfter: true } as const;
const OUT = "../../docs/images";
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture portfolio screenshots");

async function investigate(page: Page, scenario: string): Promise<void> {
  await signIn(page, "demo-operator");
  await page.goto("/incidents");
  await page.getByLabel("Scenario").selectOption(scenario);
  await page.getByRole("button", { name: "Simulate", exact: true }).click(nav);
  await page.waitForURL(/\/incidents\/[0-9a-f-]{36}$/);
  await page.getByRole("button", { name: "Start investigation" }).click(nav);
  await page.waitForURL(/\/investigations\/[0-9a-f-]{36}$/);
}

test("INC-003 multi-step plan", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await investigate(page, "INC-003");
  for (let step = 1; step <= 4; step++) {
    const approve = page.getByRole("button", { name: /Approve & execute in sandbox/ });
    await expect(approve).toBeVisible({ timeout: 180_000 });
    if (step === 1) await page.screenshot({ path: `${OUT}/inc003-approval.png` });
    await approve.click();
    await expect(approve).toBeHidden({ timeout: 60_000 });
  }
  await expect(page.getByRole("heading", { name: "RCA report" })).toBeVisible({ timeout: 120_000 });
  await page.screenshot({ path: `${OUT}/inc003-mitigated.png` });
});

test("NEG-002 escalation without action", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await investigate(page, "NEG-002");
  await expect(page.getByRole("heading", { name: "RCA report" })).toBeVisible({ timeout: 180_000 });
  await page.screenshot({ path: `${OUT}/neg002-escalated.png` });
});

test("overview and knowledge search", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, "demo-operator");
  await page.goto("/");
  await expect(page.getByText("mcp read")).toBeVisible();
  await page.screenshot({ path: `${OUT}/overview.png` });
  await page.goto("/knowledge");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(/results ·/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${OUT}/knowledge.png` });
});
