import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";

const PORT = 3456;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const OUT_DIR = path.resolve(process.cwd(), "../../docs/images/prototype");

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

async function waitForServer(url, timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.status === 200) return true;
    } catch {
      // ignore retry
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`Server did not respond at ${url} within ${timeoutMs}ms`);
}

async function main() {
  console.log("Starting Next.js production server on port", PORT);
  const server = spawn("pnpm", ["next", "start", "-p", String(PORT)], {
    stdio: "inherit",
    env: { ...process.env, PORT: String(PORT) },
  });

  try {
    await waitForServer(`${BASE_URL}/prototype`);
    console.log("Next.js server is ready at", BASE_URL);

    const browser = await chromium.launch();

    // Desktop capture context
    const desktopContext = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      deviceScaleFactor: 2,
    });
    const desktopPage = await desktopContext.newPage();

    // Mobile capture context
    const mobileContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 2,
    });
    const mobilePage = await mobileContext.newPage();

    const screens = [
      { name: "evaluation-matrix-desktop", url: "/prototype", type: "desktop" },
      // Concept A Desktop
      { name: "concept-a-home-desktop", url: "/prototype/concept-a/home", type: "desktop" },
      { name: "concept-a-workbench-desktop", url: "/prototype/concept-a/workbench", type: "desktop" },
      { name: "concept-a-explorer-desktop", url: "/prototype/concept-a/explorer", type: "desktop" },
      { name: "concept-a-architecture-desktop", url: "/prototype/concept-a/architecture", type: "desktop" },
      { name: "concept-a-guide-desktop", url: "/prototype/concept-a/guide", type: "desktop" },
      // Concept A Mobile
      { name: "concept-a-home-mobile", url: "/prototype/concept-a/home", type: "mobile" },
      { name: "concept-a-workbench-mobile", url: "/prototype/concept-a/workbench", type: "mobile" },
      // Concept B Desktop
      { name: "concept-b-home-desktop", url: "/prototype/concept-b/home", type: "desktop" },
      { name: "concept-b-workbench-desktop", url: "/prototype/concept-b/workbench", type: "desktop" },
      { name: "concept-b-explorer-desktop", url: "/prototype/concept-b/explorer", type: "desktop" },
      { name: "concept-b-architecture-desktop", url: "/prototype/concept-b/architecture", type: "desktop" },
      { name: "concept-b-guide-desktop", url: "/prototype/concept-b/guide", type: "desktop" },
      // Concept B Mobile
      { name: "concept-b-home-mobile", url: "/prototype/concept-b/home", type: "mobile" },
      { name: "concept-b-workbench-mobile", url: "/prototype/concept-b/workbench", type: "mobile" },
    ];

    for (const sc of screens) {
      const page = sc.type === "desktop" ? desktopPage : mobilePage;
      const targetUrl = `${BASE_URL}${sc.url}`;
      console.log(`Capturing ${sc.name} from ${targetUrl}...`);
      await page.goto(targetUrl, { waitUntil: "networkidle" });
      await page.waitForTimeout(600); // allow font & css rendering to settle
      const outPath = path.join(OUT_DIR, `${sc.name}.png`);
      await page.screenshot({ path: outPath, fullPage: false });
      console.log(`Saved: ${outPath}`);
    }

    await browser.close();
    console.log("All screenshots successfully captured!");
  } finally {
    server.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error("Screenshot capture failed:", err);
  process.exit(1);
});
