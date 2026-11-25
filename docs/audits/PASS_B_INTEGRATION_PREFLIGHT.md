# Pass B controlled-integration preflight

Read-only snapshot: **25 November 2026, 11:11 IST (05:41 UTC)**. Refresh work/lease/health checks
immediately before activation because the currently running application remains available to operators.

| Gate | Observed result |
| --- | --- |
| Main | Clean `main`, `0a547d415cac31e4873f1ba893ba87470503ccbc`; four local commits ahead of origin/main; no remote write |
| Feature | `feature/ui-pass-b-mac`, HEAD at the same approved baseline; reviewed Pass B diff uncommitted because Git metadata is outside writable roots |
| History | Approved baseline is an ancestor; local commit helper requires this exact starting HEAD and verifies ancestry/cleanliness after committing |
| API / web | Existing PIDs 17826 / 17852, ports 8000 / 3000, cwd in designated main worktree; web parent matches recorded secure launcher and credential-key allowlist |
| Health | API `/health/ready` 200; web `/login` 200 |
| Work | 0 queued/running/awaiting-approval/interrupted investigations; 0 pending/approved/executing actions; 0 pending/delivering workflow commands |
| Execution | 0 unexpired investigation leases; 0 owned investigations; 0 queued/running ingestion, tool or simulator-execution jobs; 0 other active client queries at observation time |
| Idle ownership | One normal server fencing session exists while the API is running; this is not an investigation execution lease |
| Schema / migrations | Current schema `0011`; no API/package/service/infra/dependency changes in Pass B; no migration required |
| Backup | Existing restore-verified schema `0011` dump exists and its SHA-256 matches the prior verification record; no restore repeated |
| Storage | PostgreSQL filesystem 50% used, 30,624,817,152 bytes free (28.52 GiB); no storage recovery or cleanup performed |
| Production integrity | All 30 table counts match the restore verification record; all eight shared/legacy upload sizes and SHA-256 values match the prior activation baseline |

Verified backup:
`/Users/prawalsharma/Documents/Projects/opspilot-backups/opspilot-20261124T145113Z-schema0011-pass-a.dump`

SHA-256: `c30db510084aa1d2495b44b17849b6a066c1aa327cf670c267f46b1eaa11b0cf`.
Prior restore evidence:
`/Users/prawalsharma/OpsPilotBackups/pass-a-restore-verification-20261125T043030Z/RESTORE_VERIFIED.json`.
Detailed current read-only snapshot remains outside Git at
`/tmp/opspilot-pass-b-integration-preflight.json` (aggregate checks only are summarized here).

## Remaining steps

1. In authorized Mac Terminal, create the local feature commit:

   ```bash
   rtk proxy bash /Users/prawalsharma/Documents/Projects/opspilot-ui-pass-b/docs/audits/PASS_B_COMMIT.sh
   ```

   The helper stages only the reviewed Pass B files, refuses pre-existing staged changes, prints the
   resulting SHA, and verifies a clean feature tree and descent from the approved baseline. It does not merge,
   push, stop/start services or access a database. It has not been executed inside this sandbox.

2. Supply explicit approval for **Pass B activation**. Visual acceptance/finalization does not authorize
   interrupting the running main application. No service stop, merge or activation is currently performed.

After that approval, refresh the preflight, capture production counts/upload integrity, and verify the actual
feature SHA and clean trees. Stop only the recorded OpsPilot API/web process trees using main's
`scripts/stop.sh`; preserve PostgreSQL, Ollama and MCP safety configuration. Merge that verified feature
commit into local main with `git merge --no-ff <verified-feature-sha>`, preserving history. Start through
main's `scripts/start.sh`, which launches the web through the existing secure environment allowlist.

Then run focused authenticated, existing-record-only workbench/inspector/coverage/authorization/navigation
smoke checks. Block production mutations (apart from session login/logout), cloud queries and remediation;
compare before/after database counts, upload hashes and application health. No migration is needed.
Any changed baseline, active work, failed health or integrity mismatch stops activation for review.
No push, tag, publication, storage recovery or new feature work is part of this sequence.
