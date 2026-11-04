---
title: "Postmortem PM-2025-031: Payment failures after ledger column drop"
doc_type: incident_report
services: [ledger-service, transaction-api]
tags: [postmortem, schema, migration, 5xx, rollback]
version: 1
owner: ledger-team
incident_date: 2025-08-14
---
# Postmortem PM-2025-031: Payment failures after ledger column drop

## Summary

For 23 minutes, 41% of `POST /v1/payments` requests failed with HTTP 500 (`LEDGER_WRITE_FAILED`).
A ledger-db migration dropped the `posting_ref` column while ledger-service v2.3.1, which still
wrote `posting_ref`, was serving traffic.

## Timeline (UTC)

- 09:58 schema_migration deployment `0031_drop_posting_ref` finished.
- 10:00 transaction-api 5xx alert fired. Read endpoints unaffected.
- 10:09 ledger-service logs found: `column "posting_ref" of relation "ledger_entries" does not exist`.
- 10:17 migration deployment rolled back (down-migration re-added column).
- 10:21 5xx ratio back under 0.5%.

## Root cause

A destructive, non-backward-compatible migration violated the expand/contract policy.

## What went well / poorly

- Rolling back the migration deployment restored service quickly.
- Responders first restarted transaction-api, which had no effect and cost 6 minutes.

## Actions

- Enforce expand/contract review for ledger-db migrations.
- Alert on `UndefinedColumn` in ledger-service logs.
