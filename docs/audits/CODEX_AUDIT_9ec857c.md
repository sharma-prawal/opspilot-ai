# Codex audit of OpsPilot AI at 9ec857c (verbatim)

> Independent audit supplied by the project owner on 2026-11-04. Preserved unmodified as the
> reference for Phase C0. Remediation status is tracked in `PHASE_C0_REMEDIATION.md`.

Audit verdict: OpsPilot AI has a sound foundation for a local research prototype, but Phase C should begin with correctness and security repairs. Expanding real infrastructure access or multi-user deployment should wait.

The checkout matched 9ec857c and was clean before and after the audit. No Critical defect was verified. Several High-severity defects affect approval recovery, authentication, and incident outcomes.

I reviewed the project instructions, architecture, decisions, evaluation artifacts, tests, and implementation. Verification performed:

- 44 selected pure unit tests passed, with bytecode and pytest cache writes disabled.
- Ruff lint and formatting checks passed with caching disabled.
- In-memory reproductions exercised the findings described below.
- Full integration tests, live inference, E2E, and make evaluate were not run because they write databases, files, or application state. Published evaluation results are identified as existing evidence.

## Verified findings

1. High — The web proxy supplies operator credentials without authenticating its caller

Sources: proxy route:8 (apps/web/app/api/ops/[...path]/route.ts:8), credential injection:17 (apps/web/app/api/ops/[...path]/route.ts:17).

The BFF checks the destination path but performs no caller authentication, Origin validation, or CSRF validation. Every allowed POST receives the server's operator credential.

Reproduction: I transpiled and invoked the actual handler in memory with a mocked upstream. A request with Origin: https://untrusted.example and Content-Type: text/plain was forwarded as JSON with the operator credential attached.

Impact: A caller reaching the BFF can exercise approval, cancellation, and ingestion privileges without possessing the backend token. Browser exploitation depends on browser network protections and reachability; that was not tested.

Correction: Authenticate the BFF caller, validate same-origin POSTs, reject unsupported content types, and test the complete browser-to-backend authorization boundary.

2. High — Missing telemetry can resolve an unhealthy incident

Sources: impact calculation:199 (packages/agents/opspilot_agents/nodes.py:199), failed metric handling:355 (packages/agents/opspilot_agents/nodes.py:355), outcome precedence:57 (packages/agents/opspilot_agents/report.py:57), incident status mapping:329 (apps/api/opspilot_api/services/investigations.py:329).

_impact_ongoing() returns false whenever no unrecovered metric anomaly exists. Failed, unavailable, unsupported, or insufficient metric data therefore resembles recovery. determine_outcome() gives this false value precedence over escalation and uncertainty.

Reproduction: An in-memory RCA containing unhealthy-service evidence, missing metrics, low confidence, and an explicit escalation request produced:

computed_impact=False
outcome=no_action_required
escalate=False

Impact: The incident can become resolved during an observability outage.

Correction: Represent impact as ongoing, recovered, or unknown. Require positive, sufficient recovery evidence before resolving an incident.

3. High — Approval decisions can become permanently stranded across a crash

Sources: decision transaction:86 (apps/api/opspilot_api/services/approvals.py:86), graph submission:134 (apps/api/opspilot_api/services/approvals.py:134), resume rejection:503 (apps/api/opspilot_api/services/investigations.py:503).

The approval service commits approved, rejected, or expired before submitting the graph resume command. There is no durable delivery record or startup reconciliation for this handoff.

Reproduction: With mocked storage, failure at runner.submit() left the action approved. Retrying the decision failed because it was no longer pending. The resume API also refused because the graph still contained an approval interrupt.

Impact: An accepted operator decision can become unrecoverable through the supported APIs.

A related source-visible gap exists when the graph finishes before the application's final persistence succeeds: final persistence:279 (apps/api/opspilot_api/services/investigations.py:279) and finished-checkpoint rejection:508 (apps/api/opspilot_api/services/investigations.py:508).

Correction: Persist decision delivery through an outbox or durable command record. Reconcile checkpoints, action decisions, execution records, and application status after restart.

4. High — Recovery verification silently checks only four anomalies

Sources: target truncation:1150 (packages/agents/opspilot_agents/nodes.py:1150), recovery predicate:1193 (packages/agents/opspilot_agents/nodes.py:1193).

Verification slices the anomaly list to four entries, then declares recovery when those selected checks pass. Remaining anomalies are ignored.

Reproduction: Supplying five unrecovered anomalies caused queries for only the first four; verification returned recovered=True.

