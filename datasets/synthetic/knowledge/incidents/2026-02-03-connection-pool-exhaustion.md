---
title: "Postmortem PM-2026-004: Ledger latency from connection pool exhaustion"
doc_type: incident_report
services: [ledger-service, transaction-api]
tags: [postmortem, latency, connection-pool, postgres]
version: 1
owner: ledger-team
incident_date: 2026-02-03
---
# Postmortem PM-2026-004: Ledger latency from connection pool exhaustion

## Summary

transaction-api p95 latency rose from 180 ms to 4.2 s for 48 minutes. ledger-service connection
pools were saturated by a reporting query missing an index on `ledger_entries(account_id, created_at)`.

## Root cause

A new merchant-statement endpoint issued a sequential scan per request, holding connections ~3 s.

## Resolution

Index created concurrently; pool temporarily raised from 40 to 60 per replica.

## Lessons

Latency rose 20 minutes before errors did; `PoolTimeout` logs were the earliest clear signal.
