---
title: "Runbook: Triage of Short-Lived Alerts"
doc_type: runbook
services: [transaction-api, ledger-service]
tags: [alert, triage, transient, false-positive, kubernetes]
version: 2
status: current
owner: sre
---
# Runbook: Triage of Short-Lived Alerts

Not every alert needs a remediation.

## Is the impact ongoing?

1. Look at the alerting metric over the last 30 minutes. If it returned to baseline and stayed there,
   the incident is over.
2. Check for routine platform events at the same minute: pod reschedules for node maintenance, a
   rolling restart, a brief dependency failover. These produce a few minutes of 5xx while connections
   re-establish.
3. If nothing changed and impact ended, close the alert with a note — **no action is required**. Consider
   tuning the alert window if it fires on blips shorter than 5 minutes.

## When to escalate instead

If impact is still ongoing, or the cause cannot be identified from the evidence, escalate to the owning
team rather than guessing at a remediation.