The recovery predicate also accepts arbitrarily negative excursion positions. A metric crossing far through its baseline can pass without checking whether that opposite-direction movement is itself unhealthy.

Impact: The report can claim mitigation while an observed failure remains.

Correction: Verify every required recovery condition, explicitly report checks omitted by budget, and use metric-specific health bounds. Include throughput and queue/consumer postconditions where relevant.

5. Medium — Signed approval tokens leak through tool-call history

Sources: gateway argument recording:86 (packages/mcp/opspilot_mcp/gateway.py:86), persistence:76 (apps/api/opspilot_api/repositories.py:76), HTTP response:39 (apps/api/opspilot_api/routes/investigations.py:39).

Execution arguments include approval_token. They are stored unchanged and returned by an unauthenticated endpoint.

Reproduction: A sentinel token passed through the actual gateway record, compiled persistence statement, and ToolCallOut serialization unchanged.

Impact: An execution credential reaches API consumers and potentially browser state. Its action binding and execution ledger limit reuse; this does not establish arbitrary-action execution.

Correction: Redact sensitive arguments before persistence and serialization. Extend the existing redaction test to every response containing tool records.

6. Medium — Low confidence and explicit escalation do not prevent action proposals

Sources: RCA routing:1262 (packages/agents/opspilot_agents/nodes.py:1262), proposal validation:972 (packages/agents/opspilot_agents/nodes.py:972).

Low confidence triggers follow-up only when follow-ups remain available. Otherwise, any nonempty model remediation plan proceeds to proposal validation. An explicit model escalation request does not stop this route.

Reproduction: A hypothesis with confidence 0.1, escalation.required=True, and a correlated rollback routed to propose and produced an approvable action.

Impact: Uncertain investigations can still ask operators to execute remediation. Human approval remains enforced.

Correction: Define an explicit uncertainty policy: block automatic proposals or require a clearly marked operator override with supporting evidence.

7. Medium — Document lifecycle changes can be ignored, and obsolete documents compete equally

Sources: document hash:84 (packages/rag/opspilot_rag/ingest.py:84), incremental skip:149 (packages/rag/opspilot_rag/ingest.py:149), retrieval filtering:76 (packages/rag/opspilot_rag/retrieval.py:76), agent demotion:827 (packages/agents/opspilot_agents/nodes.py:827).

The hash excludes lifecycle metadata such as status and document version. A metadata-only change can therefore be skipped without updating stored metadata.

Reproduction: Changing only status: current to status: superseded and the metadata version produced identical hashes.

Separately, retrieval uses storage status active but does not rank by lifecycle status. Agent demotion occurs after retrieval has already selected its limited results. The existing benchmark records obsolete and poisoned documents ahead of the desired runbook: baseline:25 (docs/evaluation/BASELINE.md:25).

Impact: Withdrawn guidance may retain a current label or displace current guidance.

Correction: Track metadata changes independently from embedding changes, and apply lifecycle policy before candidate truncation.

8. Medium — Retrieval evaluation measures a different path from agent retrieval

Sources: benchmark:16 (packages/evaluation/opspilot_eval/retrieval_bench.py:16), candidate depth:156 (packages/rag/opspilot_rag/retrieval.py:156), agent searches:817 (packages/agents/opspilot_agents/nodes.py:817), MCP filters:219 (packages/mcp/opspilot_mcp/read_server.py:219).

The benchmark retrieves 30 chunks, collapses them into document rankings, and searches without the agent's document-type separation. The agent requests five runbook chunks and three historical chunks. Candidate overfetch also changes with top_k.

Evidence: These are directly different parameters, filters, and ranking units in the implementation.

Impact: Published document Recall@5 does not establish the quality of the passages actually supplied to RCA.

Correction: Retain the document benchmark, and add an agent-path benchmark using identical queries, filters, candidate depths, chunk limits, and prompt excerpts.

9. Medium — "Plan acceptable" can remain true when a forbidden action executes

Sources: plan scoring:39 (packages/evaluation/opspilot_eval/agent_eval.py:39), acceptability predicate:66 (packages/evaluation/opspilot_eval/agent_eval.py:66).

Acceptability requires the expected steps to appear somewhere among successful executions. It does not reject additional actions, enforce order, or incorporate the separate forbidden-action result.

Reproduction: A synthetic execution containing an unrelated forbidden restart followed by the expected rollback returned both:

plan_acceptable=True
forbidden_executed=[restart_service]

Impact: A headline success metric can credit an unsafe plan. Failed attempted actions are also excluded from the successful-execution list used for these checks.

