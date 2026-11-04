---
title: "Runbook: Settlement Failures from Invalid Message Payloads"
doc_type: runbook
services: [settlement-worker, transaction-api]
tags: [queue, dlq, schema, settlement, payload]
version: 2
owner: settlement-team
---
# Runbook: Settlement Failures from Invalid Message Payloads

Symptoms: settlement-worker logs `SETTLEMENT_SCHEMA_INVALID` and DLQ depth on
`settlement-events.dlq` rises; settlement batches shrink or stop.

1. Inspect a DLQ sample — which field fails validation?
2. Correlate with recent producer (transaction-api) deployments that changed event shape.
3. Mitigate by rolling back the producer deployment, or `pause_consumer` on settlement-worker to
   stop DLQ churn while a fix is prepared.
4. Replay DLQ messages after the fix.
