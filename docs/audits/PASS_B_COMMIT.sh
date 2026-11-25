#!/usr/bin/env bash
# Run by the owner in authorized Mac Terminal. Local feature commit only; no activation or remote writes.
set -euo pipefail
cd /Users/prawalsharma/Documents/Projects/opspilot-ui-pass-b
baseline=0a547d415cac31e4873f1ba893ba87470503ccbc
test "$(git branch --show-current)" = feature/ui-pass-b-mac
test "$(git rev-parse HEAD)" = "$baseline"
git diff --cached --quiet # Refuse an unrelated pre-existing staged change.
git diff --check
git add -- apps/web/app/globals.css 'apps/web/app/investigations/[id]/view.tsx' \
  apps/web/components/evidence-inspector.tsx apps/web/components/evidence-coverage.tsx \
  apps/web/e2e-pass-a/fixtures.ts apps/web/e2e-pass-a/pass-a.spec.ts \
  apps/web/playwright.pass-a.config.ts apps/web/playwright.pass-b.config.ts \
  apps/web/e2e-pass-b apps/web/tests/pass-b.test.tsx \
  docs/PROGRESS.md docs/DECISIONS.md docs/design/VISUAL_EXPERIENCE_2.md \
  docs/audits/PASS_B_COMPLETION.md docs/audits/PASS_B_COMMIT.sh \
  docs/audits/PASS_B_INTEGRATION_PREFLIGHT.md docs/audits/pass-b-validation.txt \
  docs/audits/pass-b-playwright.json docs/audits/pass-b-regression-playwright.json \
  docs/images/pass-b
git diff --cached --check
git diff --cached --stat
git commit -m 'feat(ui): refine investigation workbench and contextual evidence review'
git merge-base --is-ancestor "$baseline" HEAD
test "$(git rev-parse HEAD)" != "$baseline"
git log -1 --format='%H %s'
git status --short --branch
test -z "$(git status --porcelain)"
printf '%s\n' 'PASS: feature worktree clean; local feature commit descends from approved Pass A baseline.'