Correction: Score ordered plan conformance, extra actions, attempted actions, successful effects, and safety independently. Make forbidden execution incompatible with plan acceptance.

10. Medium — E2E tests default to the ordinary development stack

Sources: Playwright configuration:3 (apps/web/playwright.config.ts:3), scenario creation:17 (apps/web/e2e/investigation.spec.ts:17), execution approval:38 (apps/web/e2e/investigation.spec.ts:38), default database:35 (packages/shared/opspilot_shared/config.py:35).

Playwright targets the already-running development UI and creates incidents, investigations, and executed remediation. Python's test database guard does not apply to this process.

Evidence: The default configuration contains no dedicated test-stack provisioning or database identity assertion. E2E was not executed during this audit.

Impact: Following the documented default can write test activity into opspilot, contrary to the project's test-isolation rule.

Correction: Require a dedicated E2E stack backed by opspilot_test, and fail before mutation unless its identity is verified.

11. Low — MCP drops retrieval degradation warnings

Sources: search wrapper:215 (packages/mcp/opspilot_mcp/read_server.py:215), response schema:33 (packages/mcp/opspilot_mcp/schemas.py:33), agent warning handling:855 (packages/agents/opspilot_agents/nodes.py:855).

The retriever produces warnings when embeddings fail. The MCP wrapper reconstructs the response without those warnings, and KnowledgeHits has no warning field. Consequently, the agent's warning-reading branch receives none.

Impact: Retrieval degradation is recorded centrally but hidden from investigation observations.

Correction: Preserve warnings and effective retrieval mode across the MCP contract, with a contract-level regression test.

12. Medium — Concurrent investigation creation lacks a database invariant

Sources: start operation:369 (apps/api/opspilot_api/services/investigations.py:369), investigation table:295 (packages/shared/opspilot_shared/db/models.py:295), process-local task registry:55 (apps/api/opspilot_api/services/investigations.py:55).

Creation performs a check followed by an insert without locking the incident or enforcing uniqueness for active investigations. Two concurrent transactions can both observe no active investigation and insert different IDs.

Evidence: Verified by transaction and schema inspection; no live concurrency test was run. The existing sequential duplicate-start assertion does not exercise this interleaving.

Impact: Duplicate investigations can generate separate approval IDs for equivalent actions. The runner registry also provides coordination only within one process.

Correction: Enforce active-investigation uniqueness in PostgreSQL, serialize creation appropriately, and establish database-backed execution ownership before adding workers.

13. Medium — Historical citations lose their underlying chunk versions

Sources: chunk replacement:204 (packages/rag/opspilot_rag/ingest.py:204), citation contract:29 (packages/shared/opspilot_shared/domain/evidence.py:29), knowledge evidence:830 (packages/agents/opspilot_agents/nodes.py:830).

Updating a document deletes its previous chunks. Investigation citations retain chunk IDs, but the citation contract omits document version and content hash. Knowledge evidence retains a shortened excerpt rather than the complete cited passage.

Evidence: Verified from replacement and persistence code; no database was altered to demonstrate deletion.

Impact: Later reviewers cannot reliably reconstruct the complete source passage underlying an older RCA.

Correction: Retain immutable document/chunk versions or persist complete cited snapshots with version, hash, lifecycle status, and retrieval time.

## Suspected risks requiring targeted validation

- Medium — Cancellation and execution reconciliation. Cancellation revokes pending requests only: cancel:517 (apps/api/opspilot_api/services/investigations.py:517). The executor checks approval outside the simulator transaction and does not atomically claim executing: executor:67 (packages/mcp/opspilot_mcp/action_server.py:67). The simulator's environment lock and ledger protect duplicate effects: store:576 (services/simulator/opspilot_simulator/store.py:576). Execution after a cancellation race was not demonstrated. Add cancellation-versus-claim tests and transactional authorization checks. Also test restart after token expiry: verification precedes ledger lookup, potentially preventing reconciliation of an already-executed action.
- Medium — Process separation provides limited privilege isolation. Children inherit the complete environment: stdio configuration:102 (packages/mcp/opspilot_mcp/gateway.py:102), and use a common database configuration: backend factory:24 (packages/mcp/opspilot_mcp/backend.py:24). A compromised read adapter could have broader credentials than its tool interface suggests. No process compromise was demonstrated. Separate database roles and minimize child secrets before introducing real adapters.
- Medium — Resource bounds are incomplete under concurrent ingress. Chat concurrency is bounded per adapter instance, while embeddings have no equivalent limiter: Ollama adapters:32 (packages/shared/opspilot_shared/llm/ollama.py:32). Investigation submission can accumulate waiting tasks: runner:65 (apps/api/opspilot_api/services/investigations.py:65). Memory exhaustion or model thrashing was not measured. Add admission limits, embedding concurrency control, and load measurements.

