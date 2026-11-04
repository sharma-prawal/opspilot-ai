---
title: Database Migration Policy (Expand/Contract)
doc_type: deployment_procedure
services: [ledger-service]
tags: [schema, migration, expand-contract, policy, database]
version: 3
owner: release-engineering
---
# Database Migration Policy (Expand/Contract)

All schema changes must be backward compatible with every application version that may be running.

## Rules

1. **Never rename or drop a column in one step.** Add the new column (expand), deploy code that
   writes both, backfill, switch reads, then remove the old column (contract) in a later release.
2. Migrations must be deployable independently of application code and must include a down-migration.
3. A migration that is not backward compatible must be blocked by review.

## Why

Application instances and migrations roll out at different times. A rename such as
`amount → amount_minor` applied while the old application version is serving traffic causes every
insert referencing the old column to fail with `UndefinedColumn`.
