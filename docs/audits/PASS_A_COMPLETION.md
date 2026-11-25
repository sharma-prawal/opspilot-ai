# OpsPilot AI — UI Pass A verification and local integration

24 November 2026. Verification complete; local-main activation deferred. Scope: F01/F02/F03/F06 and architecture keyboard behavior only.
Pass B has not started. Nothing has been pushed, tagged, released or published.

## Baseline and implementation

- Feature: `/Users/prawalsharma/Documents/Projects/opspilot-ui-pass-a`, branch `feature/ui-pass-a-mac`.
- Starting HEAD: `313ef6c1d674e9e8d36d08ba5054807ffac2177f`.
- Designated main: `/Users/prawalsharma/.gemini/antigravity/worktrees/opspilot-ai/product_ui_redesign`;
  clean, on `main`, at the same expected baseline, without divergence.
- Preserved/reviewed the intentional uncommitted Mac implementation. No worktree created, old Linux commit
  recovered, implementation recreated or design direction changed during this verification session.
- Earlier implementation provenance: supplied
  [completion record](https://chatgpt.com/library?file_id=libfile_b047dbf341b48191b32bfb135dff3690&account_id=personal),
  associated with approved Pass A `717430523cc51ec271ecfcaa3159989c04b95c84`. The accepted visual-audit ZIP
  was not locally available. New captures are after-only, not a before/after comparison.

| Area | Final behavior |
|---|---|
| F01 | Action DTOs use persisted identity/hash-matched decisions with original actor and aware timestamp. Approved/rejected/expired/pending/unknown/unavailable stay separate from execution and verification; success never establishes approval |
| F02 | Complete-history reference/title/service search, literal bound substrings, source/status filters, same-statement total/page, stable `(created_at DESC, id DESC)` order and empty-page totals. Legacy arrays remain available; overview source counts cover all history |
| F03 | “Collected investigation evidence” / “Latest in collected evidence”; recorded observation time is explicitly an observation time, missing/latest-sample times stay unknown. Historical summaries remain separate from verification and live health |
| F06 | Shrinkable/wrapping simulator controls and ancestors, contained roster table, readable mobile filters, navigation disclosure through 800 px with destinations/account/logout, Escape focus restoration and route-close behavior |
| Architecture | Pointer/Enter/Space synchronize selected node, inspector, edge emphasis and announcement; Tab navigation and visible focus preserved |

[API contracts](../architecture/API_CONTRACTS.md#pass-a-saved-history-and-bounded-search-2026-11-24):
search q ≤ 200, source/status enums, limit 1–100 (default 50), offset 0–100000; legacy array limit 1–200.
Invalid bounds return 422. No migration, dependency/lockfile, agent/prompt/model, connector, write-path,
MCP policy or simulator safety-gate changes.

## Isolated execution

The managed sandbox denies sockets; a single authorized unrestricted local-execution preflight succeeded.
Required checks then ran in that context, without bypasses, permission changes or approval-review rejections.

- Connected explicitly to `opspilot_test`; checked `current_database()` and found no other test clients.
  Ports 8100, 3100 and 3185 were free.
- Selected only existing DB connection/MCP-role keys in memory from main's configuration (fallback: original
  checkout). No `.env` was copied, changed or printed. No credentials were exposed.
- Allowlisted host environment; pinned test DB; disposable upload directories; synthetic operator/signing/session
  secrets and passphrases. Live providers disabled. Connector tests explicitly use loopback fixtures/SDK stubs.
- Pass A browser: production app on 3185, intercepted synthetic API/session data, no API/DB process.
  Next.js now starts through the existing secure `opspilot_shared.web_env --exec` allowlist.
- Existing simulator regression: `playwright.config.ts`, API 8100, web 3100, test DB/uploads/sessions, local Ollama.
  Direct API and authenticated BFF identity guards precede any mutation; remediation is synthetic sandbox only.

## Final validation

| Gate | Result |
|---|---|
| `make lint` | Pass: Ruff/format, strict mypy (116 files), 4 import contracts, ESLint, Next typegen/TypeScript |
| `make test` / full Python | Pass: 725 passed, 5 legitimate skips, 0 failures/errors in 263.68 s |
| Frontend Vitest (inside `make test`) | Pass: 86 tests, 14 files, 0 failures/skips |
| `pnpm build` | Pass: normal production Turbopack build, 28 routes; no font mock or build-source change |
| `pnpm exec playwright test --config playwright.pass-a.config.ts` | 10 passed, 0 failed/skipped; Chromium against production build |
| Existing simulator approval/recovery + BFF authentication | 4 passed, 0 failed/skipped in 1.5 min; local-model INC-001 approval/rollback/recovery plus 3 authentication journeys |
| `git diff --check` | Pass |
| Screenshots/widths | 25 valid PNGs; all 20 document widths equal their 390/768/1280/1440 viewports |

Skips: three opt-in local-model tests and two live Loki/Prometheus checks (optional test containers stopped).
MCP-role security tests ran using existing role credentials. No private Phase C1 evaluation; no `make evaluate`
because agent/simulator behavior is unchanged; no new benchmark or agent-quality number claimed.

Commands are the existing `make lint`, `make test`, `pnpm build`, Pass A Playwright config and standard
Playwright config (`pnpm exec playwright test --config playwright.config.ts e2e/investigation.spec.ts e2e/auth.spec.ts`).
Temporary `/tmp/opspilot-pass-a-verify.py` supplies the isolated environment above, never
copies all `.env` values into subprocesses, and is not product source. Detailed logs:
`/tmp/opspilot-pass-a-final-{test,lint,turbopack,browser,regression}.log`.
Tracked evidence: [validation summary](pass-a-validation.txt), [browser JSON](pass-a-playwright.json).

## Corrections and resolved blockers

1. React Flow suppressed the generic focus outline. A scoped node `:focus-visible` rule restores the existing
   accent outline; Chromium checks its style/width after Tab and Enter/Space.
2. At 390 px filter selects fit but their values were cramped. Mobile search now takes its own row; source/state
   keep readable widths, with browser assertions requiring each select ≥ 100 px.
3. Previously denied DB/fixture sockets, test server binding and Chromium launch work in authorized execution.
4. Webpack compiles but omits this repo's Turbopack-only Tailwind transform: it is **not** accepted as rendered
   evidence. The documented normal `pnpm build` now succeeds and supplies all final screenshots.
5. Browser selectors now target the visible workbench heading, stable toggle and level-2 inspector heading,
   avoiding collapsed content, a changing accessible name and duplicate heading text. No behavior assertion
   was weakened. Added logout/CSRF, pending authorization, missing observation time, Tab/focus and service/reference checks.
6. The initial web unit run inherited browser origin 3185 while BFF fixtures use 3000 (three 403 assertion
   failures). Corrected the temporary runner's unit origin; browser configs set their own isolated origin.
   No BFF security policy or assertion changed.

## Rendered evidence — isolated synthetic data, after-only

[`docs/images/pass-a/after/`](../images/pass-a/after/README.md) contains:

- `roster-{390,768,1280,1440}.png`.
- `saved-authorization-1440.png`, `historical-metrics-1440.png`.
- `navigation-open-{390,768}.png`, `architecture-keyboard-1440.png`.
- Overview, intake, workbench and structured architecture at each of the four widths.
- `observations-{390,768,1280,1440}.json` (five pages per width).

Every PNG passed signature, checksum, compressed-pixel and dimension validation. Representative mobile,
desktop, authorization, metric and keyboard captures were visually inspected. Table scrolling stays inside
its labeled region. Keyboard capture occurs after Space selection and before the pointer check.

## Commit and safe local-main activation

Every verification gate above is complete. The containing local feature commit is identified by
`git log -1 feature/ui-pass-a-mac`; this report travels in that commit. No push/tag/release is authorized.

**Main integration is deferred for a controlled activation window.** API PID 47769 on 8000 and web PID 47793
on 3000 run from designated main (confirmed via process cwd). A merge changes files those processes read;
the web development server can reload automatically. Neither service was stopped/restarted.

After the owner arranges an activation window and stops those services, the following performs only the
remaining history-preserving local merge. It refuses active listeners, dirty trees, a changed baseline/branch
or divergence. It does not stop processes:

```bash
rtk proxy bash <<'MERGE'
set -euo pipefail
feature=/Users/prawalsharma/Documents/Projects/opspilot-ui-pass-a
main=/Users/prawalsharma/.gemini/antigravity/worktrees/opspilot-ai/product_ui_redesign
baseline=313ef6c1d674e9e8d36d08ba5054807ffac2177f
test "$(git -C "$feature" branch --show-current)" = feature/ui-pass-a-mac
test -z "$(git -C "$feature" status --porcelain)"
test "$(git -C "$main" branch --show-current)" = main
test -z "$(git -C "$main" status --porcelain)"
test "$(git -C "$main" rev-parse HEAD)" = "$baseline"
feature_sha=$(git -C "$feature" rev-parse HEAD)
test "$feature_sha" != "$baseline"
test "$(git -C "$main" merge-base HEAD "$feature_sha")" = "$baseline"
if lsof -nP -iTCP:8000 -iTCP:3000 -sTCP:LISTEN; then
  echo 'Stop: arrange the controlled activation window first.' >&2
  exit 1
fi
git -C "$main" merge --no-ff "$feature_sha" -m 'Merge verified UI Pass A'
git -C "$main" merge-base --is-ancestor "$feature_sha" HEAD
git -C "$main" status --short --branch
git -C "$main" log -1 --format='%H %s'
MERGE
```

If main legitimately advances, review/revalidate integration rather than removing the guard.

## Preservation and limitations

Existing services, production DB data, shared/legacy uploads, `.env`, models, volumes, backups, other worktrees
and private data were preserved. Only the test DB, disposable storage, feature build output and synthetic evidence
were used. No production verification is claimed.

Legacy history without a valid persisted decision stays unknown. Latest sample timestamps stay unavailable.
Offset pages can shift during concurrent writes; searches beyond the offset ceiling must be narrowed.
Large-history performance, all-browser behavior and comprehensive assistive technology were not benchmarked.
Optional telemetry containers were not started. Pass B waits for controlled main activation; none is included.
