---
title: PostgreSQL Troubleshooting Guide
doc_type: troubleshooting
services: [ledger-service]
tags: [postgres, database, errors, locks, troubleshooting]
version: 4
owner: dba
---
# PostgreSQL Troubleshooting Guide

## `UndefinedColumn: column "x" of relation "y" does not exist`

SQLSTATE 42703. The statement references a column that is not in the table. In production this
almost always means application code and schema are out of sync — e.g. a migration renamed or
dropped a column that a running version still uses. Check recent `schema_migration` deployments.

## `PoolTimeout` / `too many connections`

Client-side pool exhausted or server `max_connections` reached. See the connection pool runbook.

## Lock timeouts during migrations

`LockNotAvailable` while a migration runs indicates `ALTER TABLE` waiting on long transactions.
Use `lock_timeout` in migrations and retry outside peak hours.

## Replication lag

Read-replica lag causes stale reads but not write failures.
