# Deployment (local-first)

```mermaid
flowchart TB
  subgraph mac["macOS host (Apple Silicon, 24 GB)"]
    ollama["Ollama (native, Metal)<br/>127.0.0.1:11434<br/>qwen3:8b ≈5.3 GB, qwen3-embedding:0.6b ≈0.6 GB"]
    apiproc["uvicorn opspilot_api<br/>127.0.0.1:8000"]
    mcpchild["MCP read/action servers<br/>(stdio children of API)"]
    webproc["next dev<br/>127.0.0.1:3000"]
    subgraph colima["Colima VM (vz, 4 CPU / 4 GiB / 30 GiB)"]
      pg["postgres: pgvector/pgvector:0.8.7-pg17<br/>published 127.0.0.1:5433 → 5432<br/>volume: opspilot_pgdata<br/>mem_limit 1g"]
    end
    apiproc --> mcpchild
    apiproc --> ollama
    mcpchild --> ollama
    apiproc --> pg
    mcpchild --> pg
    webproc --> apiproc
  end
```

## Why this shape

- Ollama runs **natively** — containers on macOS cannot use the Metal GPU.
- Only PostgreSQL is containerised. It is the single stateful dependency, and a pinned image
  (`pgvector/pgvector:0.8.7-pg17`) makes the extension version reproducible.
- Every listener binds to `127.0.0.1`.

## Memory budget (measured 2026-11-04, during an investigation)

| Component | Measured |
|---|---|
| qwen3:8b loaded (`ollama ps`, num_ctx 8192) | 5.2 GB |
| qwen3-embedding:0.6b loaded | 1.0 GB |
| Postgres container (`docker stats`; limit 1 GiB) | 277 MB |
| Colima VM ceiling | 4 GiB (allocation, not usage) |
| API + 2 MCP children + Next.js dev (RSS) | ~230 MB |
| **Working set** | **≈ 6.7 GB** + VM overhead; system reported 29% memory free with IDE/browser open |

Both models stay resident under `LLM_KEEP_ALIVE=10m`; `OLLAMA_MAX_LOADED_MODELS` was left at its default.

## Disk budget

| Item | Size |
|---|---|
| Models (`~/.ollama/models`) | 5.5 GB (measured) |
| Colima VM disk (sparse, 30 GiB cap) | 2.2 GB (measured; image 646 MB, data volume 440 MB) |
| Python venv / node_modules | 0.23 GB / 0.76 GB (measured) |
| **Project total** | **≈ 8.7 GB**, well under the 50 GB target |

## Compose profiles

| Profile | Services | Default |
|---|---|---|
| *(none)* | `postgres` | yes |
| `observability` | `jaegertracing/jaeger:2.21.0` (OTLP on 127.0.0.1:4317/4318, UI 16686, mem_limit 512m) | no |
| `tools` | `adminer:6.3.0` (127.0.0.1:8081, mem_limit 128m) | no |

Start optional profiles explicitly, e.g. `make infra-up PROFILES=observability`.

## Lifecycle commands

| Command | Effect |
|---|---|
| `make infra-up` | start Colima if stopped, `docker-compose up -d postgres`, wait for health |
| `make migrate` | Alembic upgrade + LangGraph checkpointer `setup()` |
| `make dev` | start API and web (skips any already listening) |
| `make stop` / `make infra-down` | stop app processes / stop containers (**volumes preserved**) |

Nothing in the tooling runs `docker system prune`, `docker volume prune` or deletes volumes.
