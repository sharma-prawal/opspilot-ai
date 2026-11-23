# AWS CloudWatch connector (v0.11)

Optional, backend-configured and strictly read-only. OpsPilot runs approved CloudWatch Logs Insights templates and
`GetMetricData` queries for the services of one incident over one bounded window, normalizes the results into the same
evidence records as uploads and the other connectors, stores them as a frozen snapshot, and investigates only that
snapshot with the existing LangGraph workflow. AWS is an evidence provider here, never a remediation engine.

> **Verification status.** Implemented and tested against a synthetic protocol fixture
> (`scripts/cloudwatch_fixture.py`) through the real AWS SDK (boto3/botocore 1.44). **No real AWS account, credential,
> region endpoint or log group has been used.** Authentication against AWS, IAM resource scoping, quotas, Logs Insights
> syntax acceptance and scan costs are not live-verified. See [Optional live verification](#optional-live-verification).

Decisions: D137–D143 in [DECISIONS.md](../DECISIONS.md). Security summary: [SECURITY.md](../architecture/SECURITY.md).

## Capabilities

| Signal | Source | What becomes evidence |
|---|---|---|
| Logs | Logs Insights QL over the service's approved log groups | errors/exceptions, warning/error chronology, timeouts and dependency failures, start-up/version/configuration lines, failures with correlation IDs |
| Log-derived metric | Logs Insights `stats count(*) … by bin()` | error-like events per bin (`log_error_count`); bins without events are absent |
| Metrics | `cloudwatch:GetMetricData` | ALB target 5xx / request count / target response time p95 / unhealthy targets; ECS service CPU / memory; Lambda errors / invocations / duration p95 / throttles; up to 10 configured custom metrics per service |

Not collected: AWS CloudTrail, AWS Config, deployment records, X-Ray traces, alarms, live resource state. Change history
therefore stays **unknown** in every CloudWatch investigation (the existing digest and claim warnings apply).

## AWS API operations

The complete list of operations the connector can call (botocore clients for `logs`, `cloudwatch` and `sts`):

| Operation | When | Scope |
|---|---|---|
| `logs:StartQuery` | each log template × service | the service's approved log groups (`logGroupNames`, ≤ 10), `queryLanguage=CWLI`, fixed template text, `limit` = record cap + 1 |
| `logs:GetQueryResults` | polling the query just started | that query ID only |
| `logs:StopQuery` | cleanup only | a query ID **this collection started** that did not reach a terminal status (polling ceiling, timeout, cancelled request) |
| `logs:DescribeLogGroups` | connection test, discovery | `logGroupIdentifiers` = the configured log groups only (never an account-wide listing) |
| `cloudwatch:GetMetricData` | each metric template × service; one probe in the connection test | configured namespace, metric, statistic and exact dimensions |
| `sts:GetCallerIdentity` | connection test; once per connector before the first collection | account context (no permission needed) |
| `sts:AssumeRole` | only with `CLOUDWATCH_ROLE_ARN` | that one configured role |

`ListMetrics` is not used: metric identities come from the mapping, never from discovery. No AWS write API exists in the
connector, the MCP tools or the agent.

## Required IAM permissions

Example: [`infra/cloudwatch/iam-readonly-policy.example.json`](../../infra/cloudwatch/iam-readonly-policy.example.json).

| Action | Resource | Why this scope |
|---|---|---|
| `logs:StartQuery`, `logs:GetQueryResults` | the approved log-group ARNs (`arn:aws:logs:<region>:<account>:log-group:<name>`; the `:*` form is listed too) | the Service Authorization Reference lists the `log-group` resource type for these actions |
| `logs:StopQuery` | `*` | no resource type is defined for it; OpsPilot only stops its own query IDs |
| `logs:DescribeLogGroups` | `*` | no resource type is defined; used only with the configured names (optional: without it the test reports "could not be checked") |
| `cloudwatch:GetMetricData` | `*` | metric data has no resource-level scoping for these reads |

Do not use `AdministratorAccess`, `PowerUserAccess`, `ReadOnlyAccess`-style broad policies or `CloudWatchFullAccess`.
OpsPilot never creates or modifies IAM roles or policies. The resource scoping above follows AWS documentation and has
not been tested against a live account; if `StartQuery` is denied with only the exact ARN, keep the `:*` form.

## Authentication

Credentials are chosen explicitly by `CLOUDWATCH_AUTH_MODE` — never an open-ended default chain — and resolved lazily:
importing the module or starting the API makes no AWS call and starts no login.

| Mode | Credentials used | Not used |
|---|---|---|
| `profile` (recommended for development) | the named profile `CLOUDWATCH_AWS_PROFILE`: shared credentials, IAM Identity Center (SSO) cached sessions, `credential_process`, `role_arn`/`source_profile`, web identity in the profile | environment keys, instance metadata, container credentials (a profile without credentials fails instead of falling back) |
| `instance_role` (recommended on AWS) | ECS task role / EKS Pod Identity (container credentials), IRSA web identity, EC2 instance profile | environment keys, shared files, profiles |
| `access_keys` | `CLOUDWATCH_ACCESS_KEY_ID`, `CLOUDWATCH_SECRET_ACCESS_KEY`, optional `CLOUDWATCH_SESSION_TOKEN` (temporary credentials preferred; long-lived IAM user keys discouraged) | everything else |
| `fixture` | synthetic keys for the loopback fixture only | refused unless `CLOUDWATCH_LOCAL_ENDPOINT_URL` is loopback |

- `AWS_PROFILE` in the API environment is ignored outside `profile` mode, so an unrelated developer profile is never
  picked up. Configured endpoint overrides (`AWS_ENDPOINT_URL*`, `endpoint_url` in the config file), FIPS and dual-stack
  settings are ignored or refused, and every client's endpoint is verified to be `logs|monitoring|sts.<region>.amazonaws.com`.
- An expired SSO session is reported as an authentication error ("run `aws sso login --profile <name>` yourself").
- `CLOUDWATCH_ROLE_ARN` (optional) assumes one read-only role on top of the base credentials (session name
  `opspilot-cloudwatch-readonly`, 1 h, refreshed by botocore). Commercial-partition role ARNs only; nothing from a request
  can choose a role.
- `CLOUDWATCH_ACCOUNT_ID` (optional) is the expected 12-digit account; on a mismatch every query is refused.
- Keys and tokens are `SecretStr` settings, never returned by the API, never logged, never stored in snapshots or reports,
  and denied to the Next.js process (`CLOUDWATCH_*` and `AWS_*` are on the web-env denylist). AWS error messages are not
  passed through (they can name principals and SSO session e-mails): only the error code, the action and OpsPilot's own
  explanation are shown. The connection test shows the account, principal kind and role name, never the caller ARN.

## Region and partition

`CLOUDWATCH_REGION` must be a region of the AWS commercial partition (`aws`) for which the installed SDK knows both
CloudWatch Logs and CloudWatch. GovCloud (`us-gov-*`), China (`cn-*`), ISO and sovereign partitions are refused. One
connector serves one region; cross-account observability (monitoring accounts, `logGroupIdentifiers` ARNs of source
accounts) is not supported.

## Resource mapping (`CLOUDWATCH_RESOURCES_FILE`)

CloudWatch has no universal service field, so OpsPilot never infers which log groups or resources belong to a service.
The YAML file states it and is the allowlist: nothing outside it can be queried. Example:
[`infra/cloudwatch/resources.example.yaml`](../../infra/cloudwatch/resources.example.yaml).

```yaml
services:
  inventory-service:                     # OpsPilot service name, kept exactly ([a-z][a-z0-9._-], 2-63 characters)
    log_groups: [/ecs/shop-prod/inventory-service]   # ≤ 10 per service, ≤ 50 in total
    service_field: service               # only for shared log groups: the structured field that names the service
    metrics:
      alb: {load_balancer: app/shop-prod-internal/2b8d4f6a1c3e5a79, target_group: targetgroup/inventory-service/8e2c4a6b1d3f5a97}
      ecs: {cluster: shop-prod, service: inventory-service}
      lambda: {function_name: inventory-reconciler}
      custom:
        - {id: db_pool_wait_ms, namespace: Shop/Inventory, metric_name: DbConnectionWaitTime, stat: p95,
           unit: Milliseconds, dimensions: {Service: inventory-service}}
```

Validation (the file is refused, and the connector shows as not configured with the reason, when any rule fails):
log-group names match the AWS pattern `[.\-_/#A-Za-z0-9]{1,512}`; ALB values are the `app/<name>/<16 hex>` and
`targetgroup/<name>/<16 hex>` dimension forms; custom metrics cannot use an `AWS/` namespace, need 1-10 exact
dimensions, a statistic (`Sum|Average|Minimum|Maximum|SampleCount|pNN[.NN]`) and a CloudWatch standard unit; a log
group mapped to two services requires `service_field` on both (events are then attributed by a recorded field, never by
guess); unknown keys are errors.

## Configuration

```bash
CLOUDWATCH_ENABLED=true
CLOUDWATCH_REGION=eu-west-1
CLOUDWATCH_RESOURCES_FILE=/etc/opspilot/cloudwatch-resources.yaml
CLOUDWATCH_AUTH_MODE=profile                  # profile | instance_role | access_keys
CLOUDWATCH_AWS_PROFILE=opspilot-readonly
# CLOUDWATCH_ROLE_ARN=arn:aws:iam::123456789012:role/OpsPilotCloudWatchReadOnly
# CLOUDWATCH_ACCOUNT_ID=123456789012
CLOUDWATCH_MAX_RECORDS=500                    # events per Logs Insights query (10-2000)
CLOUDWATCH_QUERY_TIMEOUT_SECONDS=60           # polling ceiling per query (5-300)
```

Restart the API after a change. Shared limits (`TELEMETRY_MAX_WINDOW_HOURS`, `TELEMETRY_TIMEOUT_SECONDS`,
`TELEMETRY_MAX_RESPONSE_BYTES`) apply as for the other connectors.

## Logs Insights templates and query safety

Built-in templates only (a `TELEMETRY_TEMPLATES_FILE` entry for `cloudwatch` is rejected). Each is Logs Insights QL
with a fixed case-insensitive regular expression:

| Template | Default | Matches |
|---|---|---|
| `cw_errors` | yes | error, exception, fatal, panic, traceback, critical |
| `cw_warnings` | no | warn, error, exception, fatal, critical, timeout |
| `cw_timeouts` | yes | timeouts, refused/reset connections, exhausted pools, unavailable dependencies, circuit breakers |
| `cw_lifecycle` | yes | starting/started, listening, version/build/commit, deploy/release, config/reload, feature flag, migration, shutdown |
| `cw_correlation` | no | error/timeout/failure events that carry a request, trace or correlation ID |
| `cw_log_error_count` | yes | error-like events per `bin()` (metric) |

Shape (`cw_errors`):

```
fields @timestamp, @message, @logStream, @log, @requestId, requestId, request_id, traceId, trace_id, correlationId, correlation_id
| filter @message like /(?i)(error|exception|fatal|panic|traceback|critical)/
| sort @timestamp desc
| limit 501
```

The only substitutions are `$limit` (the record cap + 1, to tell a truncated answer from an exact fit), `$bin` (derived
from the window) and, for shared log groups, ``| filter `<service_field>` = "<service>"`` with a validated field name
(backtick-quoted) and a validated, escaped string literal. Log groups are passed as `logGroupNames`, never in the query
text. Service names are validated (`[a-z][a-z0-9._-]{1,62}`). Neither the browser nor the model can supply query text,
log groups, regions, endpoints or roles; the API accepts only connector and template IDs.

## Query lifecycle, limits and cancellation

`StartQuery → GetQueryResults (bounded polling) → terminal status → normalize`:

- at most **3 queries in flight** per connector (the account quota — 100 concurrent Logs Insights QL queries per account
  and region, shared with every other user, dashboards and scheduled queries — is not OpsPilot's to exhaust);
- polling starts at 0.5 s and backs off ×1.5 to 5 s, for at most **40 polls** or `CLOUDWATCH_QUERY_TIMEOUT_SECONDS`
  (default 60 s), whichever comes first;
- statuses: `Complete` → normalized; `Failed` → query error; `Timeout` (AWS's own 60-minute limit) → timeout;
  `Cancelled` → reported (not by this collection); `Scheduled`/`Running`/`Unknown` keep polling until the ceiling;
- at the ceiling, or when the request is cancelled (client disconnect, task cancellation), the connector calls
  `StopQuery` for **its own query ID** in a shielded cleanup. Rows a `Running` poll already returned are kept and the
  query is marked **partial**; without rows it is a timeout. A failed `StopQuery` is recorded ("the query may run until
  the AWS 60-minute limit"), never raised, and never loses collected evidence;
- per query: ≤ `CLOUDWATCH_MAX_RECORDS` events (default 500), ≤ 10 log groups, ≤ `TELEMETRY_MAX_RESPONSE_BYTES` of results,
  messages ≤ 3,000 characters after redaction; per snapshot: ≤ 40 queries across all connectors and a window of at most
  `TELEMETRY_MAX_WINDOW_HOURS` (default 6 h), never in the future;
- throttling is retried by the SDK (standard mode, 3 attempts); `ThrottlingException` and `LimitExceededException`
  (concurrency quota) are then reported as rate-limited.

### Cost and scan volume

Logs Insights is billed by the volume of uncompressed log data scanned, regardless of how few rows match; `filter … like`
does not use field indexes and scans every event in the selected groups and window. OpsPilot keeps scans narrow (mapped
groups only, bounded windows, one query per template and service) and records AWS's statistics on every query
(`recordsScanned`, `bytesScanned`, `recordsMatched`, `logGroupsScanned`), shown in the preview and the provenance. The
connection test runs one `fields @timestamp | limit 1` query over the **last minute** of each existing configured log
group (at most 10) — tiny, but billed. `GetMetricData` is billed per metric requested. **Read-only is not free.**

## Metrics

- Period: a multiple of 60 s near 240 points per window, coarsened to ≥ 300 s for data older than 15 days and ≥ 3600 s
  older than 63 days (the resolutions CloudWatch retains).
- One statistic per template (`Sum`, `Average`, `Maximum` or `p95`), stated in the record labels and the provenance; Sum,
  Average and percentiles are never mixed or converted.
- Units: `GetMetricData` does not return units. Records carry the unit AWS documents for the metric (ALB
  `TargetResponseTime` in Seconds, Lambda `Duration` in Milliseconds, ECS utilization in Percent, counts as Count) or
  the operator-configured unit for custom metrics; no conversion is applied.
- `ScanBy=TimestampAscending`, `MaxDatapoints=2000`, `NextToken` followed for at most 3 pages (then marked truncated);
  `PartialData`/`InternalError` mark the series incomplete; `Forbidden` for every metric is a permission error;
  timestamps and values of different lengths are rejected as an invalid response.
- Missing data is never invented: periods without a datapoint are absent and counted ("N of M periods had no
  datapoint"); an empty answer is "no datapoints … never read as zero" (ALB and ECS publish only while there is traffic
  or running tasks).
- Resource identity is explicit: a metric template runs for a service only when its resource (Lambda function, ALB target
  group, ECS service, custom metric) is mapped. Otherwise the query is recorded as **not queried (no mapping)** — never
  sent to AWS — and that signal stays unknown for the service. A logs-only investigation is valid.

## Service discovery

`Find services in this window` lists the services of the mapping file (sorted, exactly as written) and notes configured
log groups that do not exist in the region, groups that could not be checked (`DescribeLogGroups` denied) and services
without logs or metrics. No log or metric data is read for discovery, and nothing is enumerated account-wide.

## Normalization and provenance

- Log events → `LogRecord`: `@timestamp` as returned (UTC; `tz` "UTC"), level from structured fields (`level`,
  `severity`, …) or inferred from the text and flagged, message after credential redaction, `aws.log_group`,
  `aws.log_stream`, `aws.account` (from `@log`), `aws.ptr` (the record pointer, usable with `GetLogRecord`), correlation
  IDs as `correlation.*` and `trace_id` from `traceId`/`trace_id`. JSON and plain-text lines both work; fields that are
  not present are not invented. The service is the mapped service (`service_source` "query", noted in the provenance)
  or, with `service_field`, the recorded field ("record").
- Metric values → `MetricRecord` with `metric_original` `<namespace>/<metric> (<stat>)` and labels `stat`,
  `period_seconds`, `namespace` and `dim.<Name>`.
- Each query's provenance (`QueryProvenance.aws`): region, account (when known), log groups, query ID, final status,
  polls, scan statistics, whether it was stopped (and why a stop failed), or the metric definitions, period and status
  codes. Citations are `cloudwatch/<template>/<service>:entry|point N`; the report's provenance table lists region, signal,
  log groups and query ID. No AWS console links are generated (they cannot be built reliably from these identities).

## Snapshots and the investigation

`collection → normalize → preview → freeze → LangGraph RCA`, exactly as for the other connectors: the preview stores
nothing; *Create incident* runs the queries once more and stores records and provenance in `ops.uploaded_datasets`;
the investigation reads only that snapshot (`opspilot-connected-telemetry`) and never contacts AWS. There is no
CloudWatch-specific graph, agent or prompt path beyond a short evidence note. Connected incidents are read-only: no
approval, execution or verified recovery. Deleting the incident deletes the snapshot. No database migration.

The report keeps observed facts, evidence-supported hypotheses, contradicting evidence, unknowns and (absent) verified
conclusions apart: start-up/version/configuration lines are labelled observed log indicators, not deployment history;
"no deployment happened", "root cause is …" and "ongoing" are annotated deterministically (the model's text is never
edited); empty queries are listed as "searched, nothing found" with the note that only the approved log groups and
mapped resources were searched; failed and not-queried sources are listed as not collected.

## Error conditions

| Situation | Reported as |
|---|---|
| no credentials / profile without credentials | `auth_error` "no AWS credentials were found for the configured CLOUDWATCH_AUTH_MODE" |
| expired temporary credentials, expired SSO session | `auth_error` (with the `aws sso login --profile` hint for profiles) |
| unknown profile | `not_configured` |
| invalid key / signature | `auth_error` |
| `AccessDeniedException` | `permission_denied`, naming the action |
| log group not found | `not_found` (connection test: "not found"; discovery note) |
| `ThrottlingException`, `LimitExceededException` | `rate_limited` |
| `MalformedQueryException`, `InvalidParameterException` | `query_error` |
| query `Failed` / `Timeout` / `Cancelled` / polling ceiling | `query_error` / `timeout` / `unavailable` / partial or `timeout` |
| AWS 5xx, unreachable endpoint | `unavailable` |
| malformed rows | skipped and counted (`rejected`) |
| results above the size limit | `response_too_large` |
| wrong account (`CLOUDWATCH_ACCOUNT_ID`) | `auth_error`; nothing queried |

Evidence states stay distinct: collected; queried with no matching records; failed or incomplete; never queried (no
mapping); unavailable because of permissions; truncated by a limit. One failing query never discards another's
evidence.

## Synthetic fixture

`scripts/cloudwatch_fixture.py` answers `StartQuery`/`GetQueryResults`/`StopQuery`/`DescribeLogGroups` (AWS JSON 1.1),
`GetMetricData` (AWS JSON 1.0, the protocol botocore 1.44 selects) and `GetCallerIdentity` (query/XML), requires SigV4
signatures, and models a fictional incident (account 111122223333, us-east-1): api-gateway → checkout-service →
inventory-service; inventory-service 3.8.0 starts at 14:02:15Z and logs `db.pool.max_size=8 (previous 40)`; from 14:05Z
database connection wait p95 rises from ~6 ms to ~1.9 s, inventory times out and answers 503, checkout and api-gateway
fail, ALB 5xx and response time rise; the pool is reloaded at 14:50:30Z. CloudWatch alone does not prove the
configuration caused it, and nothing records a deployment. pricing-service's log group does not exist and its Lambda has
no datapoints; audit-worker's log group is access-denied. Scenario log groups (`/fixture/*`) cover empty, delayed,
never-finishing (stopped), partial, failed, timed-out, cancelled, throttled, concurrency-limited, malformed, denied and
uncorrelated queries; synthetic keys select expired, invalid, no-permission and wrong-account identities.

```bash
make cloudwatch-fixture       # terminal 1: 127.0.0.1:8131
# terminal 2, for the API process only (never put this in a shared .env):
CLOUDWATCH_ENABLED=true CLOUDWATCH_AUTH_MODE=fixture CLOUDWATCH_REGION=us-east-1 \
CLOUDWATCH_LOCAL_ENDPOINT_URL=http://127.0.0.1:8131 \
CLOUDWATCH_RESOURCES_FILE=infra/cloudwatch/resources.fixture.yaml make dev
```

Then *Connected telemetry → Use the CloudWatch fixture incident*. Tests: `tests/unit/test_cloudwatch_connector.py`
(botocore `Stubber` and the fixture), `tests/unit/test_cloudwatch_investigation.py`,
`tests/integration/test_cloudwatch_api.py`; browser journeys: `E2E_CLOUDWATCH=1 make e2e`
(`apps/web/e2e/cloudwatch.spec.ts`). Screenshots: `docs/images/cloudwatch/` (synthetic data).

## Optional live verification

Only with an explicitly authorized, read-only identity, a non-production or low-volume log group, and an accepted (small)
Logs Insights scan cost. Never with root, admin or unrelated corporate profiles; OpsPilot creates no AWS resource.

1. Create (yourself) a role or SSO permission set with the example policy, scoped to one or two log groups.
2. Write a mapping file with those groups (and one ALB/ECS/Lambda resource if available).
3. Set `CLOUDWATCH_AUTH_MODE=profile`, `CLOUDWATCH_AWS_PROFILE`, `CLOUDWATCH_REGION`, `CLOUDWATCH_ACCOUNT_ID`, restart the API.
4. *Integrations → AWS CloudWatch → Test connection*: account, per-log-group status and both probes.
5. Preview a 15-30 minute window with `cw_errors` only; check the scan statistics, then widen if needed.
6. Record the result (and anything that differed from this document) in `docs/PROGRESS.md`.

## Known limitations

- Fixture-tested only; no live AWS verification (authentication, IAM scoping, quotas, Logs Insights syntax, costs).
- One region and one account per API process; no cross-account observability, GovCloud, China or ISO partitions.
- Logs Insights QL only (no OpenSearch SQL/PPL); built-in templates only; regular expressions are English keywords.
- Service attribution depends on the mapping file; shared log groups need a structured `service_field`.
- No CloudTrail/AWS Config change history, X-Ray traces, alarms or live state; no console deep links.
- Units are the documented ones (not returned by the API); metric math, Metrics Insights and `ListMetrics` discovery are
  not used.
- The connection test runs small billed Logs Insights queries; `StopQuery` permission cannot be verified without a
  running query.
- `HTTPS_PROXY`/`NO_PROXY` environment variables are honoured by the SDK as usual.
