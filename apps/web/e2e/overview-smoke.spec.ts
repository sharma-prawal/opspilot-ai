import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("overview home page renders primary content and operating modes without errors or crash boundaries", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await signIn(page);
  await page.goto("/");

  // Error boundary assertion
  await expect(page.getByText(/This page couldn['’]t load/i)).toHaveCount(0);
  await expect(page.getByText(/Application error: a client-side exception/i)).toHaveCount(0);

  // Primary content verification
  await expect(page.getByRole("heading", { name: "System overview" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open an investigation." })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Simulator/ })).toBeVisible();
  await page.getByRole("button", { name: /^Uploaded files/ }).click();
  await expect(page.getByRole("link", { name: "Analyze your files" })).toBeVisible();
  await page.getByRole("button", { name: /^Connected telemetry/ }).click();
  await expect(page.getByRole("link", { name: "Use Loki / Prometheus" })).toBeVisible();
  await page.getByRole("button", { name: /^Simulator/ }).click();
  await expect(page.getByLabel("Scenario")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Runtime health" })).toBeVisible();

  // Navigation verification
  await expect(page.getByRole("link", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Incidents", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Architecture", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Safety", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Guide", exact: true })).toBeVisible();

  // Assert no uncaught page errors
  expect(errors, `Uncaught page errors on overview: ${errors.join("; ")}`).toEqual([]);
});
