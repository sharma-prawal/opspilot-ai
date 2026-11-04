---
title: "Runbook: Elevated HTTP 5xx Error Rate"
doc_type: runbook
services: [transaction-api, ledger-service]
tags: [5xx, errors, triage, alert]
version: 7
owner: sre
---
# Runbook: Elevated HTTP 5xx Error Rate

Alert: `TransactionApi5xxRatioHigh` fires when the 5xx ratio exceeds 2% for 5 minutes.

## Triage

1. Confirm the blast radius: which endpoints? If only write endpoints (`POST /v1/payments`,
   `POST /v1/refunds`) fail, focus on the ledger write path.
2. Group error logs by message signature. Look for the `code` field (`LEDGER_WRITE_FAILED`,
   `PAYMENT_TIMEOUT`, `FX_UNAVAILABLE`).
3. Determine the **onset time** from the 5xx ratio metric and list all deployments and config
   changes in the 2 hours before onset, across transaction-api **and its downstream
   dependencies**. A change minutes before onset is the prime suspect.
4. Check downstream health (ledger-service error ratio and logs).

## Mitigation

- If a recent deployment correlates with onset, **roll back that deployment** (see the
  deployment procedure). Prefer rollback over forward-fix during an active incident.
- If the error originates in a schema migration, follow "Runbook: Rolling Back a Schema Migration".
- Do not restart transaction-api for downstream failures; it does not help and drops requests.

## Verification

The 5xx ratio should return below 1% within 5 minutes of mitigation. Confirm with the
`http_5xx_ratio` metric, not by spot-checking requests.
