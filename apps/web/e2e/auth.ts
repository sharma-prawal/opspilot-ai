import { expect, type Page } from "@playwright/test";

/** Sign in through the real login form using the operator passphrase from the environment (.env). */
export async function signIn(page: Page, name = "e2e-operator"): Promise<void> {
  const passphrase = process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE;
  if (!passphrase) throw new Error("OPSPILOT_WEB_OPERATOR_PASSPHRASE not set (run via `make e2e`, which loads .env)");
  await page.goto("/login");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Passphrase").fill(passphrase);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}
