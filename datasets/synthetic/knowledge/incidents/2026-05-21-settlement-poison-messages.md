---
title: "Postmortem PM-2026-011: Settlement stalled by invalid event payloads"
doc_type: incident_report
services: [settlement-worker, transaction-api]
tags: [postmortem, queue, dlq, payload, schema]
version: 1
owner: settlement-team
incident_date: 2026-05-21
---
# Postmortem PM-2026-011: Settlement stalled by invalid event payloads

## Summary

transaction-api v3.9.0 began emitting `amount` as a string. settlement-worker rejected 100% of
events with `SETTLEMENT_SCHEMA_INVALID`; 180k messages were dead-lettered over 2 hours.

## Resolution

transaction-api rolled back; DLQ replayed after validation.

## Lessons

Contract tests between producer and consumer schemas were missing.
