---
title: Payment Platform Architecture Overview
doc_type: architecture
services: [transaction-api, ledger-service, settlement-worker]
tags: [architecture, overview, payments]
version: 3
owner: platform-architecture
---
# Payment Platform Architecture Overview

The synthetic payment platform ("Northwind Pay") processes card-not-present payments. It is
composed of three core services plus managed infrastructure.

## Request path

1. Clients call **transaction-api** `POST /v1/payments`. The API validates the request, performs
   idempotency checks on the `Idempotency-Key` header, and authorises the payment.
2. transaction-api synchronously calls **ledger-service** `POST /v1/entries` to record a double-entry
   ledger posting. A payment is only acknowledged (`201`) once the ledger write succeeds.
3. transaction-api publishes a `payment.authorized` event to the `settlement-events` queue.
4. **settlement-worker** consumes `settlement-events`, batches payments per merchant and submits
   settlement files to the acquiring bank.

## Data ownership

- `ledger-db` (PostgreSQL) is owned exclusively by ledger-service. No other service connects to it.
  Schema changes to `ledger-db` are shipped as `schema_migration` deployments of ledger-service.
- transaction-api keeps only idempotency records in its own Redis-compatible cache.

## Failure propagation

Because the ledger write is synchronous, any ledger-service failure surfaces as HTTP 5xx on
transaction-api with error code `LEDGER_WRITE_FAILED`. Read endpoints (`GET /v1/payments/{id}`)
are served from a replica and usually keep working when writes fail — a useful discriminator.

## SLOs

| Service | Availability SLO | Latency SLO (p95) |
|---|---|---|
| transaction-api | 99.9% non-5xx | 400 ms |
| ledger-service | 99.95% | 150 ms |
| settlement-worker | 99% of batches within 15 min | n/a |