## Architecture and reasoning assessment

The dependency direction is sensible. Agents use model/tool ports, concrete adapters are assembled at the composition root, and evaluation remains outside the application dependency chain. JSON-compatible graph state, explicit serializer configuration, deterministic action IDs, and transactional sandbox effects are strong choices.

The system implements model-assisted investigation with substantial deterministic orchestration. Capability selection, RCA hypotheses, and proposed actions come from the model. Tool ordering, anomaly detection, correlation, safety checks, and outcomes come from code. Conditional routing is real, although mandatory capabilities and fixed precedence substantially constrain planning.

I found no direct agent import or file read of evaluation ground truth or simulator scenario internals in the inspected paths. The main generalization concern is benchmark reuse: the safety rules were developed after failures on the same scenarios, as documented in D25–D28 (docs/DECISIONS.md:32). Historical incident retrieval also supplies close analogues, which is useful operationally but limits claims about novel reasoning.

Citation validation establishes that referenced evidence IDs exist. Semantic support, causal validity, and narrative faithfulness remain unmeasured. The published NEG-002 result explicitly shows correct containment despite incorrect top-ranked reasoning: baseline:73 (docs/evaluation/BASELINE.md:73).

## What is implemented well

- Fixed action catalogue with persisted parameters and action-specific signed approvals.
- Constant-time token comparison, token expiry, and compare-and-set approval decisions.
- Transactional sandbox idempotency and preservation of quarantined messages.
- Explicit failure and escalation outcomes, with visible blocked proposals.
- Heading-aware chunking, contextual embedding text, parameterized retrieval, and embedding-dimension checks.
- Deterministic tests that exercise real protocol and persistence components separately from model reasoning.
- SHA-pinned CI actions and restricted repository permissions.
- Evaluation documentation that openly acknowledges bias and model weaknesses.

## What is overengineered

The main excess is duplicated lifecycle state across checkpoints, application rows, runner tasks, and execution records without sufficient reconciliation. It creates more correctness obligations than the implementation currently fulfills.

The large node implementation (packages/agents/opspilot_agents/nodes.py:215) also concentrates collection, evidence construction, policy, approvals, execution, and verification. Smaller capability modules would improve reviewability.

Two MCP processes are reasonable for demonstrating the intended integration architecture. Their shared backend factory and credentials currently provide less security isolation than the process diagram suggests.

## Testing, evaluation, and resource assessment

The existing baseline reports successful outcomes on its small scenario set, while explicitly acknowledging deterministic sampling and scenario reuse: baseline caveats (docs/evaluation/BASELINE.md:104). Those results support prototype behavior on those cases; the defects above expose additional cases outside that evidence.

CI exercises scripted-model behavior and builds the web application. Live reasoning and browser E2E are deliberately excluded: CI:3 (.github/workflows/ci.yml:3). Missing coverage includes crash boundaries, cross-origin proxy authorization, unavailable metrics, omitted recovery checks, concurrent starts, and lifecycle-only ingestion changes.

For the M5 Pro with 24 GB, the configured deployment is appropriately restrained: native Ollama, one default PostgreSQL container, serialized chat, and bounded context/output. PostgreSQL and VM limits are explicit: Compose:19 (infra/compose/compose.yaml:19), VM configuration:9 (scripts/infra-up.sh:9). I did not independently measure current memory pressure, swap, latency, or sustained concurrency.

## Phase C decision and top 10 improvements

Phase C can proceed as a hardening and unseen-scenario validation phase. Real remediation adapters, broader network exposure, and multiple execution processes should follow the corresponding repairs.

1. Secure BFF authentication and cross-origin request handling.
2. Introduce explicit unknown-impact handling; require evidence before resolution.
3. Make approval delivery durable and reconcile application state from checkpoints.
4. Verify every required recovery condition and action postcondition.
5. Remove approval credentials from persisted and public tool records.
6. Enforce transactional execution ownership, cancellation semantics, and concurrent-start invariants.
7. Correct lifecycle ingestion, retrieval ranking, and historical citation retention.
8. Align retrieval benchmarks with the agent path and repair plan scoring.
9. Add isolated E2E infrastructure plus fault-injection and authorization regression tests.
10. Validate on independently authored unseen incidents, then profile resource pressure and introduce attributable operator identity before multi-user access.
