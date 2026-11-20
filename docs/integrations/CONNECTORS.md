# Connected observability (v0.6; Datadog v0.9)

OpsPilot can investigate real telemetry from your observability stack. You configure a connector, choose a service,
an incident window and approved query templates, preview what comes back, and run the same LangGraph investigation
used for uploaded files. Everything stays **read-only**: nothing is approved or executed, and recovery is never
claimed from historical data.

| Provider | Signal | Status |
|---|---|---|
| Grafana Loki | logs (LogQL `query_range`) | **implemented** (tested with `grafana/loki:3.5.0`) |
| Prometheus | metrics (PromQL `query_range`) | **implemented** (tested with `prom/prometheus:v3.5.0`) |
| Azure Monitor / Application Insights | logs, metrics | planned, not implemented |
| Datadog | logs (search), metrics (timeseries query), APM spans (search) | **implemented in v0.9**, tested only against a synthetic contract fixture: [DATADOG.md](DATADOG.md). Events are not collected |
| Amazon CloudWatch | metrics, Logs Insights | planned, not implemented |
| Custom adapters | any | planned: implement the contract below |

Thanos, Mimir and VictoriaMetrics expose the Prometheus query API, but they were not tested.

## How it works

1. **Connectors exist only when configured.** `LOKI_URL` and/or `PROMETHEUS_URL`, or `DATADOG_ENABLED=true` with a
   documented `DATADOG_SITE` and keys, in the API environment. The API never accepts a URL, host, path, HTTP method or
   query text from a request.
2. **Preview.** `POST /api/v1/incidents/connected/preview` runs each selected template for the affected service and
   each other affected service (up to 4 services, 40 queries) over one window (at most `TELEMETRY_MAX_WINDOW_HOURS`,
   default 6 h). The results are normalized into the same `LogRecord` / `MetricRecord` contracts as uploads. The
   response contains record counts, per-query provenance and status, coverage warnings and sample records. Nothing is
   stored.
3. **Create.** `POST /api/v1/incidents/connected` runs the queries again and stores the result as a **snapshot** with
   the incident: the records, and every query's provenance (`ops.uploaded_datasets.queries`). The incident's
   `evidence_source` is `connector`.
4. **Investigate.** The investigation reads only the snapshot through the stored-evidence provider. Its tool calls
   are labelled `opspilot-connected-telemetry`, and the backends are not contacted again. Runbook and past-incident
   retrieval still uses the RAG knowledge base (`opspilot-ops-read`), so telemetry and knowledge stay separate.
5. **Report.** The RCA cites `loki/<template>/<service>:entry N`, `prometheus/<template>/<service>:point N` and
   `datadog/<template>/<service>:entry|point|span N`. It
   lists every query in a "Telemetry queries (provenance)" table and gives recommended next steps. Download it as
   Markdown. **Delete snapshot**, or `make uploads-purge` after the retention period, removes the snapshot and its
   analyses.

**What stays unknown.** Loki and Prometheus do not provide the following, so the agent and the report treat them as
gaps, never as healthy or unchanged:

- deployment and configuration-change history;
- traces (Datadog v0.9 adds indexed APM spans, which may be partial traces);
- live health, runtime configuration, datastore and queue state.

Two more rules apply:

- A signal whose queries failed for a service is reported as unavailable for that service. A query that succeeded
  but matched nothing is "no data".
- Version and start-up lines that the `lifecycle` template finds are log observations, not a change history.

## Configuration

All settings are environment variables of the API process (`.env` or the process environment). See `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `LOKI_URL` | empty (off) | Base URL of the Loki query API, e.g. `https://logs.example.com` |
| `LOKI_TENANT_ID` | empty | `X-Scope-OrgID` for multi-tenant Loki (Grafana Enterprise Logs; your Grafana Cloud user ID) |
| `LOKI_BEARER_TOKEN` or `LOKI_USERNAME` + `LOKI_PASSWORD` | empty | Read-only credentials |
| `LOKI_SERVICE_LABEL` | `service_name` | Stream label whose value is the service name |
| `PROMETHEUS_URL` | empty (off) | Base URL of the Prometheus API, e.g. `https://prometheus.example.com` |
| `PROMETHEUS_BEARER_TOKEN` or `PROMETHEUS_USERNAME` + `PROMETHEUS_PASSWORD` | empty | Read-only credentials |
| `PROMETHEUS_SERVICE_LABEL` | `service` | Series label whose value is the service name |
| `TELEMETRY_TEMPLATES_FILE` | empty | JSON file with extra or overriding templates (below) |
| `TELEMETRY_TIMEOUT_SECONDS` | 10 | Per-request timeout (connect timeout ≤ 5 s) |
| `TELEMETRY_MAX_WINDOW_HOURS` | 6 | Longest window |
| `TELEMETRY_MAX_LOG_LINES` | 2000 | Lines per Loki query (most recent first; the query is marked truncated at the limit) |
| `TELEMETRY_MAX_SERIES` | 20 | Series kept per Prometheus query |
| `TELEMETRY_MAX_RESPONSE_BYTES` | 5 MiB | Larger answers are abandoned (`response_too_large`) |

