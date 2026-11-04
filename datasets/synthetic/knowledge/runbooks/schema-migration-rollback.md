---
title: "Runbook: Rolling Back a Schema Migration"
doc_type: runbook
services: [ledger-service]
tags: [schema, migration, rollback, postgres, database]
version: 4
owner: ledger-team
---
# Runbook: Rolling Back a Schema Migration

Use when a `schema_migration` deployment breaks running application code — typical signatures are
`UndefinedColumn`, `UndefinedTable`, or `column "..." of relation "..." does not exist` in service
logs immediately after the migration completed.

## Confirm

1. Find the migration deployment (`kind=schema_migration`) and its finish time.
2. Confirm the first error log for the missing column appears *after* that finish time.
3. Confirm the running application version predates the migration's expected application version
   (i.e. the application was not updated to the new schema).

## Roll back

1. Roll back the **migration deployment** by its deployment ID through the deploy tool
   (`rollback_deployment`). This executes the down-migration (e.g. renames `amount_minor` back
   to `amount`).
2. Do not roll back unrelated application deployments.
3. Expect error rates to recover within 1–3 minutes as new inserts succeed.

## Follow-up

- Re-plan the change as expand/contract: add the new column, dual-write, backfill, switch reads,
  then contract in a later release.
- Add a CI check that blocks destructive column changes while older versions are deployed.
