---
title: Settlement Worker
doc_type: architecture
services: [settlement-worker]
tags: [queue, settlement, batch, consumer]
version: 2
owner: settlement-team
---
# Settlement Worker

settlement-worker consumes `payment.authorized` events from `settlement-events`, validates them
against the `settlement-event.v3` JSON schema, groups them per merchant and submits settlement
batches every 5 minutes.

## Failure modes

- **Invalid payloads**: events failing schema validation are retried 3 times then moved to the
  dead-letter queue `settlement-events.dlq`. A burst of DLQ messages usually follows a producer
  change to the event schema.
- **Backlog**: consumer lag grows when batch submission slows (bank SFTP latency) or when the
  worker is scaled down. Queue depth above 50k messages breaches the 15-minute settlement SLO.
- settlement-worker reads ledger balances via ledger-service `GET /v1/accounts/{id}/balance`.
