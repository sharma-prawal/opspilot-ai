# Environment Audit

Audit performed 2026-11-04 at project start, before any project code was generated.
All values were observed with system inspection commands (`sw_vers`, `sysctl`, `df`,
`lsof`, `brew`, `docker`, `ollama`), not assumed.

## Host

| Item | Observed |
|---|---|
| Working directory | `~/Documents/Projects/opspilot-ai` |
| Prior contents | Only `.claude/settings.local.json` (preserved, untouched) |
| Git | Not a repository at start → initialised with `git init -b main` |
| OS | macOS 27.0.1 (build 26A434), Darwin 27.0.0 |
| CPU | Apple M5 Pro, arm64, 15 logical cores |
| Memory | 24 GiB unified (`hw.memsize` = 25769803776) |
| Disk | 926 GiB volume, **223 GiB free at start**, 213 GiB free after toolchain + models |

## Toolchain (pre-existing)

| Tool | Status | Version / path |
|---|---|---|
| Homebrew | present | 6.0.22 (`/opt/homebrew`) |
| Python | present | 3.11.15 (`/usr/local/bin/python3`), 3.12.13 (Homebrew), 3.13.5 |
| uv | present | 0.11.8 (`~/.local/bin/uv`) |
| Node.js | present | v24.13.1 via nvm |
| npm / pnpm / yarn | present | 11.8.0 / 11.15.0 / 1.22.22 |
| Git | present | 2.54.0 (Apple Git-157) |
| psql client | present | 18.4 (Homebrew `postgresql@18`, service **not** running) |
| GNU Make / jq | present | 3.81 / 1.7.1 |
| Docker Desktop | present but **unusable** | 4.22.0 (Aug 2023); never initialised, daemon not running; CLI 24.0.5 |
| Colima | missing | — |
| Ollama | missing | — |

### Container runtime decision

Docker Desktop 4.22 was installed but had never been launched (no settings group container),
its daemon was down, and its bundled CLI (API 1.43) is older than current engines accept.
Bringing it up would require GUI licence acceptance and a privileged helper install.
Per the brief ("Colima if no suitable Docker engine exists"), Colima was installed instead.
**Docker Desktop and its files were left untouched.** The `desktop-linux` context still exists;
switch back any time with `docker context use desktop-linux`.

## Installed during this session

All via Homebrew (`brew install ollama colima docker docker-compose`):

| Software | Version | Notes |
|---|---|---|
| Ollama | 0.40.14 | Native macOS, `brew services start ollama` (launch agent `sh.brew.ollama`) |
| Colima | 0.10.3 | VM: vz, aarch64, **4 CPU / 4 GiB / 30 GiB** |
| Docker CLI | 29.9.3 | `/opt/homebrew/bin/docker` (shadows the Docker Desktop CLI on PATH) |
| docker-compose | 5.7.0 | Standalone binary `/opt/homebrew/bin/docker-compose` |
| Docker Engine (in Colima) | 29.5.2 | API 1.54 |

Side effects to be aware of:

- `colima start` created a `colima` Docker context and made it current (previously `desktop-linux`, which was not functional).
- Homebrew's automatic post-install cleanup removed stale download caches (old cached installers for
  unrelated applications) and an outdated `xz` keg.
  These are Homebrew-managed caches, not user data, but the cleanup was not explicitly requested.
  Project scripts set `HOMEBREW_NO_INSTALL_CLEANUP=1` to prevent this in future installs.
- `docker compose` (plugin form) still resolves to Docker Desktop's stale v2.20.2 plugin in
  `~/.docker/cli-plugins`. Rather than editing `~/.docker/config.json`, project scripts prefer the
  standalone `docker-compose` v5.7.0 and fall back to `docker compose`.

## Ollama verification

| Check | Result |
|---|---|
| API | `http://127.0.0.1:11434` → `{"version":"0.40.14"}`, bound to **127.0.0.1 only** |
| Service env | `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` (Homebrew defaults) |
| `qwen3:8b` | pulled, 5.2 GB on disk, id `500a1f067a9f` |
| `qwen3-embedding:0.6b` | pulled, 639 MB on disk, id `ac6da0dfba84` |
| Embedding dimension | **1024** observed from `/api/embed` (verified, not assumed); `dimensions` truncation also supported |
| Structured generation | `/api/chat` with JSON-schema `format` and `think:false` returned schema-valid JSON |
| GPU | `ollama ps` → `100% GPU` (Metal), 5.3 GB resident at `num_ctx=4096` |
| Latency (cold) | load 3.6 s; prompt eval 39 tok in 0.46 s; generation **~44 tok/s** |
| Embedding latency | 2 inputs, 1.08 s total of which 1.05 s model load (cold) |

No cloud models were pulled and no cloud inference was configured.

## Ports

| Port | Status at audit | Planned use |
|---|---|---|
| 3000 | free | Next.js web |
| 5433 | free | PostgreSQL (host-mapped, 127.0.0.1 only) |
| 8000 | free | FastAPI |
| 8765 | free | Optional MCP Streamable HTTP transport |
| 11434 | Ollama | Ollama |
| other | a few ports in use by unrelated local applications | not touched |

## Existing services / databases

- Several unrelated Homebrew services were registered (including a host `postgresql@18`, not running).
  None were modified. The project's PostgreSQL runs in a container on port 5433 to
  avoid colliding with a future host PostgreSQL on 5432.

## Re-running the audit

`make doctor` (see `scripts/doctor.sh`) re-checks all of the above and reports remediation hints.

## Addendum — end of session 1 (2026-11-04)

- Additional installs: none system-wide. Project-local: `.venv` (uv, Python 3.13.13 managed by uv, 230 MB),
  `apps/web/node_modules` (755 MB). Playwright reused an already-cached Chromium build (1248) — nothing new downloaded.
- Disk: 204 GiB free (from 223 GiB at start). Project footprint ≈ 8.7 GB.
- Running: Ollama (brew service), Colima VM, `opspilot-postgres` (healthy), API :8000 and web :3000 (started by `make dev`).
