import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { signIn } from "./auth";
import { assertIsolated } from "./isolation";

// v0.5: files are picked from disk (setInputFiles), previewed, investigated read-only by the real local model,
// the cited report is downloaded, and the upload is deleted with its files.
const nav = { noWaitAfter: true } as const;
const EXAMPLES = path.resolve(__dirname, "../public/examples/uploads");
const FILES = ["checkout-api.log", "service-metrics.csv", "change-events.json", "checkout-traces.json"];
const UPLOAD_DIR = process.env.E2E_UPLOAD_DIR ?? path.resolve(__dirname, "../../../var/e2e-uploads");

test("operator uploads files from disk, gets a cited read-only RCA, downloads it and deletes the upload", async ({ page }) => {
  test.setTimeout(480_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await signIn(page);
  assertIsolated(await (await page.request.get("/api/ops/api/v1/system/identity")).json(), "browser session");
  await page.goto("/incidents/new");
  await expect(page.getByRole("heading", { name: "Analyze your own incident data" })).toBeVisible();

  await page.getByLabel("Title", { exact: true }).fill("Checkout payments failing (e2e)");
  await page.getByLabel("Description", { exact: true }).fill("Payment errors at checkout; synthetic files picked from disk.");
  await page.getByLabel("Affected service", { exact: true }).fill("checkout-api");
  await page.getByLabel("Other affected services", { exact: true }).fill("payment-service");
  await page.getByLabel("Approximate incident time", { exact: true }).fill("2026-11-12T09:16");
  await page.getByLabel("Timezone", { exact: true }).selectOption("UTC");

  const input = page.locator('input[type="file"]');
  await input.setInputFiles(FILES.map((f) => path.join(EXAMPLES, f))); // real files from disk
  await input.setInputFiles({ name: "notes.sh", mimeType: "text/plain", buffer: Buffer.from("echo not evidence") });
  await expect(page.getByText("Unsupported type .sh")).toBeVisible();
  await page.getByRole("button", { name: "Remove notes.sh" }).click();
  await expect(page.getByLabel("Service for checkout-api.log")).toHaveValue("checkout-api"); // text logs default

  await page.getByRole("button", { name: "Preview extracted evidence" }).click();
  await expect(page.getByRole("heading", { name: "3. Extracted evidence" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Logs (129)" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Metrics (456)" })).toBeVisible();
  await expect(page.getByText(/^checkout-api\.log:line \d+$/).first()).toBeVisible();
  await expect(page.getByText(/credential.* redacted/).first()).toBeVisible();

  await page.getByRole("button", { name: "Create incident & start analysis" }).click(nav);
  await page.waitForURL(/\/investigations\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Read-only analysis of uploaded evidence.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "RCA Postmortem Report" })).toBeVisible({ timeout: 420_000 });

  await expect(page.getByText(/Analysis (complete|inconclusive)/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0); // read-only: nothing to approve
  await expect(page.getByText("Supporting evidence:").first()).toBeVisible();
  const report = page.locator(".prose-report");
  await expect(report).toContainText("Ranked hypotheses");
  await expect(report).toContainText(/source: (checkout-api\.log|service-metrics\.csv|change-events\.json|checkout-traces\.json)/);
  await page.screenshot({ path: "test-results/upload-analysis.png", fullPage: true });

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download Markdown" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^RCA-INC-\d{8}-\d{4}\.md$/);
  const md = readFileSync(await download.path(), "utf-8");
  expect(md).toContain("Uploaded evidence — read-only analysis");
  expect(md).toContain("Recommended next investigation steps");
  expect(md).not.toContain("sk_test_EXAMPLE"); // the credential in the example log never reaches the report

  const incidentHref = await page.getByRole("link", { name: "incident view" }).getAttribute("href");
  const incidentId = incidentHref!.split("/").pop()!;
  const ds = await (await page.request.get(`/api/ops/api/v1/incidents/${incidentId}/dataset`)).json();
  const stored = path.join(UPLOAD_DIR, ds.dataset_id);
  expect(existsSync(stored)).toBe(true);

  await page.goto(`/incidents/${incidentId}`);
  await page.getByRole("button", { name: "Delete uploaded data" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click(nav);
  await page.waitForURL("**/incidents");
  expect((await page.request.get(`/api/ops/api/v1/incidents/${incidentId}`)).status()).toBe(404);
  expect(existsSync(stored)).toBe(false); // raw uploaded files are removed
  expect(errors, `uncaught page errors: ${errors.join("; ")}`).toEqual([]);
});
