---
title: "Runbook: Settlement Queue Backlog"
doc_type: runbook
services: [settlement-worker]
tags: [queue, backlog, lag, consumer, scaling]
version: 2
owner: settlement-team
---
# Runbook: Settlement Queue Backlog

Symptoms: `queue_depth` on `settlement-events` grows steadily, consumer lag exceeds 10 minutes.

1. Check consumer replica count (was settlement-worker scaled down by a deployment?).
2. Check batch submission latency to the bank SFTP endpoint.
3. Scale out consumers or roll back the deployment that reduced throughput.
