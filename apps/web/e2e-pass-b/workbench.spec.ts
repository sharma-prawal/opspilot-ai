import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { hypotheses, investigationId, workbenchFixture } from "./fixtures";

const output = path.resolve(process.cwd(), "../../docs/images/pass-b/after");
test.beforeAll(async () => { await mkdir(output, { recursive: true }); });
for (const width of [390, 768, 1280, 1440]) {
  test(`contextual evidence and responsive layout at ${width}px`, async ({ page }) => {
    await workbenchFixture(page);
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/investigations/${investigationId}`);
    await expect(page.getByRole("heading", { name: "Leading hypothesis & evidence" })).toBeVisible();
    await expect(page.getByLabel("Hypotheses and citations").getByText(hypotheses[0].title, { exact: true })).toBeVisible();
    await expect(page.getByText("Historical evidence · not live operational health")).toBeVisible();
    const leading = await page.getByLabel("Hypotheses and citations").getByText(hypotheses[0].title, { exact: true }).boundingBox();
    if (width >= 1280) expect(leading!.y).toBeLessThan(850);
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `workbench-${width}.png`), fullPage: true });
    const citation = page.getByRole("button", { name: /supports ev-config/ });
    await citation.focus();
    await page.keyboard.press("Enter");
    const inspector = page.getByRole("region", { name: "Contextual evidence inspector" });
    const heading = inspector.getByRole("heading", { name: "Evidence inspector" });
    await expect(heading).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(inspector.getByRole("button", { name: "Close inspector" })).toBeFocused();
    await expect(inspector).toContainText("Supports hypothesis 1");
    await expect(inspector).toContainText("cloudwatch/lifecycle/checkout-api:entry 3");
    await expect(citation).toHaveAttribute("aria-pressed", "true");
    const claimBounds = await page.getByLabel("Hypotheses and citations").boundingBox();
    const inspectorBounds = await inspector.boundingBox();
    if (width <= 768) expect(inspectorBounds!.y).toBeGreaterThanOrEqual(claimBounds!.y + claimBounds!.height - 1);
    else expect(Math.abs(inspectorBounds!.y - claimBounds!.y)).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `inspector-${width}.png`), fullPage: true });
    await page.keyboard.press("Escape");
    await expect(citation).toBeFocused();
    await expect(citation).toHaveAttribute("aria-pressed", "false");
    await citation.press("Space");
    await expect(heading).toBeFocused();
    await expect(heading).toHaveCSS("outline-style", "solid");
    const font = await page.getByText(hypotheses[0].description, { exact: true }).evaluate(el => getComputedStyle(el).fontSize);
    await writeFile(path.join(output, `observations-${width}.json`), JSON.stringify({ viewport: width,
      document: await page.evaluate(() => document.documentElement.scrollWidth), claimBounds, inspectorBounds, font, errors }, null, 2));
    expect(errors).toEqual([]);
  });
}
test("selection synchronizes relationships, missing records and alternative hypotheses", async ({ page }) => {
  await workbenchFixture(page); await page.goto(`/investigations/${investigationId}`);
  const inspector = page.getByRole("region", { name: "Contextual evidence inspector" });
  await page.getByRole("button", { name: /contradicts ev-traffic/ }).click();
  await expect(inspector).toContainText("Contradicts hypothesis 1");
  await page.getByRole("button", { name: /Alternative · rank 2/ }).click();
  await expect(inspector).toContainText("Contradicts hypothesis 2");
  await page.getByRole("button", { name: /Leading explanation/ }).click();
  await page.getByRole("button", { name: /supports ev-missing/ }).click();
  await expect(inspector).toContainText("No corresponding record was returned for this exact citation");
  await expect(inspector).toContainText("ev-missing");
  await page.getByRole("button", { name: /Collected Evidence/ }).click();
  await page.getByRole("button", { name: "Inspect ev-traffic" }).press("Enter");
  await expect(inspector).toContainText("Contradicts hypothesis 1");
});
test("provider coverage and original report warnings remain inspectable", async ({ page }) => {
  await workbenchFixture(page); await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/investigations/${investigationId}`);
  await page.getByText("Coverage details and provider provenance", { exact: true }).click();
  const coverage = page.getByRole("region", { name: "Evidence coverage and uncertainty" });
  for (const label of ["No accessible matching records — access/coverage not independently verified.", "Sampling coverage is limited; correlation is incomplete.", "Deployment/change history is unknown"]) await expect(coverage.getByText(label, { exact: true })).toBeVisible();
  await expect(coverage).toContainText("Not attempted");
  await expect(coverage).toContainText("Unavailable");
  await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, "coverage-1440.png"), fullPage: true });
  await page.getByText(/Model summary and report-reading notes/).click();
  await expect(page.getByText("Unsupported causal assertion: an observed change is not a verified cause.", { exact: true })).toBeVisible();
  await expect(page.getByText(/Model claims the configuration change caused/)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export RCA report" }).click();
  expect((await download).suggestedFilename()).toBe("RCA-SYNTHETIC-001.md");
});
for (const source of ["connector", "upload"] as const) test(`${source} remains read-only with unverified recovery`, async ({ page }) => {
  await workbenchFixture(page, source); await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/investigations/${investigationId}`);
  await expect(page.getByText(/Nothing executed; external recovery is unverified/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/ })).toHaveCount(0);
  await expect(page.getByLabel("Remediation decision sequence")).toHaveCount(0);
  await expect(page.getByText("Restarting may reload the same persisted configuration.", { exact: false })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `${source}-readonly-1440.png`), fullPage: true });
});
for (const pending of [true, false]) test(`simulator ${pending ? "pending authorization" : "completed verification"} stays distinct`, async ({ page }) => {
  await workbenchFixture(page, "simulator", pending); await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/investigations/${investigationId}`);
  const sequence = page.getByLabel("Remediation decision sequence");
  await expect(sequence).toContainText(pending ? "Pending review" : "Approved — original-sre");
  await expect(sequence).toContainText(pending ? "Not executed" : "1 simulator results");
  await expect(sequence).toContainText(pending ? "Not verified" : "Simulator recovery verified");
  if (pending) {
    await page.getByRole("link", { name: "Review exact proposed action" }).click();
    await expect(page.getByRole("button", { name: /Approve & execute in sandbox/ })).toBeFocused();
    await expect(page.locator("[data-pending-approval] form")).toContainText("Deciding as");
  }
  await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `simulator-${pending ? "pending" : "verified"}-1440.png`), fullPage: true });
});

