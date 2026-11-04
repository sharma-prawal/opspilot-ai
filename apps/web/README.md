# OpsPilot AI — web UI

Next.js 16 (App Router, Cache Components) operator console. It talks only to the same-origin BFF route
`app/api/ops/[...path]/route.ts`, which forwards an allowlist of paths to the FastAPI backend and injects the
operator token server-side.

```bash
pnpm install
OPSPILOT_API_URL=http://127.0.0.1:8000 OPERATOR_TOKEN=... pnpm dev   # or `make dev` from the repo root
pnpm lint && pnpm typecheck && pnpm test   # unit checks
pnpm e2e                                   # Playwright against a running stack (real local model)
```

See the repository README for the full system.