Restart the API after changing them. **Integrations** shows each connector's endpoint, auth mode, templates and
limits, and has a **Test connection** button. The incident form has the same button.

### First run with the local demo stack (tested)

From a working OpsPilot checkout (`make bootstrap` done, `make dev` used before):

1. **Start the database and apply migration `0011`** with the normal workflow. It is additive: it allows
   `connector` incidents and adds a `queries` column, and existing incidents are kept.

   ```bash
   make infra-up    # PostgreSQL, if not running
   make migrate     # app and test databases (Alembic head = 0011)
   ```

2. **Start the local Loki and Prometheus with synthetic telemetry:**

   ```bash
   make telemetry-up   # Loki 127.0.0.1:3310 (tenant opspilot-demo), Prometheus 127.0.0.1:9390
   ```

   `make telemetry-up` does the following:
   - generates the synthetic incident (`scripts/generate_telemetry.py`; 2026-11-12 08:00–10:00 UTC);
   - backfills it into Prometheus (`promtool tsdb create-blocks-from openmetrics`);
   - pushes the logs to Loki.

   Both containers keep their data in tmpfs, create no volumes and listen only on 127.0.0.1. Loki runs in
   multi-tenant mode, so a missing tenant answers 401 (useful to see the authentication-error state).

3. **Configure the connectors in `.env`.** The demo stack needs no credentials:

   ```bash
   LOKI_URL=http://127.0.0.1:3310
   LOKI_TENANT_ID=opspilot-demo
   PROMETHEUS_URL=http://127.0.0.1:9390
   TELEMETRY_TEMPLATES_FILE=infra/telemetry/query-templates.json
   ```

   For your own backends, put read-only credentials in their own variables: `LOKI_BEARER_TOKEN`, or
   `LOKI_USERNAME` + `LOKI_PASSWORD`, and the same for `PROMETHEUS_`. Never put them in the URL. They are sent only
   over https, or to a loopback address.

4. **Restart the API.** Settings are read once at start-up:

   ```bash
   make stop && make dev
   ```

5. **Test the connections.** On **Integrations** (`/integrations`), use **Test connection** on each connector. You
   should see *Connected (version 3.5.0)*. *Authentication failed*, *Unavailable* or *Not configured* tell you what
   to fix.

6. **Investigate:**
   1. Open **Incidents → Use Loki / Prometheus** (`/incidents/new?source=connected`) and click **Use the local demo
      incident**, which fills the service, the other affected service, the incident time and the window.
   2. Optionally click **Find services in this window**.
   3. Keep or change the ticked **query templates** under each connector.
   4. Click **Preview returned evidence** and check the per-query results, the warnings and the samples.
   5. Click **Create incident & start analysis**. The investigation page shows hypotheses with citations; use
      **Download Markdown** for the report.

7. **Stop the demo stack** when you are done (the containers and their data are removed; nothing else is touched):

   ```bash
   make telemetry-down
   ```

   Remove or comment out the connector lines in `.env` and restart the API, otherwise the connectors show as
   *Unavailable*.

The story: payment-service 2.14.0 starts at 09:12:20Z with a smaller database pool (50 → 10). From 09:14Z its
authorizations time out waiting for connections, and checkout-api payments fail with 504s. search-api restarts with a
new version at 08:31Z and stays healthy (an unrelated change). One fake credential is logged so that redaction can be
seen.

### Adapting to your application

Restart the API after each change.

