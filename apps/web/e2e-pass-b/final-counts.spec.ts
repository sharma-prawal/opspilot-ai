import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { investigationId, workbenchFixture } from "./fixtures";

test("cited and accessible evidence counts stay distinct on desktop and mobile", async ({ page }) => {
  const output = path.resolve(process.cwd(), "../../docs/images/pass-b/final-counts");
  await mkdir(output, { recursive: true });
  const widths: Record<string, number> = {};
  await workbenchFixture(page);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/investigations/${investigationId}`);
    await expect(page.getByText("3 cited supports (2 accessible · 1 unavailable) · 1 cited contradiction (1 accessible · 0 unavailable)", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /supports ev-missing/ }).click();
    await expect(page.getByRole("region", { name: "Contextual evidence inspector" })).toContainText("No corresponding record was returned for this exact citation");
    widths[String(width)] = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(widths[String(width)]).toBe(width);
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `counts-${width}.png`), fullPage: true });
  }
  await writeFile(path.join(output, "widths.json"), JSON.stringify(widths, null, 2));
});
