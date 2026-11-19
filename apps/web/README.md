# OpsPilot AI — web UI

Next.js 16 (App Router, Cache Components) operator console. It talks only to the same-origin BFF route
`app/api/ops/[...path]/route.ts`, which forwards an allowlist of paths to the FastAPI backend and injects the
operator token server-side.

```bash
pnpm install
make -C ../.. dev                          # start via the repo launcher (see below), not a bare `pnpm dev`
pnpm lint && pnpm typecheck && pnpm test   # unit checks
pnpm e2e                                   # Playwright against a running stack (real local model)
```

Start the web server with `make dev` (or `scripts/start.sh`) from the repository root. Next.js only reads
`.env*` files from `apps/web`, and the BFF's secrets live in the repository-root `.env`. The launcher starts
`next dev` detached with an allowlisted environment built by `opspilot_shared.web_env`: the BFF settings
(`OPSPILOT_API_URL`, `OPERATOR_TOKEN`, `OPSPILOT_WEB_SESSION_SECRET`, `OPSPILOT_WEB_OPERATOR_PASSPHRASE`,
optional `OPSPILOT_WEB_VIEWER_PASSPHRASE` / `OPSPILOT_WEB_ORIGIN`) plus basic process variables (`PATH`, `HOME`,
locale, Node settings). Backend-only settings — database and MCP role passwords, `ACTION_SIGNING_KEY`, model and
connector settings — never reach the web process or its children. A bare
`pnpm dev` here starts without them, so every BFF request fails closed with `web authentication is not
configured` and the UI shows unavailable model names and counts. If that happens, stop that server and run
`make dev`.

See the repository README for the full system.
