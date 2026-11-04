---
title: Deployment and Rollback Procedure
doc_type: deployment_procedure
services: [transaction-api, ledger-service, settlement-worker]
tags: [deploy, rollback, release]
version: 5
owner: release-engineering
---
# Deployment and Rollback Procedure

## Deployment kinds

- `application` — rolling update of a service to a new version.
- `schema_migration` — applies database migrations for a service; independent of application rollout.
- `rollback` — recorded automatically when a deployment is reverted.

Every deployment has a stable ID (`dep-...`). Rollbacks are always performed **by deployment ID**
so the exact change is reverted.

## Rollback

`rollback_deployment(service, deployment_id)` reverts the deployment: for `application` it restores
`previous_version`; for `schema_migration` it runs the down-migration. Rollback requires approval
from the incident commander during an incident.

## Change freeze

No deployments during active SEV1/SEV2 incidents except mitigations.
