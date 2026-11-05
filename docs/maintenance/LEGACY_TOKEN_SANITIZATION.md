# OpsPilot AI — Legacy Approval Token Sanitization Plan

**Document:** `docs/maintenance/LEGACY_TOKEN_SANITIZATION.md`  
**Target Environment:** Local Development Database (`opspilot` on PostgreSQL 17 + pgvector)  
**Status:** **AUDIT & PLANNING ONLY — PENDING OWNER AUTHORIZATION**  
**Author:** DevSecOps / Database Administration  
**Date:** 2026-11-05  

---

## 1. Executive Summary

During Phase C0 hardening (audit finding E), automated key-based secret redaction was introduced across application output boundaries, REST endpoints, structured logs, and new database writes. Prior to that fix, early development and evaluation runs stored raw approval tokens inside tool invocation records.

A read-only audit of the development database (`opspilot`) identified **58 historical records** containing unredacted approval tokens. All 58 records belong to completed investigations whose remediation actions succeeded. All tokens have expired (exceeding their 15-minute validity window by days).

This document outlines the complete, auditable, and non-destructive procedure to sanitize these 58 legacy records using the built-in `opspilot sanitize-secrets --apply` command once explicit owner authorization is granted.

> [!CAUTION]
> **AUTHORIZATION HOLD:** Do not execute `uv run opspilot sanitize-secrets --apply` or perform secret-bearing database backups until explicit written approval is provided by the repository owner. No database records have been modified during this audit.

---

## 2. Database Audit Findings

### 2.1 Affected Tables and Row Counts

The application's `sanitize-secrets` scanner inspects all 12 structured JSONB columns across the `ops` and `sim` schemas, along with the LangGraph checkpoint binary store.

| Schema | Table | Column | Affected Rows | Status |
|---|---|---|:---:|---|
| `ops` | `tool_invocations` | `arguments` | **58** | **Pending sanitization** (`"approval_token": "<raw_token>"`) |
| `ops` | `workflow_events` | `payload` | 0 | Clean (post-fix writes redacted) |
| `ops` | `investigations` | `result` | 0 | Clean |
| `ops` | `evidence` | `data` | 0 | Clean |
| `ops` | `evidence` | `citation` | 0 | Clean |
| `ops` | `action_requests` | `parameters` | 0 | Clean |
| `ops` | `action_requests` | `execution_result` | 0 | Clean |
| `ops` | `action_requests` | `verification` | 0 | Clean |
| `ops` | `workflow_commands` | `payload` | 0 | Clean (outbox never stored tokens) |
| `ops` | `audit_log` | `details` | 0 | Clean |
| `sim` | `action_executions` | `parameters` | 0 | Clean |
| `sim` | `action_executions` | `details` | 0 | Clean |
| `langgraph` | `checkpoint_writes` | `blob` | 329 | Checkpoint history (counted only, see §2.3) |
| `langgraph` | `checkpoint_blobs` | `blob` | 228 | Checkpoint history (counted only, see §2.3) |

### 2.2 Characterization of the 58 Affected Records

A non-printing inspection of the 58 `ops.tool_invocations` rows confirmed:
1. **Tool identity:** All 58 rows represent invocations of `tool = 'execute_remediation'` dispatched to the `actions` MCP server.
2. **Investigation state:** Every associated investigation in `ops.investigations` has reached a terminal status (`completed` or `mitigated`). None are active, queued, running, or awaiting approval.
3. **Action request state:** All corresponding `ops.action_requests` records are in status `succeeded`.
4. **Token validity:** All 58 HMAC approval tokens are expired. Tokens carry a cryptographic timestamp and expiry claim; the newest token expired days prior to this audit.
5. **Post-fix records:** All tool invocations recorded after the C0 hardening release (18+ records) are already stored with redacted tokens (`"approval_token": "[REDACTED]"`).

### 2.3 LangGraph Checkpoint Analysis

