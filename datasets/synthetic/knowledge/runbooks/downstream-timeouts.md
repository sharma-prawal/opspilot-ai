---
title: "Runbook: Timeouts from Degraded Downstream Dependencies"
doc_type: runbook
services: [transaction-api]
tags: [timeout, latency, dependency, circuit-breaker, fx]
version: 4
status: current
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

## External providers

fx-rates-provider is a third-party service. When it is degraded there is no internal action that fixes
it: **escalate to the vendor** via the provider status page / support contract and keep the
circuit breaker and cached-rate fallback in place. Do not roll back unrelated internal deployments just
because they are recent — first check whether failing requests point at the provider (`upstream=` field).
