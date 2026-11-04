---
title: Ledger Service Design
doc_type: architecture
services: [ledger-service]
tags: [ledger, database, schema, postgres]
version: 5
owner: ledger-team
---
# Ledger Service Design

ledger-service records immutable double-entry postings for every payment.

## Schema

The core table is `ledger_entries`:

| Column | Type | Notes |
|---|---|---|
| `entry_id` | uuid | primary key |
| `payment_id` | uuid | from transaction-api |
| `account_id` | text | merchant or clearing account |
| `amount` | numeric(18,2) | legacy decimal amount (being replaced) |
| `amount_minor` | bigint | amount in minor units (planned replacement for `amount`) |
| `currency` | char(3) | ISO 4217 |
| `direction` | text | `debit` or `credit` |
| `created_at` | timestamptz | |

The migration from `amount` to `amount_minor` is planned as an **expand/contract** change:
add `amount_minor`, dual-write from application code, backfill, switch reads, and only then drop
`amount`. Renaming or dropping `amount` while any running version still writes it will break inserts.

## Write path

`POST /v1/entries` inserts two rows (debit + credit) in one transaction. Insert failures return
`500` with body `{"code": "LEDGER_WRITE_FAILED"}`; callers must not retry non-idempotently.

## Migrations

Migrations are applied by the deploy pipeline as a separate deployment of kind
`schema_migration` before (or independently of) the application rollout. Each migration has a
down-migration; the pipeline's rollback of a `schema_migration` deployment runs it.

## Connection pooling

ledger-service uses a pool of 40 connections per replica (`LEDGER_DB_POOL_MAX`). Pool exhaustion
shows up as `PoolTimeout: couldn't get a connection after 5.00 sec` and rising p95 latency rather
than immediate errors.
