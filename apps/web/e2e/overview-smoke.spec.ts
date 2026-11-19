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
  await expect(page.getByText("Evidence-Grounded Distributed Incident Investigation")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Initiate Investigation Dossier" })).toBeVisible();

  // 3 Operating Modes tabs verification
  await expect(page.getByRole("button", { name: /1\. Simulated Fault Scenarios/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /2\. Uploaded Artifacts/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /3\. Connected Loki\/Prometheus/i })).toBeVisible();

  // Mode switching verification
  await page.getByRole("button", { name: /2\. Uploaded Artifacts/i }).click();
  await expect(page.getByText("Drop raw incident logs, CSV metric series, or JSON event traces")).toBeVisible();

  await page.getByRole("button", { name: /3\. Connected Loki\/Prometheus/i }).click();
  await expect(page.getByText("Audit Telemetry from Grafana Loki & Prometheus")).toBeVisible();

  await page.getByRole("button", { name: /1\. Simulated Fault Scenarios/i }).click();
  await expect(page.getByLabel("Scenario")).toBeVisible();

  // Runtime Seams & Health card verification
  await expect(page.getByRole("heading", { name: "Runtime Seams & Health" })).toBeVisible();

  // Navigation verification
  await expect(page.getByRole("link", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Incidents", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Architecture", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Safety", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Guide", exact: true })).toBeVisible();

  // Assert no uncaught page errors
  expect(errors, `Uncaught page errors on overview: ${errors.join("; ")}`).toEqual([]);
});
