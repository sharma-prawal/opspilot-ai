---
title: "Runbook: Timeouts from Degraded Downstream Dependencies"
doc_type: runbook
services: [transaction-api]
tags: [timeout, latency, dependency, circuit-breaker, fx]
version: 3
owner: sre
---
# Runbook: Timeouts from Degraded Downstream Dependencies

Symptoms: `PAYMENT_TIMEOUT` or `FX_UNAVAILABLE` errors, latency rising toward the configured client
timeout, and healthy CPU/memory on the calling service.

1. Identify which dependency is slow from `upstream=` log fields and dependency latency metrics.
2. Check the provider status page / dependency health.
3. Non-critical dependencies (fx-rates-provider) should fail open to cached rates; confirm the
   circuit breaker opened.
4. Raising `http.client.timeout_ms` hides the problem and increases thread exhaustion risk —
   avoid it as a mitigation.
