/** Raster delivery exports from the original local SVG sources; no remote imagery. */
import { chromium } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
const brand = resolve(import.meta.dirname, "../public/brand");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1100, height: 1100 },
    deviceScaleFactor: 1,
  });
  const exports = [
    ["logo-light", 930, 192],
    ["logo-dark", 930, 192],
    ["symbol-light", 256, 256],
    ["symbol-dark", 256, 256],
    ["app-icon", 512, 512],
    ["app-icon", 192, 192],
    ["app-icon", 32, 32],
  ];
  for (const [name, width, height] of exports) {
    const svg = await readFile(resolve(brand, `${name}.svg`), "utf8");
    await page.setContent(
      `<style>body{margin:0}svg{display:block;width:${width}px;height:${height}px}</style>${svg}`,
    );
    await page
      .locator("svg")
      .screenshot({
        path: resolve(brand, `${name}-${width}.png`),
        omitBackground: true,
      });
  }
} finally {
  await browser.close();
}
