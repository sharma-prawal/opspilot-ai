# Azure Monitor & Application Insights connector (v0.10)

> **Verification status.** Implemented and tested against a **synthetic Log Analytics Query API fixture only**
> (`scripts/azure_monitor_fixture.py`), which follows the documented request and response shapes. **No real Azure
> tenant, subscription or Log Analytics workspace has been used for validation.** Native Azure Monitor resource
> metrics and sovereign clouds are deferred (see [Known limitations](#known-limitations)).

Azure Monitor is an optional, backend-configured, **strictly read-only** evidence provider in the same connected
observability workflow as Loki, Prometheus and Datadog (see [CONNECTORS.md](CONNECTORS.md)):

```
Query Azure (approved KQL templates) → normalize → preview → frozen snapshot → read-only LangGraph investigation
```

The investigation never contacts Azure: it reads only the snapshot stored with the incident, so its evidence and
citations are reproducible. There is no Azure-specific agent, and Azure is never a remediation path.

## Capabilities

| Signal | Source tables | Built-in templates | Becomes |
|---|---|---|---|
| Logs | `AppTraces` | `trace_warnings` (SeverityLevel ≥ Warning), `trace_lifecycle` (start-up, version, configuration lines), `all_traces` (off by default) | `LogRecord` |
| Logs | `AppExceptions` | `exceptions` (type, outer/innermost message, problem ID, up to 10 stack frames) | `LogRecord` (ERROR) |
| Requests / dependencies | `AppRequests`, `AppDependencies` | `failed_requests` (+ the requests and dependency calls of up to 10 of those operations), `failed_dependencies`, `slow_requests` (off by default) | `SpanRecord` |
| Metrics (KQL-derived) | `AppRequests`, `AppDependencies` | `http_requests_per_min`, `request_failure_ratio`, `http_5xx_ratio`, `p95_latency_ms`, `dependency_failure_ratio`, `dependency_p95_ms` | `MetricRecord` (one series per service and template) |

Also: a connection test (token, workspace, each table), bounded service discovery and the shared evidence-coverage
and unsupported-claim checks (D125). `AppEvents` is accepted in operator template files but has no built-in template.

Not collected: deployment or configuration-change history (Azure activity log, release annotations, App
Configuration history), live resource health, native platform metrics (CPU, memory, DTU), and anything outside the
one configured workspace.

## Requirements

- **Workspace-based Application Insights.** The telemetry must be stored in a Log Analytics workspace (the
  `AppRequests`, `AppDependencies`, `AppExceptions`, `AppTraces` tables). Classic (non-workspace) Application Insights
  resources are not supported.
- **The workspace ID** (a GUID, on the workspace's *Overview* page). Not the workspace name, resource ID or a URL.
- **Least-privilege access.** Assign **Log Analytics Data Reader** on that workspace only. Microsoft documents it as
  the minimum to run queries (`Microsoft.OperationalInsights/workspaces/query/read`, `workspaces/read`, and the
  `tables/data/read` data action). *Log Analytics Reader* also works but grants broader `*/read`. No Contributor,
  Owner, Monitoring Contributor or subscription-wide role is needed. Role assignments can take several minutes to apply.
- **Cloud role names.** Services are identified by `AppRoleName` (Application Insights *cloud role name*).

## Authentication

OpsPilot uses the official `azure-identity` credentials (`azure-identity` 1.27, synchronous credentials called in a
worker thread). There is **no `DefaultAzureCredential` chain** and no interactive or device-code credential:
`AZURE_MONITOR_AUTH_MODE` selects exactly one credential, and nothing else is tried.

| `AZURE_MONITOR_AUTH_MODE` | Credential | Settings |
|---|---|---|
| `service_principal` (default) | `ClientSecretCredential`, authority `login.microsoftonline.com` | `AZURE_TENANT_ID` (GUID or verified domain), `AZURE_CLIENT_ID` (GUID), `AZURE_CLIENT_SECRET` |
| `managed_identity` | `ManagedIdentityCredential` | optional `AZURE_CLIENT_ID` for a user-assigned identity; `AZURE_CLIENT_SECRET` must be empty |
| `azure_cli` | `AzureCliCredential` (`az account get-access-token`, 10 s process timeout) — **development only** | optional `AZURE_TENANT_ID`; requires an existing `az login` |
| `fixture` | a synthetic token, **only** with a loopback `AZURE_MONITOR_LOCAL_API_URL` | used by tests and `make azure-fixture` |

- Token scope: `https://api.loganalytics.azure.com/.default` (the documented audience of the Logs Query API).
- Tokens are cached in memory, refreshed five minutes before expiry, and refreshed once after an HTTP 401. A token
  still rejected after that refresh is an `auth_error`.
- Constructing a credential makes no network call; nothing is contacted at API start-up. The first token is requested
  by the first connection test or query.
- Credential failures are reported with their `AADSTS…` code only (e.g. `AADSTS7000215: invalid client secret`); the
  library's message text (tenant, application, trace IDs) is never shown, logged or stored.
- Tokens and secrets are backend-only: never `NEXT_PUBLIC_*`, never in API responses, logs, errors, evidence or
  snapshots. `AZURE_*`, `MSAL_*` and `IDENTITY_*` variables are on the web-process denylist (D116).

## Configuration

```bash
AZURE_MONITOR_ENABLED=true
AZURE_MONITOR_WORKSPACE_ID=<workspace GUID>
AZURE_MONITOR_AUTH_MODE=service_principal     # service_principal | managed_identity | azure_cli
AZURE_TENANT_ID=<tenant GUID or contoso.onmicrosoft.com>
AZURE_CLIENT_ID=<app (client) ID>
AZURE_CLIENT_SECRET=<secret>                  # service_principal only
AZURE_MONITOR_MAX_RECORDS=500                 # per request/dependency query (10–2000)
```

Restart the API after a change (`make stop && make dev`). When `AZURE_MONITOR_ENABLED` is false or the configuration
is invalid, the connector reports `not_configured` with the reason and every other connector keeps working.

Shared limits (`TELEMETRY_*`) apply: window ≤ `TELEMETRY_MAX_WINDOW_HOURS` (6 h), ≤ `TELEMETRY_MAX_LOG_LINES` (2000)
rows per log query, `TELEMETRY_TIMEOUT_SECONDS` (10 s) client timeout, `TELEMETRY_MAX_RESPONSE_BYTES` (5 MiB) per answer,
and at most 40 queries per snapshot.

**Cloud.** Azure public cloud only: the destination is fixed to `https://api.loganalytics.azure.com` and the
authority to `login.microsoftonline.com`. Azure Government and Azure China are **not supported** (no configurable host
exists, by design). There is no setting that accepts a URL other than the loopback fixture override.

## Using it

1. **Integrations → Azure Monitor → Test connection.** The test (1) obtains a token, (2) runs `print opspilot_probe = 1`
   against the workspace, then (3) runs `<table> | take 1 | project TimeGenerated` over the last day for each of the four
   tables. Results: overall `ok` / `partial` / `auth_error` / `permission_denied` / `rate_limited` / `unavailable` /
   `error`; per signal; and per table (`present`, `not in workspace`, `access denied`, …). "present; no accessible
   records in the last 24 h" means the table exists and returned no rows to this identity: it may be quiet, or its data
   may be restricted (see below).
2. **Incidents → New → Connected telemetry.** Enter the incident, time and window, tick *Azure Monitor*, choose
   templates. **Find services in this window** lists cloud role names.
3. **Preview returned evidence**: per-query status, provenance, issues (partial, truncated, sampled, empty bins),
   sample records with their source reference, and the returned metric series charted as returned.
4. **Create incident & start analysis** stores the snapshot and starts the read-only investigation. The report can be
   downloaded as Markdown; deleting the incident deletes the snapshot.

## Service discovery

One fixed query over the window:

```kusto
union isfuzzy=true AppRequests, AppDependencies, AppExceptions, AppTraces
| summarize records = count() by AppRoleName
| top 51 by records desc
```

- At most 50 roles are listed (the 51st row only tells OpsPilot the list was cut).
- Names are kept exactly, lower-cased: `orders-api` stays `orders-api`. Queries match `AppRoleName =~ "<name>"`
  (case-insensitive), and every record keeps the exact recorded role in `azure.app_role_name`. A mixed-case role such
  as `Billing.Worker` is listed as `billing.worker` with a note; two roles that differ only in case are reported as such.
- Names that cannot be a service name (spaces, `:`, `/`, longer than 63 characters) are listed as unusable, and records
  without `AppRoleName` are counted. Nothing is silently rewritten.
- A service name can be typed by hand when discovery is unavailable; it is validated the same way.

## KQL templates and query safety

Templates are fixed KQL text chosen by ID; no request carries KQL, a table, workspace, URL or resource ID.

```kusto
// request_failure_ratio, rendered for orders-api over a 2-hour window (60 s bins)
AppRequests
| where AppRoleName =~ "orders-api"
| summarize value = todouble(sumif(ItemCount, Success == false)) / todouble(sum(ItemCount)),
    records = count(), items = sum(ItemCount) by bin(TimeGenerated, 60s)
| order by TimeGenerated asc
```

- **Placeholders**: `$selector` → `AppRoleName =~ "<service>"` (service validated against
  `^[a-z][a-z0-9._-]{1,62}$`, then quoted as a KQL string literal with `\` and `"` escaped); `$limit` → row limit + 1
  (so a truncated answer is detected); `$bin` / `$bin_seconds` → the bin size (≥ 60 s, about 240 bins per window).
- **Bounded time**: the window is sent as the documented `timespan` (`start/end`), checked against the 6 h limit and
  refused if it ends in the future.
- **Bounded rows**: `take`/`top` in the query, and the row count is checked again after retrieval.
- **Bounded run time**: `Prefer: wait=<TELEMETRY_TIMEOUT_SECONDS>` asks the service to stop the query server-side.
- **Operator template files** (`TELEMETRY_TEMPLATES_FILE`) may add Azure templates, which must start with one of
  `AppTraces`, `AppExceptions`, `AppRequests`, `AppDependencies`, `AppEvents` followed by `| where $selector`, use
  `$selector` exactly once, end with `take $limit`/`top $limit` (logs, spans) or summarize `value` by
  `bin(TimeGenerated, $bin)` (metrics), and may not contain `union`, `join`, `lookup`, `let`, `set`, `declare`,
  `evaluate`, `invoke`, `search`, `find`, `externaldata`, `external_table`, `materialize`, `workspace()`, `app()`,
  `resource()`, `cluster()`, `database()`, `adx()`, `arg()`, `table()`, `;`, comments or control commands.
- **Expansion** (`failed_requests`): the `OperationId`s of up to 10 matched requests (validated against
  `^[A-Za-z0-9][A-Za-z0-9._|-]{0,127}$`) are queried in fixed `AppRequests`/`AppDependencies` queries, within the same
  window and the same record budget.

### Cost and request bounds

Log Analytics queries can incur charges depending on the workspace's plan. OpsPilot runs only what the operator
previews or snapshots: per preview/snapshot at most 40 template queries (plus at most 2 expansion queries per
`failed_requests` query), at most 2 queries in flight per connector (the service allows 5 concurrent queries and 200
requests per 30 s per user), bounded rows and bins, a 5 MiB response cap and a 10 s timeout. The connection test is
5 tiny queries. No resource, diagnostic setting, alert, data collection rule or ingestion is ever created or changed.

## Normalization and provenance

Every record's source reference is `azure_monitor/<template>/<service>:entry|point|span N`, the prefix of a query in
the snapshot's provenance list, which records: provider (`azure_monitor`, *Azure Monitor*), workspace ID, source
table(s), template ID and label, service, the exact KQL that ran, window, bin size, row limit, status
(`ok`/`empty`/`error`), error kind, returned/rejected counts, truncation, issues, collection time and duration.

- **AppTraces → LogRecord**: `SeverityLevel` 0 Verbose → DEBUG, 1 Information → INFO, 2 Warning → WARN, 3 Error and
  4 Critical → ERROR (inferred from the text, and flagged, when absent); `OperationId` → trace ID, `ParentId` → span
  ID; scalar `Properties` kept as `prop.*`; credential-like values redacted.
- **AppExceptions → LogRecord** (ERROR unless `SeverityLevel` says otherwise): `"<ExceptionType>: <OuterMessage> |
  innermost <type>: <message>"`; `exception.type`, `exception.innermost_type`, `exception.problem_id`,
  `exception.method`, `exception.stack` (up to 10 frames) and `exception.stack_truncated` when more frames exist or
  Application Insights did not keep the full stack; `exception.stack = "not recorded"` when there is none.
- **AppRequests / AppDependencies → SpanRecord**: `OperationId` → trace ID, `Id` → span ID, `ParentId` → parent
  (none when it equals the operation ID), `DurationMs`, status `error`/`ok` exactly as `Success` says (otherwise
  `unset`), result code, `http.status_code` for HTTP, `dependency.type` and `dependency.target`. Request payloads,
  URLs and dependency command text (`Data`) are not collected.
- **Bins → MetricRecord**, one per returned bin at the bin start, with the template's unit. Bins without records are
  **absent, never zero**; a `null` value (e.g. a percentile over nothing) is left out and counted.
- Every record keeps the exact `AppRoleName`, `AppRoleInstance`, `AppVersion` and, when not 1, `azure.item_count`.

## Sampling, correlation and what the evidence cannot show

- **Sampling.** Application Insights may keep one record for `ItemCount` items. KQL counts, rates and ratios are
  `ItemCount`-weighted, and p95 uses `percentilew(DurationMs, ItemCount, 95)`. Records are never multiplied or
  invented. When any metric bin is sampled, or any trace, exception, request or dependency record has `ItemCount > 1`,
  the query notes it ("record counts understate event counts"); the report's *Evidence coverage* adds an *Incomplete or
  sampled* row naming those queries, and the preview shows "represents N sampled items" on records (D132).
- **Partial operations.** Records whose `ParentId` is not among the records a query returned are marked
  `parent_missing`; nothing is reconstructed. Missing dependency records do not prove a call did not happen.
- **Dependency edges.** `get_service_dependencies` reports `caller → callee` only for a recorded dependency whose
  child request belongs to another role. A `Target` without its own telemetry (a database, an external API) appears as
  the recorded target of failed calls (`upstream`), never as an observed service.
- **Exceptions.** No `AppExceptions` record is not evidence that nothing failed; a missing table leaves that query
  failed (`unsupported`) and the report lists it under *Not collected / unavailable*.
- **Change history** is never collected. The RCA prompt and digest say it is unknown; start-up, version and
  configuration lines found by `trace_lifecycle` are *log indicators of a possible change*, not a verified deployment
  history; claims that "nothing changed" are flagged as unsupported (D125).
- **Empty answers.** Microsoft documents that a query over protected or restricted data succeeds with zero rows when
  the caller lacks data access. OpsPilot cannot tell that from "no matching telemetry" without Azure Resource Manager
  or permission lookups, which it does not make. An empty Azure query is therefore reported as **"No accessible
  matching records — access/coverage not independently verified"** (provenance note, preview badge *no accessible
  records*, its own *Evidence coverage* row, and the provenance table), never as "nothing found" (D136). HTTP 401/403
  and `PartialError` keep their explicit handling.
- **Model confidence** in the report is the model's own uncalibrated estimate.
- **Claim calibration.** The report keeps observed facts, evidence-supported hypotheses, verified conclusions (none in
  a read-only analysis) and unknowns apart, and adds deterministic notes when the model states a cause as fact,
  presents a start-up or configuration log line as a deployment or configuration change, describes the incident as
  "ongoing" (that is the end of the snapshot window, not the live state), or when a suggested restart would not fix a
  persisted configuration (D135). The model's text is never edited.

## Error conditions

| Situation | Result |
|---|---|
| Invalid/expired secret, unknown tenant/app | `auth_error` with the `AADSTS` code; no query is sent |
| Managed identity / Azure CLI not available | `auth_error` ("not available here") |
| HTTP 401 | token refreshed once and retried; otherwise `auth_error` |
| HTTP 403 `InvalidAuthenticationToken*` | `auth_error` |
| HTTP 403 `InsufficientAccessError` (no role) | `permission_denied` naming *Log Analytics Data Reader*; never retried |
| HTTP 404 | `not_found` (check `AZURE_MONITOR_WORKSPACE_ID`) |
| HTTP 400 "Failed to resolve table … named 'AppExceptions'" | `unsupported`: the table is not in this workspace |
| HTTP 400 for a missing column | `query_error` naming the column |
| HTTP 408 / 504 | `timeout` |
| HTTP 429 | retried at most twice when `Retry-After` ≤ 10 s, else `rate_limited` with the wait |
| HTTP 500 / 503 | `unavailable` (503 retried like 429) |
| HTTP 3xx | `redirect_refused` (redirects are never followed) |
| HTTP 200 with `error.code = PartialError` | rows kept, query marked truncated with the partial error |
| HTTP 204 | `empty` with a note (the workspace has no data), reported as no accessible matching records |
| HTTP 200 with zero rows | `empty`, reported as "No accessible matching records — access/coverage not independently verified" |
| Malformed body, short rows, missing required columns | `invalid_response` or rows rejected and counted |
| Answer > 5 MiB | `response_too_large` |

Failures are per query: other templates, signals and connectors keep their results, and the failed signal stays
unknown for that service.

## Synthetic fixture

`scripts/azure_monitor_fixture.py` (`make azure-fixture`, 127.0.0.1:8128) emulates `POST /v1/workspaces/{id}/query`
with the documented body, bearer authentication, column types (`datetime` with 7 fractional digits, `string`, `bool`,
`int`, `long`, `real`, `dynamic` as JSON text), `PartialError`, 204 and OneAPI error objects. It understands only the
KQL OpsPilot's built-in templates produce and answers anything else with HTTP 400.

Story (fictional): at 10:28:10Z `payment-service` 2.14.0 starts and loads `db.pool.max_size=5` (previously 50). From
10:31Z its SQL calls to `orders-db` wait for pooled connections, `POST /payments` fails with 503, Npgsql pool-exhaustion
exceptions follow, and `orders-api` answers 502. `inventory-service` stays healthy; at 11:12:30Z 2.13.4 with
`max_size=50` starts and the errors stop. `orders-api` is sampled at 50 % (`ItemCount` 2), so some payment requests
reference a parent dependency that is not stored. There is no deployment record anywhere.

Workspaces select scenarios: `…1001` incident, `…1002` no `AppExceptions`/`AppDependencies` tables, `…1003`
`PartialError` on every query, `…1004` malformed body, `…1005` 403 `InsufficientAccessError`, `…1006` 429
(`Retry-After: 30`), `…1007` 504, `…1008` 503, `…1009` 204, `…100a` redirect (prefix `6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f`).
An expired token is answered with 401; any other token with 403.

```bash
make azure-fixture                      # terminal 1
# terminal 2, for the API process only (never put this in a shared .env):
AZURE_MONITOR_ENABLED=true AZURE_MONITOR_AUTH_MODE=fixture \
AZURE_MONITOR_LOCAL_API_URL=http://127.0.0.1:8128 \
AZURE_MONITOR_WORKSPACE_ID=6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1001 make dev
```

Then use **Use the Azure fixture incident** on the connected intake (incident 2026-11-16 10:35Z). Automated coverage
(run `E2E_AZURE=1 make e2e` for the browser journeys; the API uses fixture port 8129 there):
`tests/unit/test_azure_monitor_connector.py`, `tests/unit/test_azure_monitor_investigation.py`,
`tests/integration/test_azure_monitor_api.py` and the Playwright journeys in `apps/web/e2e/azure.spec.ts`
(`E2E_AZURE=1`). Screenshots in `docs/images/azure/` show synthetic fixture data only.

## Optional real Azure verification

Not performed for this release. To verify against your own workspace without changing anything in Azure:

1. Use an existing workspace-based Application Insights resource with recent data, and an identity that already has
   *Log Analytics Data Reader* on that workspace (do not create resources or role assignments for this).
2. Configure the settings above in the API environment only (never paste secrets into chat or tickets).
3. Test connection; expect `ok` or `partial` with per-table detail.
4. Preview a short window (≤ 1 h) for one service with the default templates; check the provenance KQL and counts
   against the same queries in the portal's *Logs* blade.
5. Create the incident, run the analysis, download the report, then delete the incident.
6. Record the outcome (date, role, tables present, any differences) before claiming live verification.

## Known limitations

- **Fixture-only verification**: no real tenant, subscription or workspace was used.
- **Native Azure Monitor resource metrics are deferred.** They need a second audience (Azure Resource Manager), the
  `Microsoft.Insights/metrics` API (or `azure-monitor-querymetrics`; `MetricsQueryClient` was removed from
  `azure-monitor-query` 2.0) and validated resource IDs; all metrics here are derived from Application Insights records.
- **Public cloud only**; Azure Government and Azure China are not supported.
- **Workspace-based Application Insights only**; classic resources and cross-workspace queries are not supported.
- **Change history is not collected** (activity log, release annotations, App Configuration).
- **Partial distributed traces**: `failed_requests` expands at most 10 operations within the record budget, and
  sampling or missing correlation leaves operations partial.
- **Protected/restricted tables**: Microsoft documents that queries without access to protected data succeed with no
  rows; OpsPilot cannot tell that apart from "no data", so every empty Azure query is reported as *no accessible
  matching records* with access/coverage not independently verified, never as proof that no records exist.
- **Role names** with spaces, `:` or `/` cannot be queried; mixed-case roles are matched case-insensitively.
- **Service-side limits** (500,000 rows, ~100 MiB, 10 min) are far above OpsPilot's own bounds and never reached.

Decisions: D128–D136 in [DECISIONS.md](../DECISIONS.md). Release notes:
[V0.10.0_NOTES.md](../releases/V0.10.0_NOTES.md).
