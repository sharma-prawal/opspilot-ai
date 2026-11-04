---
title: "Ledger Pool Tuning (2024)"
doc_type: runbook
services: [ledger-service]
tags: [connection-pool, postgres, latency, legacy]
version: 1
status: superseded
superseded_by: runbooks/db-connection-pool-exhaustion.md
owner: ledger-team
---
# Ledger Pool Tuning (2024)

> This page predates the ledger-db capacity limits introduced in 2025 and is kept for history.

When `PoolTimeout` errors appear on ledger-service, raise `LEDGER_DB_POOL_MAX` to 80 per replica and
restart ledger-service. In 2024 ledger-db ran with `max_connections = 1000`, so this was always safe.