The LangGraph checkpointer stores serialized state snapshots in `langgraph.checkpoint_writes` and `langgraph.checkpoint_blobs`. During workflow execution, an approved action temporarily passed `approval_token` into the graph state to resume the workflow from `await_approval` to `execute_remediation`.

- **Decision D38:** Serialized checkpoints are strictly counted but **never rewritten**.
- **Rationale:** Deserializing, modifying, and re-serializing MsgPack/JSON blobs in LangGraph's internal storage risks schema corruption, invalidating hash trees, or breaking workflow resume capability. Because checkpointed tokens are short-lived, action-bound, and long expired, they pose no operational replay risk.

---

## 3. Sanitizer Coverage & Architectural Impact

### 3.1 Sanitizer Implementation (`apps/api/opspilot_api/services/sanitize.py`)

The built-in sanitizer operates as follows:
1. **Target selection:** Iterates through `JSON_COLUMNS` using an SQL `ILIKE` prefilter over `SENSITIVE_KEY_PARTS` (`token`, `password`, `secret`, etc.), followed by exact dictionary evaluation via `contains_secret()`.
2. **Key-based redaction:** Applies `opspilot_shared.redaction.redact()`, which recursively replaces any sensitive dictionary key value with `"[REDACTED]"`. Safe counter keys (such as `prompt_tokens`, `completion_tokens`) are explicitly preserved.
3. **Values only:** Only the token string inside `arguments->>'approval_token'` is mutated. The parent JSON structure, `action_id`, and surrounding keys remain intact.
4. **Transactional:** All mutations execute inside a single database transaction (`async with sf() as s:`). It commits only if all updates succeed; any failure triggers an automatic rollback.
5. **Idempotent:** If run multiple times, records already containing `"[REDACTED]"` are ignored by `contains_secret()`. Subsequent runs report `total: 0`.

### 3.2 Impact Assessment

- **Workflow recovery:** **Zero impact.** The 58 investigations are terminal. Active workflows never read past tool invocation records from prior incidents.
- **RCA & Citations:** **Zero impact.** Root-cause analyses and citations reference `ops.evidence` and `kb.chunks`, none of which are modified by this cleanup.
- **Audit trail:** **Preserved.** The tool call ID, investigation ID, timestamps, server name, latency, status, execution result summary, and `ops.action_requests` decision records are completely untouched.
- **Lost capability:** The only capability lost is re-verifying the HMAC signature of these 58 expired tokens against the historical signing key. Because the actions have already executed and the tokens cannot be reused, this signature verification has no ongoing utility.

---

## 4. Execution Prerequisites & Safety Gates

Before executing the sanitization procedure, verify all prerequisite safety gates:

1. **Authorization Gate:** Written approval from repository owner obtained.
2. **Worktree / Branch Isolation:** Operating on a dedicated maintenance branch without uncommitted changes.
3. **Codex Evaluation Inactive:** Verify no concurrent evaluation runs (`make evaluate`, `opspilot-eval`) are active on the machine.
4. **API Service Stopped:** Ensure the local dev API is stopped (`./scripts/stop.sh`) so no background watchdog or runner process holds locks on `ops.tool_invocations`.
5. **Database Target Verified:** Enforce targeting `opspilot` (the dev database) only during authorized maintenance. Never run against `opspilot_test` or external instances.
6. **No Repository Secrets:** Backups must be saved outside the repository root and never committed to Git.

---

## 5. Step-by-Step Maintenance Procedure

### Phase 1: Pre-Execution Dry Run

Verify the current state and expected affected count without modifying data:

```bash
# 1. Stop local background services
./scripts/stop.sh

# 2. Execute dry-run scan (read-only)
uv run opspilot sanitize-secrets
```

