---
title: Service Dependency Map
doc_type: dependency_map
services: [transaction-api, ledger-service, settlement-worker, fx-rates-provider]
tags: [dependencies, topology]
version: 6
owner: sre
---
# Service Dependency Map

| Service | Depends on | Kind | Critical |
|---|---|---|---|
| transaction-api | ledger-service | sync_http | yes |
| transaction-api | fx-rates-provider | sync_http | no |
| transaction-api | settlement-events | async_queue | no |
| ledger-service | ledger-db | database | yes |
| settlement-worker | settlement-events | async_queue | yes |
| settlement-worker | ledger-service | sync_http | yes |

## Reading the map during an incident

Start from the service raising the alert and walk *downstream* along critical edges. A critical
downstream dependency that is unhealthy is the most likely origin of errors seen upstream. Check
whether the downstream service had a recent deployment or schema migration.
