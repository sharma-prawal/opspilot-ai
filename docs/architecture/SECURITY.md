# Security

Phase C0 hardened this model against the Codex audit of `9ec857c`; per-finding evidence is in
[`docs/audits/PHASE_C0_REMEDIATION.md`](../audits/PHASE_C0_REMEDIATION.md).

## Threat model (local-first, single operator)

| Asset | Threat | Control |
|---|---|---|
| Sandbox environment state | LLM-initiated or injected state change | Fixed remediation catalogue; actions executed only by graph code after approval; action server re-validates approval in DB and claims atomically |
| Web UI / BFF | Any local page or process driving operator actions through the proxy (C0 H1) | Explicit sign-in (passphrase → HMAC-signed HttpOnly SameSite=Strict session); every proxied call needs a session; mutations also need same-origin, a session-bound CSRF token and `application/json`; per-route roles (viewer / operator); decision identity taken from the session; fails closed when unconfigured |
| Approval decisions | Forged approval, replay, approving a different action | Operator bearer token required on **every** backend POST (server-side only); approval bound to `action_id` + `params_hash`; workflow must be paused on that action; status transitions are compare-and-set; decisions delivered through a transactional outbox (no stranded approvals) |
| Execution vs. cancellation | Executing an action after the operator cancelled (C0 H); background work resurrecting a cancelled workflow (C0-G2) | The action server claims `approved → executing` under a row lock before any effect; cancel takes the same lock, revokes `pending`/`approved` and undelivered decision commands in one transaction, and is refused once claimed. Investigation status changes only through one locked compare-and-set against a transition policy (`completed`/`cancelled` absorbing; `failed` reopened only by an operator resume); a database trigger refuses any UPDATE leaving `completed`/`cancelled`; a terminal investigation never gets a new approval request |
| Credentials in records | Approval tokens or secrets in tool-call history, events, logs, API responses (C0 E) | Central key-based redaction at the gateway record, persistence, REST DTOs, structured logs and the BFF relay; spent tokens cleared from workflow state; `opspilot sanitize-secrets` for legacy rows (dry-run by default) |
| Web server process | Backend credentials readable by the Next.js process or its children (dependency, build plugin, SSR code) | `make dev` / `scripts/start.sh` start the web server with an allowlisted environment (`opspilot_shared.web_env`): BFF settings and basic process variables only; database/MCP passwords, `ACTION_SIGNING_KEY`, model and connector settings are excluded (D116) |
| MCP server processes | A compromised server process using broader rights than its tools (C0 O) | Minimal child environment (no `.env`, no operator token, no web secrets; signing key only for the action server); separate DB roles: `opspilot_mcp_read` (read + retrieval traces) and `opspilot_mcp_actions` (sandbox writes + the status claim only) |
| Concurrency | Duplicate investigations / parallel execution of one workflow (C0 G, C0-F2); a second API worker or CLI/evaluation runtime on the same database (C0-G4) | Partial unique index (one active investigation per incident); incident row lock; DB execution-ownership lease with heartbeat; lease loss stops the segment and every runner write is fenced on ownership and terminal status. **Single execution owner per database:** every runtime takes a PostgreSQL session-level advisory lock first; a second one fails at start-up; loss of the lock (connection failure) suspends all execution (503) and the served API exits; launchers pin `--workers 1` and a `WEB_CONCURRENCY>1` start is refused |
| Stale execution owner | A process that lost ownership (or never had it) executing, checkpointing or remediating (C0-H2) | Runtime lifecycle: only READY works, loss is sticky and synchronous, start-up fails on loss before READY; database fence `(epoch, lock pid)` on every checkpoint write (trigger), runner state write and execution claim (approval tokens carry the minting owner's epoch; unbound tokens refused) |
| Mixed document revisions | Guidance assembled from two contents labelled as one version (C0-H1) | Serialized per-document publication assigning the revision under a lock; DB-enforced one-content-per-version and chunks-on-current-revision; retrieval pins version + document hash and fails closed |
| Superseded guidance | Obsolete or withdrawn operational guidance (possibly unsafe) reaching the remediation context (C0-G3) | Agent-facing retrieval excludes obsolete documents; lifecycle re-validated on the expanded rows and against committed rows before assembly; the knowledge node withholds any that still arrives; historical search only through the authenticated operator API |
| Resources | Request pile-up on the local model; unbounded queued work (C0 P, C0-F2) | Chat and embedding concurrency bounds per process; bounded admission (`max_pending_investigations`) reserved atomically before any write → HTTP 429 with nothing written; accepted-but-undispatched work is re-dispatched by the sweep |
| Test isolation | Tests or E2E mutating the development database (C0 N); tests inheriting other tests' unfinished workflows (C0-F4) | Python tests refuse non-`*_test` DBs; E2E runs its own API (forced `opspilot_test`) and web server and verifies the browser → BFF → API → DB identity before any mutation; each DB test owns its workflows and unfinished ones are retired (terminal, never deleted) after it and before the session |
| Host machine | Arbitrary command / SQL execution | No shell or SQL tool exists; tool arguments are typed with bounds (regex service names, max windows, max limits); SQL is parameterised SQLAlchemy |
| Checkpoint store | Deserialisation RCE if DB compromised | `LANGGRAPH_STRICT_MSGPACK=true`; state contains only JSON-compatible primitives |
| LLM context | Prompt injection via logs, runbooks, incident text | Evidence delimited and declared untrusted; system prompt forbids following it; outputs schema-validated; cited IDs must exist; remediation catalogue enforced in code |
| Network | Exposure of DB / API / model | All services bound to 127.0.0.1; CORS allowlist; MCP over stdio by default |
| Secrets | Leakage via VCS | `.env` git-ignored; `.env.example` placeholders only; no paid API keys exist in the system |

## Prompt-injection posture

Prompt injection cannot be fully prevented in an LLM, so the design assumes the model *can* be
manipulated and limits what a manipulated model can do:

1. The LLM never calls tools directly. Nodes call tools; the LLM only returns structured JSON.
2. The LLM's remediation output is an enum + IDs. `propose` rejects unknown action types,
   unknown services and deployment IDs not present in collected evidence.
3. Even a valid proposal only creates a `pending` request; execution requires a human approval
   recorded in the database.
4. The action server refuses any action that is not `approved`, already executed, or whose
   parameters hash differs from the approved hash.

Tests: `tests/security/` contains injected log lines and an injected runbook, and asserts that
(a) no out-of-catalogue action is proposed, (b) nothing executes without approval, (c) direct
calls to the action tool without approval fail, (d) replayed approvals are rejected.

## Data

All datasets are synthetic and generated in this repository. No customer or production data. Since v0.5 an
operator can upload their own sanitized files, since v0.6 query their own Loki/Prometheus, and since v0.9 their
own Datadog organization (see below). All of it stays local.

## Uploaded evidence (v0.5)

- File content is untrusted data. It reaches the model only inside the fenced `<evidence>` block, like simulator
  logs; incident title and description are treated the same way.
- Only `.log`, `.txt`, `.json` and `.csv` are accepted, as text; nothing is executed or rendered as HTML. File names
  are reduced to a sanitized base name; raw copies are written under `UPLOAD_DIR/<dataset id>/` (v0.9.1: a shared absolute directory outside every checkout; one resolver validates the dataset UUID, refuses symlinks and keeps every path directly under the root, and deletion never touches anything outside it) with
  server-generated names and mode 0600, inside a 0700 directory, and are never read back. No tool argument is a path.
- Credential-like values (password/token/secret/api key/authorization/cookie keys, bearer and basic schemes, AWS
  access keys, PEM private keys) are redacted at parse time, before storage or prompting.
- Limits bound memory: 5 files, 5 MB each, 8 MB total, 50 000 records; the BFF refuses bodies above 12 MB. Upload,
  preview and delete are operator-only, CSRF-checked BFF mutations.
- Uploaded incidents are read-only (D105): no approval request, no execution, no recovery claim. The normalized
  records are readable by the application role only (no MCP role grant).
- Retention: delete from the incident page or `make uploads-purge` (files, records, investigations, checkpoints).

## Connected observability (v0.6)

Full detail: [CONNECTORS.md](../integrations/CONNECTORS.md#security). Decisions D109–D112.

- **Destinations.** Only `LOKI_URL` / `PROMETHEUS_URL` from the API environment. Requests carry connector and
  template IDs, service slugs and a window. A query, URL or path field is rejected with 422. Base URLs with
  credentials, a query or a fragment are refused at start-up.
- **Read-only transport** (`ReadOnlyHttp`):
  - GET only, to a fixed per-connector allowlist: `query_range`, `labels`, `label/<label>/values`, `status/buildinfo`;
  - redirects refused, `trust_env=False` (no proxy variables or netrc);
  - connect/read timeouts and a streamed response-size cap.
  - Tests assert that only GETs to these paths of the configured hosts are made.
- **Bounds.** Window ≤ 6 h and not in the future, ≤ 40 queries, a line limit per Loki query, a series limit per
  Prometheus query, step ≈ window/240 (≥ 15 s).
- **Credentials.**
  - Bearer or basic auth from the environment; sent only over https or to loopback.
  - Never returned: the connector list shows the auth mode only.
  - Configured secrets and credential-like values are replaced in every error message.
  - Log lines are redacted like uploads.
- **Operator boundary.** Connection tests, service discovery, previews and creation are operator-only BFF/API
  mutations. A backend 401/403 is reported as a per-query `auth_error` (HTTP 200), never as an HTTP 401.
- **Read-only incidents.** Connected incidents follow D105: the investigation reads the stored snapshot only and
  never calls the backend; there is no approval request, no execution and no recovery claim.
- **Residual risk.**
  - OpsPilot cannot verify that a token is read-only: use read-only credentials.
  - A configured URL may point at an internal host by design (that is the operator's choice), but only that host.
  - Tested only against local containers with synthetic data.

## Datadog connector (v0.9)

Full detail: [DATADOG.md](../integrations/DATADOG.md#security-controls). Decisions D119–D124.

- **Query construction.** Service names must match `[a-z][a-z0-9._-]{1,62}`. In log/span search syntax every
  documented special character is escaped with `\`; metric tag scopes take only the validated value. Injection
  attempts (`OR`, wildcards, quotes, colons, braces, slashes, commas, newlines) are rejected with 422 and tested at
  the connector and the API (D126).
- **Destination.** Only `https://api.<DATADOG_SITE>`, for a site in the documented allowlist (`SITES`). Any other
  value is refused at start-up: hosts, URLs, look-alike domains, link-local addresses. Requests cannot name a host,
  path, method, query or site; such fields are 422. `DATADOG_LOCAL_API_URL` (synthetic fixture) is refused unless it
  is a loopback address.
- **Read-only surface.** `ReadOnlyHttp.post_json` accepts only paths in the connector's fixed POST allowlist: logs
  search, logs aggregate, metrics timeseries query, spans search. These are documented *read* query endpoints that
  happen to use POST. `GET` is limited to `/api/v1/validate`. The client has no PUT/PATCH/DELETE method. Loki and
  Prometheus have an empty POST allowlist and cannot POST at all. Redirects and ambient proxy settings are refused as
  for v0.6.
- **Credentials.** `DATADOG_API_KEY` / `DATADOG_APP_KEY`:
  - are read from the API environment only, never through `NEXT_PUBLIC_*`; `DATADOG_` and `DD_` are on the web
    process denylist;
  - are sent only as headers to the site's https API host;
  - are never in connector info, test results, provenance, snapshots, reports or the audit log;
  - are scrubbed from error messages, including backend echoes (tested).
- **Bounds and rate limits.**
  - Pagination is capped: ≤ 1000 records per page, ≤ 5 pages per query, the line limit and `DATADOG_MAX_SPANS`.
  - Trace expansion is capped at 10 traces per span query.
  - At most 2 Datadog requests are in flight per connector.
  - On 429/503, at most 2 retries, and only when the provider's reset is ≤ 10 s; otherwise the query fails
    `rate_limited`. Never a loop.
- **Model isolation.** No Datadog tool exists in LangGraph or MCP. The investigation reads the frozen snapshot, and
  the model's text never reaches a Datadog request.
- **Residual risk.**
  - OpsPilot cannot verify that the application key is read-only: scope it to the three read permissions.
  - Log Explorer links contain the rendered query text (service, env, filters), never a key.
  - Not verified against a live Datadog organization.

## Azure Monitor connector (v0.10, unreleased)

Full detail: [AZURE_MONITOR.md](../integrations/AZURE_MONITOR.md). Decisions D128–D134.

- **Destination.** Only `POST https://api.loganalytics.azure.com/v1/workspaces/<AZURE_MONITOR_WORKSPACE_ID>/query`
  (Azure public cloud). The workspace ID must be a GUID; names, resource IDs and URLs are refused at start-up. No
  setting accepts another host: `AZURE_MONITOR_LOCAL_API_URL` exists only for the synthetic fixture, needs
  `AZURE_MONITOR_AUTH_MODE=fixture` and is refused unless it is a loopback address. Requests cannot name a host,
  workspace, table, path or query; such fields are 422.
- **Read-only surface.** The connector's POST allowlist is that one query path and its GET allowlist is empty. No
  Azure Resource Manager, metrics, alert, diagnostic-setting, automation or ingestion API is reachable. The documented
  minimum role (*Log Analytics Data Reader* on the workspace) is all that is needed.
- **Query construction.** Templates are fixed KQL over `AppTraces`, `AppExceptions`, `AppRequests`, `AppDependencies`
  (and `AppEvents` for operator templates). Service names must match `[a-z][a-z0-9._-]{1,62}` and are inserted as a
  quoted KQL string literal (`AppRoleName =~ "<name>"`, `\` and `"` escaped, control characters refused). Operation
  IDs used for expansion are validated and quoted the same way. Operator template files are checked: one approved
  table followed by `| where $selector`, no `union`, `join`, `let`, cross-resource functions, `externaldata`,
  `evaluate`, comments, `;` or control commands.
- **Credentials.** One explicit `azure-identity` credential per `AZURE_MONITOR_AUTH_MODE` (service principal, managed
  identity or Azure CLI for development); no `DefaultAzureCredential` chain and no interactive sign-in. Bearer tokens
  are held in memory, registered with `ReadOnlyHttp` for scrubbing, and never logged or returned; credential errors
  keep only their `AADSTS` code. `AZURE_`, `MSAL_` and `IDENTITY_` are on the web-process denylist. Since v0.10 the
  isolated Playwright stack also starts Next.js through that allowlist (`web_env --exec`), so the E2E API's backend
  credentials never reach the web process.
- **Bounds.** Window ≤ 6 h sent as the documented `timespan`; `take`/`top` limits checked again after retrieval;
  `Prefer: wait=<timeout>`; 5 MiB per answer; at most 2 queries in flight; at most 10 operations expanded per
  `failed_requests` query; 429/503 retried at most twice and only when the wait is ≤ 10 s.
- **Model isolation.** No Azure tool exists in LangGraph or MCP. The investigation reads the frozen snapshot, and the
  model's text never reaches an Azure request.
- **Residual risk.**
  - Not verified against a real Azure tenant or workspace; tested only against a synthetic Logs API fixture.
  - OpsPilot cannot verify that an identity is read-only: assign only *Log Analytics Data Reader* on the workspace.
  - Queries are billed per the workspace's plan; OpsPilot bounds how many it runs but cannot see the cost.

## Safety gates on model proposals (Phase B)

Prompt injection and over-eager models both show up as unwarranted proposals. Measured on the first live
pass before the gates existed, the model rolled back unrelated deployments in all three negative scenarios and
proposed a 345-connection pool on a 200-connection database. The gates in `AGENT_WORKFLOWS.md` now block these
in code, independent of the prompt. The human approval and the action server's token check remain the final
controls; the gates reduce how often a human is asked to approve something wrong.

Adversarial content in the corpus: an unreviewed wiki page instructs "AI assistants" to restart services and
raise pools to 200 and to mark actions approved; a superseded runbook recommends a pool increase that is unsafe
under current limits. Retrieved documents carry their lifecycle status; non-current documents are halved in
relevance and labelled in evidence and reports.

Since C0, retrieval applies the lifecycle policy *before* top-k truncation: current guidance always outranks
unreviewed or unknown-status material, which outranks superseded or withdrawn guidance. The agent still labels
and demotes non-current evidence. Uncertain diagnoses never reach approval: low confidence, an explicit
escalation request, competing hypotheses with disjoint evidence, or an exhausted budget all withhold the plan.

## Known gaps (tracked)

- One shared passphrase per role (operator / viewer), not per-user identity. OIDC and approver ≠ requester are
  planned. The sign-in throttle is per process.
- Backend GET endpoints are unauthenticated on localhost; all mutations require the bearer token.
- MCP children run as the same OS user, so a compromised child could read `.env` from disk. The DB roles limit
  what its *connection* can do; per-server OS users or containers are needed before real adapters.
- LangGraph checkpoint history retains the resume value of past approval steps, including their short-lived,
  action-bound token. It is counted by `sanitize-secrets` but not rewritten, to avoid corrupting resumable runs.
- Redaction is key-based; a secret embedded in free text (for example an exception message) is not detected.
- Cancelling a run owned by another API process stops it only at its next boundary. Execution bounds are per
  process.
- An operator who approves every step still executes whatever passed the gates; the gates are evidence-based
  heuristics, not proofs of correctness. Confidence is self-reported by the model.
- Model weights are trusted as distributed by Ollama's registry.
- The application database role (`opspilot_app`) is a trusted schema owner. Ownership fencing and the
  document-revision constraints stop stale normal application writes and the MCP roles, but not a holder of that
  credential, who could disable triggers, edit the epoch or rewrite chunk rows (independent verification C0-H).
- Physical chunk IDs are not immutable: revision identity is logical source content (see RAG pipeline). Citation
  snapshots remain self-verifying.
- Operator control-plane writes from a process that has just lost ownership are not fenced; they can be delayed
  until lease or outbox recovery, without stale execution.
- Expired approval tokens written to a local development database by versions before v0.2.1 remain until the
  operator runs `opspilot sanitize-secrets --apply`.