**Expected Dry-Run Output:**
```json
{
  "mode": "dry-run",
  "json_rows_with_secrets": {
    "ops.tool_invocations.arguments": 58,
    "ops.workflow_events.payload": 0,
    "ops.investigations.result": 0,
    "ops.evidence.data": 0,
    "ops.evidence.citation": 0,
    "ops.action_requests.parameters": 0,
    "ops.action_requests.execution_result": 0,
    "ops.action_requests.verification": 0,
    "ops.workflow_commands.payload": 0,
    "ops.audit_log.details": 0,
    "sim.action_executions.parameters": 0,
    "sim.action_executions.details": 0
  },
  "total": 58,
  "redacted": 0,
  "checkpoint_entries_mentioning_approval_token": {
    "langgraph.checkpoint_writes": 329,
    "langgraph.checkpoint_blobs": 228
  },
  "checkpoint_note": "checkpoint history is not rewritten; entries hold short-lived, action-bound tokens"
}
```

*Verification Gate:* If `total` is not 58, halt and investigate before proceeding.

---

### Phase 2: Targeted Pre-Sanitization Backup

Export **only** the 58 affected records (`id` and `arguments`) to a secured file located outside the repository.

```bash
# 1. Export affected records from the PostgreSQL container to container /tmp
docker exec -i opspilot-postgres psql -U postgres -d opspilot -v ON_ERROR_STOP=1 <<'SQL'
\copy (
  SELECT id, arguments 
  FROM ops.tool_invocations 
  WHERE arguments ? 'approval_token' 
    AND arguments->>'approval_token' NOT IN ('[REDACTED]', '<redacted>')
) TO '/tmp/tool_invocations_tokens_backup.csv' WITH (FORMAT csv, HEADER true);
SQL

# 2. Copy the backup file to the user's home directory (strictly outside the repo)
docker cp opspilot-postgres:/tmp/tool_invocations_tokens_backup.csv ~/opspilot_legacy_tokens_backup.csv

# 3. Clean up the temporary file inside the container
docker exec opspilot-postgres rm /tmp/tool_invocations_tokens_backup.csv

# 4. Restrict permissions on the backup file
chmod 600 ~/opspilot_legacy_tokens_backup.csv
```

---

### Phase 3: Backup Integrity & Restore Verification

Verify the exported backup is complete and restorable using an isolated transaction that rolls back:

```bash
# 1. Verify line count on host (header + 58 rows = 59 lines)
test $(wc -l < ~/opspilot_legacy_tokens_backup.csv | tr -d ' ') -eq 59 \
  && echo "✔ Backup row count verified (58 rows + header)" \
  || { echo "✘ Backup row count mismatch"; exit 1; }

# 2. Copy backup into container for a test import
docker cp ~/opspilot_legacy_tokens_backup.csv opspilot-postgres:/tmp/test_verify.csv

# 3. Test restore in an aborted transaction (proves syntax, keys, and schemas match)
docker exec -i opspilot-postgres psql -U postgres -d opspilot -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
CREATE TEMP TABLE backup_verify (
  id varchar(64) PRIMARY KEY,
  arguments jsonb NOT NULL
);

\copy backup_verify FROM '/tmp/test_verify.csv' WITH (FORMAT csv, HEADER true);

DO $$
DECLARE
  imported_count integer;
  matched_count integer;
BEGIN
  SELECT count(*) INTO imported_count FROM backup_verify;
  SELECT count(*) INTO matched_count 
  FROM ops.tool_invocations t 
  JOIN backup_verify b ON t.id = b.id;

  IF imported_count <> 58 THEN
    RAISE EXCEPTION 'Verification failed: expected 58 imported rows, got %', imported_count;
  END IF;

  IF matched_count <> 58 THEN
    RAISE EXCEPTION 'Verification failed: expected 58 matching DB rows, got %', matched_count;
  END IF;

  RAISE NOTICE '✔ Backup restore verification passed: 58/58 records validated.';
END $$;
ROLLBACK;
SQL

# 4. Remove verification file from container
docker exec opspilot-postgres rm /tmp/test_verify.csv
```

---

### Phase 4: Execute Sanitization

> **Requires Owner Authorization Gate:** Execute this step only after Phases 1–3 succeed and approval is granted.

```bash
uv run opspilot sanitize-secrets --apply
```

