/** Isolated browser verification and actual implementation screenshots. All API data is labeled synthetic. */
import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  fixtureState,
  installFixtures,
} from "./fixtures/visual-experience-2.mjs";

const root = resolve(import.meta.dirname, "../../..");
const out = resolve(root, "docs/images/visual-experience-2");
const port = 3199;
const base = `http://127.0.0.1:${port}`;
const results = [];
async function assertPortFree() {
  const probe = createServer();
  await new Promise((res, rej) => {
    probe.once("error", rej);
    probe.listen(port, "127.0.0.1", res);
  });
  await new Promise((res) => probe.close(res));
}
await assertPortFree();
const safeEnv = Object.fromEntries(
  ["PATH", "HOME", "TMPDIR", "LANG"]
    .filter((k) => process.env[k])
    .map((k) => [k, process.env[k]]),
);
const server = spawn(
  "pnpm",
  ["exec", "next", "start", "--hostname", "127.0.0.1", "-p", String(port)],
  {
    cwd: resolve(root, "apps/web"),
    env: { ...safeEnv, NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let logs = "";
server.stdout.on("data", (chunk) => {
  logs += chunk;
});
server.stderr.on("data", (chunk) => {
  logs += chunk;
});
let browser;
try {
  await mkdir(out, { recursive: true });
  let ready = false;
  for (let n = 0; n < 60; n++) {
    try {
      if ((await fetch(base)).status < 500) {
        ready = true;
        break;
      }
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!ready) throw new Error(`Isolated server failed: ${logs}`);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const state = fixtureState();
  await installFixtures(page, state);
  const check = async (name, fn) => {
    await fn();
    results.push({ check: name, passed: true });
    console.log(`PASS ${name}`);
  };
  const visit = async (path) => {
    await page.goto(`${base}${path}`);
    await page.getByRole("navigation", { name: "Primary" }).waitFor();
    await page.getByRole("button", { name: "Sign out", exact: true }).waitFor();
    await page.addStyleTag({ content: 'body::before { content: "SYNTHETIC UI FIXTURES · NO LIVE OPERATIONS"; display: block; padding: 6px 10px; background: #1c2529; color: white; text-align: center; font: 10px monospace; }' });
  };
  const shot = async (name) => {
    await page.evaluate(async () => {
      await document.fonts.ready;
      document.activeElement?.blur();
      window.scrollTo(0, 0);
      await new Promise((r) =>
        requestAnimationFrame(() => requestAnimationFrame(r)),
      );
    });
    await page.screenshot({
      path: resolve(out, `${name}.png`),
      fullPage: true,
    });
  };
  const noOverflow = async () => {
    const overflow = await page.evaluate(() => ({
      width: innerWidth,
      actual: document.documentElement.scrollWidth,
      elements: [...document.querySelectorAll("main *")]
        .filter((e) => {
          const r = e.getBoundingClientRect();
          return (
            r.right > innerWidth + 1 &&
            !e.closest(
              ".overflow-x-auto,.evidence-map-scroll,.source-timeline,.workbench-tabs",
            )
          );
        })
        .slice(0, 8)
        .map((e) => ({
          tag: e.tagName,
          classes: e.className,
          text: e.textContent.slice(0, 90),
        })),
    }));
    expect(overflow.actual, JSON.stringify(overflow)).toBeLessThanOrEqual(
      overflow.width + 1,
    );
  };

  await check("home intake, runtime and three source modes", async () => {
    await visit("/");
    await expect(
      page.getByRole("heading", { name: "Open an investigation." }),
    ).toBeVisible();
    await expect(
      page.getByText("local-model:synthetic-fixture", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /^Uploaded files/ }).click();
    await expect(
      page.getByRole("link", { name: "Analyze your files" }),
    ).toBeVisible();
    await page.getByRole("button", { name: /^Connected telemetry/ }).click();
    await expect(
      page.getByRole("link", { name: "Use Loki / Prometheus" }),
    ).toBeVisible();
    expect(await page.getByText(/Connected Loki 3/).count()).toBe(0);
    await page.getByRole("button", { name: /^Simulator/ }).click();
    await page.getByLabel("Scenario").selectOption("INC-002");
    await noOverflow();
    await shot("home-desktop");
    await page.setViewportSize({ width: 390, height: 844 });
    await noOverflow();
    await shot("home-mobile");
    await page.setViewportSize({ width: 1440, height: 960 });
  });
  await check(
    "roster search, source filter, clear and linked case",
    async () => {
      await visit("/incidents");
      await expect(page.getByRole("table")).toBeVisible();
      await page.getByRole("searchbox").fill("checkout");
      await expect(page.locator("tbody tr")).toHaveCount(1);
      await page.getByRole("searchbox").fill("no-match");
      await expect(
        page.getByText("No incidents match these filters."),
      ).toBeVisible();
      await page.getByRole("button", { name: "Clear filters" }).click();
      await page.getByLabel("Source", { exact: true }).selectOption("upload");
      await expect(page.locator("tbody tr")).toHaveCount(1);
      await page.getByLabel("Source", { exact: true }).selectOption("all");
      await shot("roster-desktop");
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await shot("roster-mobile");
      await page.setViewportSize({ width: 1440, height: 960 });
    },
  );
  await check(
    "hypothesis selection, contradiction and exact source payload",
    async () => {
      await visit("/investigations/demo-investigation");
      await expect(
        page.getByRole("heading", { name: "Root Cause Hypotheses" }),
      ).toBeVisible();
      await expect(
        page.getByText(
          "Model-estimated confidence, not a calibrated statistical probability (uncalibrated).",
          { exact: false },
        ),
      ).toBeVisible();
      await page
        .getByRole("button", { name: /Database connection pressure/ })
        .click();
      await expect(page.getByText("1 contradicting")).toBeVisible();
      await expect(
        page.getByRole("button", { name: /Logs · Contradicts/ }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: /ev-log-schema · contradicts/ })
        .click();
      await expect(page.locator("pre")).toContainText("amount_cents");
      await expect(
        page.getByText("ledger.log:line 42", { exact: true }),
      ).toBeVisible();
      await shot("evidence-desktop");
      await page
        .getByRole("button", { name: /Analysis & Remediation/ })
        .click();
      await page
        .getByRole("button", { name: /Schema migration broke/ })
        .click();
      await shot("workbench-desktop");
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await shot("workbench-mobile");
      await page.setViewportSize({ width: 1440, height: 960 });
    },
  );
  await check("review action link opens and focuses remediation from the evidence tab", async () => {
    await page.getByRole("button", { name: /Collected Evidence/ }).click();
    await page.getByRole("region", { name: "Leading conclusion" }).getByRole("link", { name: /Review proposed action/ }).click();
    await expect(page.locator("#remediation-section")).toBeFocused();
    await expect(page.getByRole("button", { name: /Analysis & Remediation/ })).toHaveAttribute("aria-pressed", "true");
  });
  await check(
    "metric comparison and source chronology open their real record",
    async () => {
      await page
        .getByRole("button", { name: "http_5xx_ratio", exact: true })
        .click();
      await expect(page.locator("pre")).toContainText('"baseline": 0.001');
      await expect(page.getByRole("button", { name: "Inspect ev-metric-errors", exact: true })).toBeFocused();
      await page
        .getByRole("button", { name: /Analysis & Remediation/ })
        .click();
      await page
        .getByRole("list", { name: "Source evidence chronology" })
        .getByRole("button")
        .first()
        .click();
      await expect(page.locator("pre")).toContainText("demo-deploy-42");
    },
  );
  await check(
    "evidence composition filters actual source category",
    async () => {
      await page
        .getByRole("button", { name: /Analysis & Remediation/ })
        .click();
      await page
        .getByRole("figure", { name: "Collected evidence composition" })
        .getByRole("button", { name: /Logs/ })
        .click();
      await expect(
        page.getByRole("button", { name: /Inspect ev-log-schema/ }),
      ).toBeVisible();
      expect(
        await page
          .getByRole("button", { name: /Inspect ev-metric-errors/ })
          .count(),
      ).toBe(0);
      await page.getByRole("button", { name: "Show all categories" }).click();
      await expect(
        page.getByRole("button", { name: /Inspect ev-metric-errors/ }),
      ).toBeVisible();
    },
  );
  await check(
    "approval submits exact action hash and completed recovery stays simulator-specific",
    async () => {
      await page
        .getByRole("button", { name: /Analysis & Remediation/ })
        .click();
      await page
        .getByLabel("Comment (optional)")
        .fill("Synthetic approval test");
      await page
        .getByRole("button", { name: /Approve & execute in sandbox/ })
        .click();
      await expect(
        page.getByText("VERIFIED SIMULATOR RECOVERY", { exact: true }),
      ).toBeVisible();
      expect(state.decisions[0].params_hash).toBe("synthetic-parameter-hash");
      expect(state.decisions[0].decision).toBe("approve");
      await expect(page.locator(".prose-report")).toHaveCount(0);
      await page.getByRole("button", { name: "Expand Report" }).click();
      await expect(page.locator(".prose-report")).toContainText(
        "Ranked hypotheses",
      );
      const download = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download Markdown" }).click();
      expect((await download).suggestedFilename()).toMatch(/RCA-.*\.md/);
      await shot("completed-desktop");
    },
  );
  for (const source of ["upload", "connector"])
    await check(
      `${source} remains read-only with suggestions and no approval controls`,
      async () => {
        state.source = source;
        state.status = "completed";
        await visit("/investigations/demo-investigation");
        await expect(
          page.getByText("Nothing executed", { exact: true }),
        ).toBeVisible();
        expect(
          await page.getByRole("button", { name: /Approve & execute/ }).count(),
        ).toBe(0);
        expect(
          await page
            .getByText("VERIFIED SIMULATOR RECOVERY", { exact: true })
            .count(),
        ).toBe(0);
        if (source === "upload") await shot("readonly-desktop");
      },
    );
  await check(
    "blocked-only result never indicates admitted plan or execution",
    async () => {
      state.source = "simulator";
      state.blockedOnly = true;
      await visit("/investigations/demo-investigation");
      await expect(page.getByText("Blocked", { exact: true })).toBeVisible();
      await expect(
        page.getByText("No approval recorded", { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText("Not executed", { exact: true }),
      ).toBeVisible();
      expect(
        await page.getByRole("button", { name: /Approve & execute/ }).count(),
      ).toBe(0);
      await shot("blocked-desktop");
      state.blockedOnly = false;
    },
  );
  await check(
    "normal running and failure states remain inspectable",
    async () => {
      state.status = "running";
      await visit("/investigations/demo-investigation");
      await expect(page.getByText("Following the evidence…")).toBeVisible();
      state.status = "failed";
      await visit("/investigations/demo-investigation");
      await expect(
        page.getByText("INVESTIGATION FAILED", { exact: true }),
      ).toBeVisible();
    },
  );
  await check(
    "integration implementation differs from configured and tested health",
    async () => {
      await visit("/integrations");
      await expect(
        page.getByRole("table", { name: /Implemented capabilities/ }),
      ).toBeVisible();
      await expect(
        page.getByText("Not tested", { exact: true }).first(),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Test connection", exact: true })
        .click();
      await expect(page.getByText("Synthetic Loki answered.")).toBeVisible();
      await shot("integrations-desktop");
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await shot("integrations-mobile");
      await page.setViewportSize({ width: 1440, height: 960 });
    },
  );
  await check("architecture diagrams and accessible tree", async () => {
    await visit("/architecture");
    await expect(page.getByText("FastAPI REST Runner").first()).toBeVisible();
    for (const name of [/Diagram B/, /Diagram C/, /Diagram D/, /Diagram A/])
      await page.getByRole("tab", { name }).click();
    await shot("architecture-desktop");
    await page
      .getByRole("button", {
        name: "Toggle accessible structured text hierarchy",
      })
      .click();
    await expect(
      page.getByRole("heading", { name: "Structured Architectural Hierarchy" }),
    ).toBeVisible();
  });
  await check(
    "safety boundary and guide preserve technical detail on demand",
    async () => {
      await visit("/safety");
      await expect(
        page.getByRole("list", { name: "Safety enforcement sequence" }),
      ).toBeVisible();
      await expect(
        page.getByText(/not cryptographically certified/),
      ).toBeVisible();
      await shot("safety-desktop");
      await visit("/guide");
      await expect(
        page.getByRole("navigation", { name: "Investigation walkthrough" }),
      ).toBeVisible();
      await page.getByRole("button", { name: /Local Setup/ }).click();
      await expect(
        page.locator("pre").filter({ hasText: "make bootstrap ARGS=--install" }),
      ).toBeVisible();
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await shot("guide-mobile");
      await page.setViewportSize({ width: 1440, height: 960 });
    },
  );
  await check("loading, empty and unavailable backend states", async () => {
    state.loading = true;
    state.empty = true;
    await visit("/");
    await expect(
      page.getByRole("status", { name: "Loading recent incidents" }),
    ).toBeVisible();
    await expect(page.getByText(/No investigations yet/)).toBeVisible();
    state.loading = false;
    state.unavailable = true;
    await visit("/");
    await expect(page.getByText("unavailable", { exact: true })).toBeVisible();
    await expect(page.getByText("Open cases", { exact: false })).toContainText(
      "—",
    );
    await shot("unavailable-desktop");
  });
  expect(errors).toEqual([]);
  await writeFile(
    resolve(out, "verification.json"),
    JSON.stringify(
      {
        data: "Explicitly synthetic fixtures",
        server: "Isolated production frontend :3199; no live API/database/LLM",
        results,
        pageErrors: errors,
      },
      null,
      2,
    ) + "\n",
  );
  console.log(`${results.length} browser checks passed; screenshots: ${out}`);
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  await new Promise((resolve) => {
    if (server.exitCode !== null) resolve();
    else server.once("exit", resolve);
  });
}
