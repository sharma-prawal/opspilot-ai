import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixture, investigationId } from "./fixtures";

const output = path.resolve(process.cwd(), "../../docs/images/pass-a/after");
test.beforeAll(async () => { await mkdir(output, { recursive: true }); });

for (const width of [390, 768, 1280, 1440]) {
  test(`responsive saved-history pages at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await fixture(page);
    const observations: Record<string, unknown> = {};
    for (const [name, url, heading] of [
      ["roster", "/incidents", "Incidents"], ["overview", "/", "System overview"],
      ["intake", "/incidents/new", "Analyze your data"],
      ["workbench", `/investigations/${investigationId}`, "Synthetic saved investigation"],
      ["architecture", "/architecture", "Interactive Architecture & Workflow Explorer"],
    ]) {
      await page.goto(url);
      if (name === "intake") await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      else if (name === "workbench") await expect(page.getByRole("heading", { level: 1, name: /SYNTHETIC-001/ })).toBeVisible();
      else await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
      if (name === "roster") {
        await expect(page.getByText("75 matching cases · complete history")).toBeVisible();
        for (const control of [page.getByLabel("Scenario"), page.getByRole("button", { name: "Simulate", exact: true })]) {
          const bounds = await control.boundingBox();
          expect(bounds).not.toBeNull();
          expect(bounds!.x).toBeGreaterThanOrEqual(0);
          expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
        }
        const region = page.getByLabel("Scrollable incident roster");
        if (width < 1000) expect(await region.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
        for (const label of ["Source", "State"]) {
          const bounds = await page.getByLabel(label, { exact: true }).boundingBox();
          expect(bounds!.width).toBeGreaterThanOrEqual(100);
          expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
        }
      }
      if (name === "architecture") await page.getByRole("button", { name: "Toggle accessible structured text hierarchy" }).click();
      await page.evaluate(() => document.fonts.ready);
      const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      observations[name] = { viewport: width, document: documentWidth };
      expect(documentWidth).toBe(width);
      await page.screenshot({ path: path.join(output, `${name}-${width}.png`), fullPage: true });
    }
    await writeFile(path.join(output, `observations-${width}.json`), JSON.stringify(observations, null, 2));
  });
}

test("complete-history search, filters and pagination", async ({ page }) => {
  await fixture(page);
  await page.goto("/incidents");
  await expect(page.getByText("1–50 of 75")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("51–75 of 75")).toBeVisible();
  await page.getByLabel("Search incidents").fill("Older needle");
  await expect(page.getByText("1–1 of 1")).toBeVisible();
  await expect(page.getByRole("link", { name: /SYNTHETIC-075/ })).toBeVisible();
  await page.getByLabel("Source", { exact: true }).selectOption("upload");
  await page.getByLabel("State", { exact: true }).selectOption("open");
  await expect(page.getByText("1–1 of 1")).toBeVisible();
  await page.getByLabel("State", { exact: true }).selectOption("resolved");
  await expect(page.getByText("No incidents match these filters.")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByText("1–50 of 75")).toBeVisible();
});

test("authorization remains independent of saved execution", async ({ page }) => {
  for (const [authorization, expected] of [["approve", "Approved — original-sre"], ["reject", "Rejected — original-sre"],
    ["expired", "Expired — original-sre"], ["pending", "Pending review"], ["unknown", "Authorization unknown"], ["unavailable", "Authorization unavailable"]] as const) {
    await page.unrouteAll();
    await fixture(page, { authorization });
    await page.goto(`/investigations/${investigationId}`);
    const sequence = page.getByLabel("Remediation decision sequence");
    await expect(sequence).toContainText(expected);
    await expect(sequence).toContainText(authorization === "pending" ? "Not executed" : "1 simulator results");
    if (authorization === "approve") await expect(sequence).toContainText("Approved — original-sre at 2026-11-20 12:00:00Z");
    if (authorization === "approve") {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.screenshot({ path: path.join(output, "saved-authorization-1440.png"), fullPage: true });
    }
  }
});

test("historical metrics label observation time and unknown latest sample time", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fixture(page, { source: "upload" });
  await page.goto(`/investigations/${investigationId}`);
  await expect(page.getByRole("heading", { name: "Collected investigation evidence" })).toBeVisible();
  await expect(page.getByText("Latest in collected evidence")).toBeVisible();
  await expect(page.getByText(/Evidence observation time: 2026-11-20 12:00:00Z/)).toBeVisible();
  await expect(page.getByText(/Latest sample time unavailable/)).toBeVisible();
  await expect(page.getByText("Current", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: path.join(output, "historical-metrics-1440.png"), fullPage: true });
  await page.unrouteAll();
  await fixture(page, { source: "upload", observationTime: null });
  await page.reload();
  await expect(page.getByText(/Evidence observation time unavailable/)).toBeVisible();
  await expect(page.getByText(/Latest sample time unavailable/)).toBeVisible();
});

for (const width of [390, 768]) test(`disclosure navigation and account at ${width}px`, async ({ page }) => {
  await fixture(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/incidents");
  const toggle = page.locator(".nav-toggle");
  await expect(toggle).toHaveAccessibleName(/Open navigation/);
  await toggle.click();
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(nav.getByRole("link", { name: "Incidents", exact: true })).toHaveAttribute("aria-current", "page");
  for (const label of ["Overview", "Incidents", "Analyze data", "Architecture", "Integrations", "Guide", "Safety", "Approvals", "Knowledge"]) {
    const link = nav.getByRole("link", { name: label, exact: true });
    await link.scrollIntoViewIfNeeded();
    await expect(link).toBeVisible();
  }
  await expect(nav.getByText("synthetic-operator · operator")).toBeVisible();
  const signOut = nav.getByRole("button", { name: "Sign out" });
  await signOut.scrollIntoViewIfNeeded();
  const box = await signOut.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(1000);
  await page.screenshot({ path: path.join(output, `navigation-open-${width}.png`), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await nav.getByRole("link", { name: "Architecture", exact: true }).click();
  await expect(page).toHaveURL(/\/architecture$/);
  await expect(page.getByRole("button", { name: /Open navigation · Architecture/ })).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: /Open navigation/ }).click();
  const logout = page.waitForRequest(request => request.url().endsWith("/api/session") && request.method() === "DELETE");
  await nav.getByRole("button", { name: "Sign out" }).click();
  expect((await logout).headers()["x-opspilot-csrf"]).toBe("synthetic-test-csrf");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in to OpsPilot AI" })).toBeVisible();
});

test("architecture pointer, Enter and Space synchronize inspector and edges", async ({ page }) => {
  await fixture(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/architecture");
  const nodes = page.locator(".react-flow__node");
  await expect(nodes.first()).toBeVisible();
  for (const [index, key] of [[0, "Enter"], [1, "Space"]] as const) {
    const node = nodes.nth(index);
    const id = await node.getAttribute("data-id");
    await node.focus();
    await page.keyboard.press("Tab");
    await expect(nodes.nth(index + 1)).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(node).toBeFocused();
    await node.press(key);
    await expect(node).toHaveClass(/selected/);
    await expect(node).toBeFocused();
    await expect(node).toHaveCSS("outline-style", "solid");
    await expect(node).toHaveCSS("outline-width", "2px");
    const selectedName = (await page.getByRole("status").filter({ hasText: /^Selected / }).textContent())!.replace(/^Selected /, "");
    await expect(page.getByRole("heading", { level: 2, name: selectedName, exact: true })).toBeVisible();
    const connected = page.locator(`.react-flow__edge[aria-label^="Edge from ${id} to "], .react-flow__edge[aria-label$=" to ${id}"]`);
    expect(await connected.count()).toBeGreaterThan(0);
    await expect(connected.first().locator(".react-flow__edge-path")).toHaveCSS("opacity", "1");
    expect(await page.locator('.react-flow__edge-path[style*="opacity: 0.35"]').count()).toBeGreaterThan(0);
  }
  await page.screenshot({ path: path.join(output, "architecture-keyboard-1440.png"), fullPage: true });
  await nodes.nth(2).click();
  await expect(nodes.nth(2)).toHaveClass(/selected/);
});