**Expected Application Output:**
```json
{
  "mode": "apply",
  "json_rows_with_secrets": {
    "ops.tool_invocations.arguments": 58,
    ...
  },
  "total": 58,
  "redacted": 58,
  "checkpoint_entries_mentioning_approval_token": { ... },
  "checkpoint_note": "checkpoint history is not rewritten; entries hold short-lived, action-bound tokens"
}
```

---

### Phase 5: Post-Execution Verification

Confirm that zero unredacted tokens remain in the development database:

```bash
# 1. Run sanitizer dry-run check (should report total 0)
uv run opspilot sanitize-secrets

# 2. Confirm directly via SQL that no unredacted approval_tokens exist
docker exec -i opspilot-postgres psql -U postgres -d opspilot -tAc "
SELECT count(*) 
FROM ops.tool_invocations 
WHERE arguments ? 'approval_token' 
  AND arguments->>'approval_token' NOT IN ('[REDACTED]', '<redacted>');
"
```

**Expected SQL Output:** `0`

---

### Phase 6: Post-Sanitization Cleanup

Once post-execution verification is approved:

```bash
# Securely remove the local secret-bearing backup
rm -P ~/opspilot_legacy_tokens_backup.csv 2>/dev/null || rm -f ~/opspilot_legacy_tokens_backup.csv
echo "✔ Temporary token backup wiped."
```

---

## 6. Rollback & Disaster Recovery Procedure

If the sanitization operation must be reversed:

### 6.1 Interrupted Execution
`sanitize-secrets --apply` wraps all mutations in a single SQLAlchemy transaction (`await s.commit()`). If interrupted prior to completion (power failure, process kill, connection drop):
- The transaction automatically rolls back.
- No partial redactions persist.
- Run `uv run opspilot sanitize-secrets` to confirm all 58 records remain intact.

### 6.2 Full Rollback from Backup

If an authorized execution must be rolled back after commit:

```bash
# 1. Copy the verified backup into the container
docker cp ~/opspilot_legacy_tokens_backup.csv opspilot-postgres:/tmp/restore_tokens.csv

# 2. Restore original arguments by primary key in a single transaction
docker exec -i opspilot-postgres psql -U postgres -d opspilot -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
CREATE TEMP TABLE token_rollback (
  id varchar(64) PRIMARY KEY,
  arguments jsonb NOT NULL
);

\copy token_rollback FROM '/tmp/restore_tokens.csv' WITH (FORMAT csv, HEADER true);

UPDATE ops.tool_invocations t
SET arguments = r.arguments
FROM token_rollback r
WHERE t.id = r.id;

DO $$
DECLARE
  restored_count integer;
BEGIN
  SELECT count(*) INTO restored_count 
  FROM ops.tool_invocations 
  WHERE arguments ? 'approval_token' 
    AND arguments->>'approval_token' NOT IN ('[REDACTED]', '<redacted>');

  IF restored_count <> 58 THEN
    RAISE EXCEPTION 'Rollback failed: expected 58 restored rows, got %', restored_count;
  END IF;

  RAISE NOTICE '✔ Rollback complete: 58 tool invocation records restored.';
END $$;

COMMIT;
SQL

# 3. Clean up container temporary file
docker exec opspilot-postgres rm /tmp/restore_tokens.csv

# 4. Verify dry-run count returns to 58
uv run opspilot sanitize-secrets
```

---

## 7. Known Limitations & Edge Cases

1. **Structured Keys vs. Free-Form Text:** The redaction policy is key-based. If a token was captured in unstructured string fields (such as error tracebacks or free-text log messages), it would not be detected by `is_sensitive()`. (Verified: no such leaks were found during the Phase C0 audit).
2. **LangGraph Checkpoint Blobs:** Historical checkpoint blobs in `langgraph.checkpoint_writes` and `langgraph.checkpoint_blobs` retain mentions of `approval_token`. These entries are deliberately left unedited per Decision D38 to preserve deserialization integrity for the LangGraph framework.
3. **Concurrent Operations:** Never execute `--apply` while `opspilot-eval` or `make evaluate` is actively executing.