| Your telemetry | What to set |
|---|---|
| Streams labelled `app="checkout"` instead of `service_name` | `LOKI_SERVICE_LABEL=app` |
| Series labelled `job="checkout"` instead of `service` | `PROMETHEUS_SERVICE_LABEL=job` |
| Label values with capitals or underscores (`Checkout_API`) | not supported: values must be lower-case slugs such as `checkout-api`; use a label that holds such values, or relabel in your pipeline |
| Different metric names (e.g. `http_server_requests_seconds_count` from Spring, or `istio_requests_total`) | write templates for them in a JSON file and set `TELEMETRY_TEMPLATES_FILE` (see [Query templates](#query-templates)). A file template with the same ID as a built-in replaces it; give it an agent-known `metric` name (`http_5xx_ratio`, `p95_latency_ms`, `db_pool_in_use`, …) so it is examined first |
| Logs in JSON | nothing: JSON lines are parsed (level, message, trace and span IDs, attributes) |
| A multi-tenant Loki or Grafana Cloud Logs | `LOKI_TENANT_ID` (the tenant or Grafana Cloud user ID) plus read-only credentials |
| A large or slow backend | `TELEMETRY_TIMEOUT_SECONDS`, `TELEMETRY_MAX_LOG_LINES`, `TELEMETRY_MAX_SERIES`, `TELEMETRY_MAX_RESPONSE_BYTES`, or a shorter window |

A template that returns "no data" in the preview usually means the metric or label name does not exist in your
backend. Run the rendered query (shown in the preview) in Grafana Explore or the Prometheus UI to adjust it.

### What was verified, and what was not

| Configuration | Status |
|---|---|
| Local `grafana/loki:3.5.0` (multi-tenant, `X-Scope-OrgID`) and `prom/prometheus:v3.5.0` over http on 127.0.0.1, synthetic data | **tested**: live connector tests, API tests and the Playwright journey |
| Error states: 401 without tenant, connection refused, 404 wrong path | tested against the local containers |
| Bearer and basic auth, timeouts, redirects, oversized answers, 4xx/5xx answers | tested against in-process fakes of the documented API responses only |
| Remote or cloud endpoints (Grafana Cloud, self-hosted Loki/Prometheus over https, Mimir, Thanos, VictoriaMetrics, Amazon Managed Prometheus, Azure Monitor managed Prometheus) | **not verified**. The official query API is the same, but authentication schemes (e.g. AWS SigV4 or Azure AD tokens) other than bearer or basic are not supported, and no remote system was contacted during development |

## Query templates

Users pick templates by ID; nobody types a query. Built-in templates:

| Connector | ID | Query (for one service) | Unit |
|---|---|---|---|
| Loki | `errors_warnings` (default) | `{$selector} \|~ "(?i)(error\|warn\|exception\|fail\|timeout\|refused\|unavailable\|panic\|fatal)"` | – |
| Loki | `lifecycle` (default) | lines about starting, stopping, versions, deploys, config, restarts | – |
| Loki | `all_lines` | `{$selector}` | – |
| Prometheus | `http_5xx_ratio` | `sum(rate(http_requests_total{$selector,status=~"5.."}[$rate])) / sum(rate(http_requests_total{$selector}[$rate]))` | ratio |
| Prometheus | `p95_latency_ms` | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{$selector}[$rate]))) * 1000` | ms |
| Prometheus | `http_requests_per_min` | `sum(rate(http_requests_total{$selector}[$rate])) * 60` | req/min |

Placeholders:

- **`$selector`** (required) becomes `<service label>="<service>"`. The service must be a lower-case slug
  (`^[a-z][a-z0-9-]{1,62}$`), so no quote, brace or backslash can reach the query.
- **`$rate`** (PromQL only) becomes a range of at least four steps, at least `5m`.

The range-query step is about window/240, a multiple of 15 s, and never finer than 15 s.

If your metric names differ, or you want more signals, add them in `TELEMETRY_TEMPLATES_FILE`. Templates in the file
replace built-ins with the same connector and ID:

```json
{"templates": [
  {"id": "db_pool_in_use", "connector": "prometheus", "label": "DB pool connections in use",
   "query": "max(db_pool_connections_in_use{$selector})", "metric": "db_pool_in_use", "unit": "connections"}
]}
```

The rules for templates:

- Every template must contain `$selector`.
- A LogQL template must start with the stream selector `{$selector…}`.
- A PromQL template needs a `metric` name for its records.
- Invalid templates are ignored and listed on Integrations.
- Metric names the agent knows (`http_5xx_ratio`, `p95_latency_ms`, `db_pool_in_use`, …) are examined first.

## Security

| Concern | Control |
|---|---|
| Destinations | Only the configured base URLs. Paths come from a fixed per-connector allowlist; requests carry template IDs, service slugs and a window. Unknown request fields (e.g. `query`, `url`) are rejected with 422 |
| State-changing operations | The HTTP client (`ReadOnlyHttp`) can only send `GET` to the allowlisted read endpoints (`query_range`, `labels`, `label/<label>/values`, `status/buildinfo`). Loki push/delete and Prometheus admin endpoints are unreachable |
| Redirects / ambient config | Redirects are refused (`redirect_refused`). Proxy variables and `.netrc` are ignored (`trust_env=False`) |
| Size and time | Window ≤ 6 h and not in the future; ≤ 40 queries; line, series and response-size limits; timeouts |
| Credentials | Environment only, never in the URL (rejected), never returned by the API (`GET /connectors` shows only the auth mode). They are sent only over https or to a loopback address. Error messages replace configured secrets and credential-like values with `[REDACTED]` |
| Untrusted content | Log lines are redacted like uploads (password/token/key fields, bearer tokens, AWS keys, private keys) and treated as data, never instructions |
| Operator boundary | Connection tests, service discovery, previews and creation are operator-only (BFF and API). A backend 401 becomes a per-query `auth_error`, never an HTTP 401 for the operator's session |
| Local only | Inference uses the local Ollama model; telemetry is stored only in the local database |

Use credentials that can only read. OpsPilot cannot tell a read-only token from an admin token. It only guarantees
that it sends read requests.

## Interface contract for new providers

A provider implements `TelemetryConnector` (`packages/shared/opspilot_shared/connectors/contract.py`):

```python
class TelemetryConnector(Protocol):
    id: str  # "loki", "prometheus", "datadog", ...
    kind: ConnectorKind
    signal: Literal["log", "metric", "span"]  # primary signal
    signals: tuple[Signal, ...]  # v0.9: every signal its templates return (Datadog: log, metric, span)

    def info(self) -> dict: ...  # display-safe: endpoint, auth mode, label, templates, limits
    def templates(self) -> list[QueryTemplate]: ...
    async def test(self) -> ConnectionStatus: ...  # ok | partial | auth_error | rate_limited | unavailable | error
    # (multi-signal providers add ConnectionStatus.signals: one SignalStatus per product)
    async def services(self, window: FetchWindow) -> list[str]: ...
    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult: ...
