---
title: "Runbook: Settlement Failures from Invalid Message Payloads"
doc_type: runbook
services: [settlement-worker, transaction-api]
tags: [queue, dlq, schema, settlement, payload]
version: 3
status: current
owner: settlement-team
---
# Runbook: Settlement Failures from Invalid Message Payloads

Symptoms: settlement-worker logs `SETTLEMENT_SCHEMA_INVALID` and DLQ depth on
`settlement-events.dlq` rises; settlement batches shrink or stop.

1. Inspect the queue and a DLQ sample — which field fails validation, which producer version sent it?
2. Correlate with recent producer (transaction-api) deployments that changed the event shape.

## Containment, resolution, recovery

- **Containment:** `pause_consumer` on settlement-worker stops retry churn and partition stalls. It does
  **not** fix anything; nothing settles while paused.
- **Resolution:** roll back the producer deployment that emits the invalid shape, so no new poison arrives.
- **Recovery:** `quarantine_messages` for the observed validation error code moves invalid messages
  (pending and dead-lettered) aside — they are preserved for later replay, never deleted. Then
  `resume_consumer`. Resuming while poison messages remain, or before the producer is fixed, restarts
  the failure loop.
- **Afterwards:** transform and replay quarantined messages once a compatible schema is deployed.
