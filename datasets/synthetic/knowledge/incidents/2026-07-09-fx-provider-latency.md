---
title: "Postmortem PM-2026-017: Payment timeouts from FX provider degradation"
doc_type: incident_report
services: [transaction-api, fx-rates-provider]
tags: [postmortem, timeout, dependency, fx, latency]
version: 1
owner: payments-api-team
incident_date: 2026-07-09
---
# Postmortem PM-2026-017: Payment timeouts from FX provider degradation

## Summary

fx-rates-provider latency rose to 6 s. Cross-currency payments failed with `PAYMENT_TIMEOUT`
because the circuit breaker threshold was misconfigured. Single-currency payments were unaffected.

## Resolution

Circuit breaker corrected to open after 20% failures; payments fell back to cached rates.

## Lessons

An earlier change raising `http.client.timeout_ms` from 2000 to 5000 ms made thread exhaustion worse.
