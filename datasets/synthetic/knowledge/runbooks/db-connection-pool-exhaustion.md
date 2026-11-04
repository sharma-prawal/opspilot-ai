---
title: "Runbook: Database Connection Pool Exhaustion"
doc_type: runbook
services: [ledger-service]
tags: [latency, connection-pool, postgres, timeout]
version: 3
owner: ledger-team
---
# Runbook: Database Connection Pool Exhaustion

Symptoms: p95 latency on ledger-service rises sharply, transaction-api latency follows, logs show
`PoolTimeout: couldn't get a connection after 5.00 sec`, and `db_pool_in_use` sits at
`db_pool_max`. Error rate rises later, as timeouts start.

## Common causes

- A slow query holding connections (missing index after a data growth step).
- Long transactions or idle-in-transaction sessions.
- Traffic increase without pool or replica scaling.

## Mitigation

1. Identify long-running queries in `pg_stat_activity` (DBA on call).
2. As a temporary measure, `scale_connection_pool` for ledger-service within the safe bound
   (max 200 total across replicas; ledger-db max_connections is 400).
3. Restarting ledger-service clears stuck connections but only buys time.
