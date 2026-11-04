# ADR-007: Resource-aware local deployment

- Status: Accepted (2026-11-04)

## Context
24 GB unified memory shared between the OS, IDE, browser, an 8B model and the stack. ~257 GB free disk;
project target < 50 GB.

## Alternatives considered
Running Kafka/Redis/Elastic/Jaeger by default; larger models; parallel LLM calls.

## Decision
- Only PostgreSQL is containerised by default (Colima 4 CPU / 4 GiB / 30 GiB; Postgres `mem_limit: 1g`).
- Optional services live behind Compose profiles (`observability`, `tools`).
- LLM concurrency semaphore = 1; one investigation at a time by default; bounded `num_ctx` (8192)
  and `num_predict`; per-investigation tool/LLM budgets.
- No 14B+/cloud models are pulled.

## Rationale
Keeps total footprint ≈ 11–12 GB with headroom; avoids model thrash from concurrent loads.

## Tradeoffs
Throughput is one investigation at a time; acceptable for a single operator. Settings allow scaling up.

## Consequences
`make doctor` checks free memory/disk and warns before starting heavy work.
