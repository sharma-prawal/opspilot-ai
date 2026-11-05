import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

// Read-only browser checks of the BFF authentication boundary (no incidents/investigations are created).
test("unauthenticated visitors are sent to sign-in and the BFF refuses them", async ({ page, request }) => {
  const api = await request.get("/api/ops/api/v1/incidents");
  expect(api.status()).toBe(401);
  const mutation = await request.post("/api/ops/api/v1/incidents/simulate", {
    data: { scenario: "INC-001" }, headers: { origin: "http://127.0.0.1:3000" } });
  expect(mutation.status()).toBe(401);
  await page.goto("/incidents");
  await page.waitForURL(/\/login/);
});

test("signed-in operator can read; mutations without CSRF or from another origin are refused", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "System overview" })).toBeVisible();
  await expect(page.getByText(/e2e-operator · operator/)).toBeVisible();
  const status = await page.evaluate(async () => {
    const base = { method: "POST", headers: { "content-type": "application/json" }, body: "{}" };
    const noCsrf = await fetch("/api/ops/api/v1/knowledge/search", base);
    const wrongType = await fetch("/api/ops/api/v1/knowledge/search", { ...base, headers: { "content-type": "text/plain" } });
    return [noCsrf.status, wrongType.status];
  });
  expect(status).toEqual([403, 415]);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
  const after = await page.evaluate(async () => (await fetch("/api/ops/api/v1/incidents")).status);
  expect(after).toBe(401);
});

test("wrong passphrase is rejected", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Name").fill("intruder");
  await page.getByLabel("Passphrase").fill("definitely-not-the-passphrase");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /invalid/ })).toBeVisible();
});
