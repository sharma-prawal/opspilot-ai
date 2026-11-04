---
title: Transaction API Service
doc_type: architecture
services: [transaction-api]
tags: [api, payments, http]
version: 4
owner: payments-api-team
---
# Transaction API Service

transaction-api is the public entry point for payment creation.

## Endpoints

- `POST /v1/payments` — create and authorise a payment (writes to ledger-service).
- `GET /v1/payments/{id}` — read a payment (served from read replica).
- `POST /v1/refunds` — create a refund (writes to ledger-service).

## Dependencies

- ledger-service (synchronous HTTP, critical, timeout `http.client.timeout_ms`, default 2000 ms)
- fx-rates-provider (synchronous HTTP, non-critical, cached for 60 s)
- settlement-events queue (asynchronous publish)

## Error handling

Upstream failures are mapped to stable error codes (see the error catalogue). The API never
returns raw database errors; a `LEDGER_WRITE_FAILED` code always means the ledger write failed
downstream. Errors from ledger-service are logged with `upstream=ledger-service` and the upstream
status code.

## Operational notes

- A spike in 5xx on `POST` endpoints only, with `GET` healthy, points at the write path
  (ledger-service) rather than transaction-api itself.
- transaction-api restarts do not help with downstream failures and drop in-flight requests.
