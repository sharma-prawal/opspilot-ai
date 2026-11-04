---
title: "Runbook: Database Connection Pool Exhaustion"
doc_type: runbook
services: [ledger-service]
tags: [latency, connection-pool, postgres, timeout]
version: 4
status: current
supersedes: runbooks/legacy-ledger-pool-tuning.md
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

## Pool exhaustion is usually a symptom

A saturated pool means connections are *held too long*, not that there are too few. Look for what
holds them: long-running or sequential-scan queries, a new endpoint, a missing index, lock waits.
If a recent deployment introduced the slow query, **revert that deployment** — this removes the cause.

## Capacity check before any pool change

Never change a pool size without checking the datastore:

`replicas × pool_max_per_replica + all other clients ≤ 90% of (max_connections − reserved)`

If ledger-db is already near capacity, a larger pool only moves the bottleneck into the database and
can exhaust `max_connections` for every client (including admin access). Treat a pool increase as a
short-lived containment step, never as the fix.

## Mitigation

1. Identify long-running queries (datastore status / `pg_stat_activity`).
2. Revert the change that introduced them, or disable the feature flag.
3. Only if capacity allows, raise the pool within the bound above, and plan to revert it.
4. Restarting ledger-service clears stuck connections but only buys time.