```

Every provider must meet these requirements:

1. **Input.** Only an approved `QueryTemplate`, a service slug and a bounded `FetchWindow`. Render the query
   with `templates.render` (or an equivalent that validates the service). Accept no free-form query, URL or path.
2. **Output.** `FetchResult(provenance, logs | metrics | spans)`. A multi-signal provider names each template's
   `signal`; `provenance.signal` decides which `Dataset.collected` entry the query counts for:
   - Records are `LogRecord` / `MetricRecord` with `ts`, `ts_original` exactly as returned, `tz`, `service`,
     `service_source` (`record` if the record names it, `query` if it comes from the selector) and `source` of the
     form `<id>/<template>/<service>:entry|point N`.
   - Units come from the template, labels are kept, and nothing is filled in. Non-finite or unparsable values are
     skipped and counted in `provenance.rejected`.
3. **Failures.** Backend failures are recorded in `provenance.status="error"` and `provenance.error={kind, message}`
   using the `ErrorKind` values, and are never raised. Only an invalid request raises
   `ConnectorError("invalid_request")`. Messages must not contain credentials.
4. **Transport.** Use `ReadOnlyHttp` (GET-only, allowlisted paths, no redirects, `trust_env=False`, timeouts,
   size cap, secret scrubbing) or give the same guarantees. A provider whose *read* queries are POSTs (Datadog) lists
   them in `allowed_post_paths()`; every other POST is refused, and a provider without that list cannot POST.
   Bounded retries for 429/503 (`max_retries`, `max_retry_wait`) are opt-in per connector. Subclassing `HttpConnector`
   (`connectors/base.py`) gives you URL validation, auth headers, window checks, the connection test and provenance.
5. **Registration.** Add the settings to `opspilot_shared.config.Settings`, build the connector in
   `connectors/registry.py` (only when its URL is configured), add its ID to the API's `ConnectorSourceIn` literal
   and the BFF route allowlist, and add built-in templates in `connectors/templates.py`.
6. **Tests.** Serve the backend's documented response shapes through `httpx.MockTransport` (see
   `tests/fakes/telemetry.py`). Cover normalization, provenance, each error kind, limits and "GET only to allowlisted
   paths". If you can, also test against the real backend locally (see `tests/integration/test_telemetry_live.py`).

The investigation, evidence analysis, report and UI need no change: they consume the normalized records and
provenance.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `auth_error` "no org id" | multi-tenant Loki: set `LOKI_TENANT_ID` |
| `auth_error` 401/403 | wrong or expired read-only credentials |
| `not_found` 404 | base URL or path prefix wrong (point at the API, not the UI) |
| `redirect_refused` | the URL points at a login page or UI path |
| `query_error` 400 | the template does not fit your schema (metric or label names) |
| "no data" | right backend, but nothing for this service label value or window |
| empty results for old data on a self-hosted Loki | chunks flushed but not yet indexed; the local test config keeps them in memory (`infra/telemetry/loki.yaml`) |