test("workbench contrast samples and reduced-motion preference", async ({ page }) => {
  await workbenchFixture(page, "simulator", true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/investigations/${investigationId}`);
  await expect(page.locator(".workbench .animate-pulse").first()).toHaveCSS("animation-name", "none");
  const samples = await page.evaluate(() => {
    const rgb = (value: string) => (value.match(/[\d.]+/g) ?? []).map(Number);
    const blend = (top: number[], bottom: number[]) => {
      const alpha = top[3] ?? 1;
      return top.slice(0, 3).map((value, i) => value * alpha + bottom[i] * (1 - alpha));
    };
    const luminance = (color: number[]) => color.slice(0, 3).map(v => {
      const n = v / 255; return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, n, i) => sum + n * [0.2126, 0.7152, 0.0722][i], 0);
    return [".review-hypothesis-pick strong", ".review-hypothesis-pick .text-muted", ".hypothesis-review .claim-notes", ".citation-record .text-success", ".citation-record .text-danger"].map(selector => {
      const el = document.querySelector(selector)!;
      const ancestors: Element[] = []; for (let node: Element | null = el; node; node = node.parentElement) ancestors.unshift(node);
      let bg = [255, 255, 255];
      for (const node of ancestors) bg = blend(rgb(getComputedStyle(node).backgroundColor), bg);
      const fg = blend(rgb(getComputedStyle(el).color), bg);
      const a = luminance(fg), b = luminance(bg);
      return { selector, contrast: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
    });
  });
  for (const sample of samples) expect(sample.contrast, sample.selector).toBeGreaterThanOrEqual(4.5);
  await writeFile(path.join(output, "accessibility-samples.json"), JSON.stringify(samples, null, 2));
});
