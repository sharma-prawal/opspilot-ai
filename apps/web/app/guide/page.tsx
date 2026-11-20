"use client";

import Link from "next/link";
import { useState } from "react";
import { ModelName } from "@/lib/models";
import { Badge, Button, Card, CodeBlock, PageHeader } from "@/components/ui";

interface GuideStep {
  number: number;
  id: string;
  title: string;
  summary: string;
  content: React.ReactNode;
}

export default function GuidePage() {
  const [activeStep, setActiveStep] = useState<string>("what-is-opspilot");

  const steps: GuideStep[] = [
    {
      number: 1,
      id: "what-is-opspilot",
      title: "1. What OpsPilot AI Is",
      summary: "Autonomous, local-first SRE investigation agent with deterministic safety gates.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            <strong className="text-text">OpsPilot AI</strong> is an enterprise-oriented, local-first autonomous incident response system. Given a distributed system failure, it investigates telemetry anomalies, correlates deployment changes, inspects downstream dependency health, queries runbooks using hybrid pgvector RAG, and formulates ranked root-cause hypotheses with verified citations.
          </p>
          <p>
            Crucially, OpsPilot AI separates <em>probabilistic AI reasoning</em> from <em>deterministic safety enforcement</em>:
          </p>
          <ul className="list-disc pl-4 space-y-1">
            <li>
              <strong className="text-text">Local-First Architecture:</strong> All inference runs locally on your machine using Ollama: the investigation model <ModelName /> and the embedding model <ModelName kind="embedding" /> (both set in <code className="font-mono">.env</code>). Zero telemetry or source code leaves your local environment.
            </li>
            <li>
              <strong className="text-text">Deterministic Safety Gates:</strong> Hard Python rules evaluate every AI remediation proposal against impact, correlation, ambiguity, and capacity constraints before any action can be presented to an operator.
            </li>
            <li>
              <strong className="text-text">Human-in-the-Loop (HITL):</strong> Every state-changing action requires an authenticated operator decision. Approvals mint single-use, 60-second HMAC-signed tokens independently verified by the MCP action server.
            </li>
            <li>
              <strong className="text-text">Affirmative Recovery Verification:</strong> Incidents are never marked resolved or mitigated unless post-action telemetry confirms all recovery thresholds have returned to baseline.
            </li>
          </ul>
        </div>
      ),
    },
    {
      number: 2,
      id: "prerequisites",
      title: "2. Architecture & Prerequisites",
      summary: "Colima / Docker, Ollama, Python uv, Node.js pnpm, and PostgreSQL 17 + pgvector.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            OpsPilot AI runs entirely on a standard modern developer laptop (macOS with Apple Silicon or Linux with GPU).
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
            <div className="rounded-lg border border-border bg-panel-2/50 p-3">
              <span className="font-bold text-text">Runtime Dependencies:</span>
              <ul className="list-disc pl-4 mt-1 space-y-0.5">
                <li><strong className="text-text">Ollama:</strong> 0.40+ serving the configured <code className="font-mono">LLM_MODEL</code> (active: <ModelName />) and <code className="font-mono">EMBEDDING_MODEL</code> (active: <ModelName kind="embedding" />).</li>
                <li><strong className="text-text">Colima or Docker Engine:</strong> for PostgreSQL container runtime.</li>
                <li><strong className="text-text">PostgreSQL 17 + pgvector:</strong> port 5433 (avoids local port 5432 conflict).</li>
              </ul>
            </div>
            <div className="rounded-lg border border-border bg-panel-2/50 p-3">
              <span className="font-bold text-text">Toolchains &amp; Package Managers:</span>
              <ul className="list-disc pl-4 mt-1 space-y-0.5">
                <li><strong className="text-text">Python:</strong> 3.12 managed via <code className="text-accent font-mono">uv</code>.</li>
                <li><strong className="text-text">Node.js:</strong> v20+ with <code className="text-accent font-mono">pnpm 11+</code>.</li>
                <li><strong className="text-text">Homebrew:</strong> (macOS) for system tools.</li>
              </ul>
            </div>
          </div>
        </div>
      ),
    },
    {
      number: 3,
      id: "local-setup",
      title: "3. Local Setup & Health Check",
      summary: "One-command idempotent bootstrap and health diagnostic.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            Clone the repository and run the automated bootstrap target from the project <code className="font-mono text-accent">Makefile</code>:
          </p>
          <CodeBlock
            language="bash"
            code={`# Step 1: Install tools and write .env (stops and explains if models are missing)
make bootstrap ARGS=--install

# Step 1b: Explicit opt-in model download (~7.3 GB), then finish bootstrap
make models
make bootstrap

# Step 2: Verify all dependencies, Ollama models, and database schemas
make doctor`}
          />
          <p>
            The <code className="font-mono text-text">make doctor</code> command verifies:
          </p>
          <ul className="list-disc pl-4 space-y-0.5">
            <li>PostgreSQL 17 container is healthy on port 5433 and pgvector extension is enabled.</li>
            <li>Ollama service responds on 127.0.0.1:11434 with the configured models (active: <ModelName /> and <ModelName kind="embedding" />). <code className="font-mono">uv run opspilot models --probe</code> checks a model&apos;s capabilities and structured output before you switch.</li>
            <li>Database migrations are up to date and all 3 schemas (<code className="font-mono">ops</code>, <code className="font-mono">kb</code>, <code className="font-mono">sim</code>) exist.</li>
            <li>Operational runbooks and postmortems are ingested with 1024-dimensional embeddings.</li>
          </ul>
          <div className="rounded-lg border border-border bg-panel-2/50 p-3 space-y-2">
            <span className="font-bold text-text">Choosing the investigation model</span>
            <p>
              The investigation model is configuration, not code: set <code className="font-mono">LLM_MODEL</code> in{" "}
              <code className="font-mono">.env</code> to any local Ollama chat model and restart the API. The active model
              is currently <ModelName />. The embedding model (<ModelName kind="embedding" />) is separate; changing it
              requires re-indexing the knowledge base.
            </p>
            <CodeBlock
              language="bash"
              code={`# Preferred: qwen3.5:9b-q4_K_M   Fallback: qwen3:8b
# 1. Pull a candidate. On Apple Silicon use the explicit GGUF tag (-q4_K_M):
#    plain qwen3.5:9b resolves to an MLX build that returns HTTP 501 for structured output.
ollama pull <model>:<tag>

# 2. Check capabilities and one schema-constrained call through the real adapter
uv run opspilot models --model <model>:<tag> --probe

# 3. Compare on the six public scenarios without touching the official baseline
LLM_MODEL=<model>:<tag> uv run opspilot-eval agent --trials 1 --out /tmp/<run-name>`}
            />
            <p>
              The agent needs JSON-schema structured output (Ollama <code className="font-mono">format</code>); MCP tools
              are called by code, not by model tool-calling. Measured results and the recommended default are in{" "}
              <code className="font-mono">docs/evaluation/MODEL_COMPARISON_V0.4.md</code>. The safety gates and human
              approval apply unchanged whatever model is selected.
            </p>
          </div>
        </div>
      ),
    },
    {
      number: 4,
      id: "start-app",
      title: "4. Starting the Application",
      summary: "Start FastAPI runner and Next.js web application.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            Start the application stack using the Makefile:
          </p>
          <CodeBlock
            language="bash"
            code={`# Start FastAPI API, MCP stdio servers, and Next.js Turbopack dev server
make dev`}
          />
          <p>
            The dev target binds services to localhost only:
          </p>
          <ul className="list-disc pl-4 space-y-1">
            <li><strong className="text-text">Operator Web UI:</strong> <code className="text-accent font-mono">http://127.0.0.1:3000</code></li>
            <li><strong className="text-text">FastAPI Application Service:</strong> <code className="text-accent font-mono">http://127.0.0.1:8000</code> (readiness: <code className="font-mono">/health/ready</code>)</li>
            <li><strong className="text-text">MCP Read Server:</strong> spawned as child stdio process</li>
            <li><strong className="text-text">MCP Actions Server:</strong> spawned as child stdio process</li>
          </ul>
        </div>
      ),
    },
    {
      number: 5,
      id: "operator-signin",
      title: "5. Signing In as Operator",
      summary: "Operator authentication, session cookies, and CSRF protection.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            Open <code className="font-mono text-accent">http://127.0.0.1:3000</code> in your browser. If unauthenticated, you will be redirected to the sign-in screen:
          </p>
          <div className="rounded-lg border border-border bg-panel-2/50 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Badge tone="cyan">Role-Based Access</Badge>
              <span className="text-text font-medium">Local Operator Passphrase</span>
            </div>
            <p className="text-xs text-text-muted">
              The sign-in form requires your operator username and the secret passphrase defined in your <code className="font-mono text-text">.env</code> configuration (<code className="font-mono">WEB_OPERATOR_PASSPHRASE</code>).
            </p>
            <div className="font-mono text-[11px] text-muted">
              Default demo credentials: Name = <code className="text-text">demo-operator</code>, Passphrase = configured in <code className="text-text">.env</code>.
            </div>
          </div>
          <p>
            Once authenticated, the BFF sets a secure, HTTP-only session cookie. Any subsequent state-changing mutations automatically include a unique <code className="font-mono text-text">x-opspilot-csrf</code> header validated by the proxy.
          </p>
        </div>
      ),
    },
    {
      number: 6,
      id: "scenario-selection",
      title: "6. Choosing a Synthetic Scenario",
      summary: "Six deterministic scenarios covering positive mitigations and negative escalations.",
      content: (
        <div className="space-y-4 text-xs leading-relaxed text-text-muted">
          <p>
            OpsPilot AI includes 6 pre-configured synthetic incident scenarios generated deterministically using seed <code className="font-mono text-accent">1001</code>:
          </p>

          <div className="space-y-2">
            <h4 className="font-semibold text-success uppercase tracking-wider text-[11px]">
              Positive Mitigation Scenarios (Remediation Expected)
            </h4>
            <div className="space-y-2">
              <div className="rounded-lg border border-border bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-accent">INC-001: Incompatible Schema Migration</span>
                  <Badge tone="success">Rollback Deployment</Badge>
                </div>
                <p className="mt-1 text-text-muted">
                  An unnotified column rename in <code className="font-mono">ledger-service</code> triggers an HTTP 500 spike on <code className="font-mono">transaction-api</code>. Agent investigates telemetry, locates change correlation 1.00, retrieves rollback runbook, and requests approval to rollback deployment <code className="font-mono">dep-ls-0042</code>.
                </p>
              </div>

              <div className="rounded-lg border border-border bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-accent">INC-002: Connection Pool Exhaustion</span>
                  <Badge tone="success">Unsafe Action Blocked</Badge>
                </div>
                <p className="mt-1 text-text-muted">
                  Sequential table scan consumes 93% of database connections on <code className="font-mono">ledger-db</code>. The AI model often proposes scaling the connection pool, but <strong>deterministic safety gates block it as unsafe</strong> (capacity limit exceeded), guiding the approved action to rollback <code className="font-mono">dep-ls-0291</code>.
                </p>
              </div>

              <div className="rounded-lg border border-border bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-accent">INC-003: Invalid Settlement Payloads</span>
                  <Badge tone="success">Multi-Step Plan</Badge>
                </div>
                <p className="mt-1 text-text-muted">
                  Poison messages flood the Dead-Letter Queue due to schema drift. Generates a 4-step canonical remediation plan: <code className="font-mono">pause_consumer</code> → <code className="font-mono">rollback_deployment</code> → <code className="font-mono">quarantine_messages</code> → <code className="font-mono">resume_consumer</code>. Each step is individually approved.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2 pt-2">
            <h4 className="font-semibold text-warn uppercase tracking-wider text-[11px]">
              Negative &amp; Ambiguous Scenarios (No Action / Escalation Expected)
            </h4>
            <div className="space-y-2">
              <div className="rounded-lg border border-border bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-muted">NEG-001: Transient Latency Blip</span>
                  <Badge tone="neutral">No Action Required</Badge>
                </div>
                <p className="mt-1 text-text-muted">
                  A transient network packet loss spike that cleared before the investigation began. Telemetry verification confirms affirmative recovery; agent concludes <code className="font-mono">no_action_required</code> without any state changes.
                </p>
              </div>

              <div className="rounded-lg border border-border bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-warn">NEG-002: External FX Provider Outage</span>
                  <Badge tone="warn">Safety Gate Escalates</Badge>
                </div>
                <p className="mt-1 text-text-muted">
                  Third-party forex exchange is down. A recent internal deployment is an unrelated red-herring. The model proposes rolling back the deploy, but <strong>causal consistency safety gate blocks it</strong> and escalates to human on-call.
                </p>
              </div>

              <div className="rounded-lg border border-border bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-warn">NEG-003: Ambiguous Changes &amp; Log Outage</span>
                  <Badge tone="warn">Uncertainty Gate Escalates</Badge>
                </div>
                <p className="mt-1 text-text-muted">
                  Two deployments landed within seconds of each other while the centralized log cluster was unavailable. Ambiguity margin triggers, withholding action and escalating to human SRE with <code className="font-mono">inconclusive</code>.
                </p>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      number: 7,
      id: "starting-investigation",
      title: "7. Starting an Investigation",
      summary: "Simulation creation and asynchronous LangGraph execution.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            To start an investigation from the browser:
          </p>
          <ol className="list-decimal pl-4 space-y-1">
            <li>Go to <Link href="/" className="text-accent hover:underline font-semibold">Overview</Link> or <Link href="/incidents" className="text-accent hover:underline font-semibold">Incidents</Link>.</li>
            <li>Select a scenario (e.g. <code className="font-mono text-text">INC-001</code>) and click <strong className="text-text">Simulate</strong>.</li>
            <li>On the Incident detail page, click <strong className="text-text">Start investigation</strong>.</li>
          </ol>
          <p>
            The backend returns HTTP 202 with the investigation ID (<code className="font-mono text-text">thread_id</code>). The runner streams the StateGraph asynchronously while the Next.js UI polls checkpoints and renders the live 12-stage stepper.
          </p>
          <p>
            Alternatively, run headless from the terminal:
          </p>
          <CodeBlock
            language="bash"
            code={`uv run opspilot investigate --scenario INC-001 --decision approve`}
          />
        </div>
      ),
    },
    {
      number: 8,
      id: "understanding-evidence",
      title: "8. Understanding Evidence & Hypotheses",
      summary: "Unit-aware shift detection, log clustering, and citation verification.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            During execution, specialized nodes populate the persistent <code className="font-mono text-text">ops.evidence</code> repository:
          </p>
          <ul className="list-disc pl-4 space-y-1">
            <li><strong className="text-text">Telemetry Evidence:</strong> Bidirectional shift detection (comparing pre-incident baseline to post-onset values) and error log clustering.</li>
            <li><strong className="text-text">Change Correlation:</strong> Temporal correlation score (0.00 to 1.00) measuring how close a git deployment or config commit was to the onset timestamp.</li>
            <li><strong className="text-text">Knowledge Retrieval:</strong> Hybrid vector and keyword search chunks with source runbook citations and heading paths.</li>
          </ul>
          <p>
            The RCA step formulates ranked hypotheses. Every hypothesis must cite real evidence IDs. If the LLM generates a hallucinated evidence ID, the validation layer strips it and records a citation violation.
          </p>
        </div>
      ),
    },
    {
      number: 9,
      id: "approving-remediation",
      title: "9. Reviewing & Deciding Remediation",
      summary: "Human-in-the-loop approval, parameter hashes, and sandbox execution.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            When the agent formulates a remediation action, it passes through the deterministic safety gates. If admitted, the LangGraph workflow pauses at the <code className="font-mono text-text">await_approval</code> interrupt.
          </p>
          <div className="rounded-lg border border-warn/30 bg-warn-soft/30 p-3 space-y-1">
            <span className="font-bold text-warn">How Approval Works:</span>
            <ul className="list-disc pl-4 space-y-0.5">
              <li>The operator reviews the exact action type, target parameters, and parameter SHA-256 hash.</li>
              <li>The operator may enter an optional audit comment.</li>
              <li>Clicking <strong className="text-text">Approve &amp; execute in sandbox</strong> issues a signed, 60s expiring token.</li>
              <li>The MCP action server independently validates the token and parameters against the database before executing the sandbox change.</li>
              <li>Clicking <strong className="text-text">Reject</strong> terminates remediation; the incident transitions to <code className="font-mono">remediation_rejected</code> with zero actions executed.</li>
            </ul>
          </div>
        </div>
      ),
    },
    {
      number: 10,
      id: "recovery-rca",
      title: "10. Recovery Verification & RCA Reports",
      summary: "Deterministic post-condition evaluation and postmortem report generation.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            After an approved remediation executes, the workflow enters the <code className="font-mono text-text">verify</code> node:
          </p>
          <ul className="list-disc pl-4 space-y-1">
            <li><strong className="text-text">Metric Re-query:</strong> Verifies that anomaly metrics returned within residual baseline limits.</li>
            <li><strong className="text-text">Postcondition Verification:</strong> Verifies that target state is active (e.g. rolled back revision is deployed, connection pool resized, or consumer resumed).</li>
            <li><strong className="text-text">Health Re-query:</strong> Re-queries downstream service health snapshots.</li>
          </ul>
          <p>
            Once verified, the <code className="font-mono text-text">report</code> node generates a formal engineering postmortem in Markdown format, synthesizing root causes, actions taken, evidence links, and follow-up work.
          </p>
        </div>
      ),
    },
    {
      number: 11,
      id: "upload-own-data",
      title: "11. Analyze Your Own Incident Files",
      summary: "Upload sanitized logs, metrics, traces or change events for a read-only AI investigation.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            Besides the simulator, OpsPilot can investigate evidence you export from your own systems. Open{" "}
            <Link href="/incidents/new" className="font-semibold text-accent hover:underline">Analyze files</Link>, describe the
            incident, drop up to 5 files (5 MB each, 8 MB total) and preview what was extracted before anything is stored.
            The same LangGraph workflow and your configured model (<ModelName />) run the investigation.
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-border bg-panel-2/50 p-3">
              <strong className="text-text">.log / .txt</strong>
              <p className="mt-1">Lines beginning with a timestamp; levels and <code className="font-mono">key=value</code> pairs (e.g. <code className="font-mono">upstream=</code>, <code className="font-mono">trace_id=</code>) are recognized. Stack-trace lines join the entry above.</p>
            </div>
            <div className="rounded-lg border border-border bg-panel-2/50 p-3">
              <strong className="text-text">.json</strong>
              <p className="mt-1">Arrays, JSON Lines or OTLP/JSON traces. Objects become logs, metric samples, trace spans or change events (deployment, rollback, migration, config change, alert).</p>
            </div>
            <div className="rounded-lg border border-border bg-panel-2/50 p-3">
              <strong className="text-text">.csv</strong>
              <p className="mt-1">A timestamp column plus one numeric column per metric, <code className="font-mono">metric,value[,unit]</code> rows, or an event-type column. Units come from headers like <code className="font-mono">latency (ms)</code> or suffixes like <code className="font-mono">_ms</code>.</p>
            </div>
          </div>
          <div className="rounded-lg border border-warn/30 bg-warn-soft/30 p-3">
            <strong className="text-warn">Sanitize before uploading.</strong> Remove customer data, personal data and
            secrets from your exports. Credential-looking values are redacted on parse as a safety net only.
          </div>
          <ul className="list-disc space-y-1 pl-4">
            <li><strong className="text-text">Limits:</strong> 5 files per incident, 5 MB each, 8 MB total, 50,000 records.</li>
            <li><strong className="text-text">Nothing is invented.</strong> Records without a timestamp are rejected; timestamps without an offset are read in the timezone you choose and marked as assumed. A record without a service uses the service you declare for its file, or is rejected.</li>
            <li><strong className="text-text">Citations point at your files.</strong> Every normalized record keeps <code className="font-mono">file:line</code> (or row/item/span) and its original timestamp, and evidence in the RCA shows where it came from.</li>
            <li><strong className="text-text">Read-only.</strong> Uploaded incidents get hypotheses, uncertainty and evidence gaps, recommended next steps, suggested remediation and a downloadable Markdown report. No approval is requested, nothing is executed, and recovery is never claimed.</li>
            <li><strong className="text-text">Honest gaps.</strong> Files cannot show live health, runtime configuration, datastore or queue state; those tool calls report &ldquo;not available&rdquo; and the report says what to export next.</li>
            <li><strong className="text-text">Untrusted and local.</strong> File content is data, never instructions; credential-looking values are redacted on parse; files stay under <code className="font-mono">UPLOAD_DIR</code> (default <code className="font-mono">var/uploads</code>) and in the local database. Nothing is sent to an external AI API.</li>
          </ul>
          <p>
            Try it with the synthetic example set (a checkout outage after a payment-service deploy): use{" "}
            <strong className="text-text">Load example into the form</strong> on the upload page, or download the files from{" "}
            <code className="font-mono">/examples/uploads/</code>. Delete an upload with <strong className="text-text">Delete uploaded data</strong> on its incident page (removes its files, normalized records, investigations and checkpoints, nothing else), or:
          </p>
          <CodeBlock
            language="bash"
            code={`# list uploaded incidents
uv run opspilot uploads list

# delete uploads older than UPLOAD_RETENTION_DAYS (default 14); stop the API first
make uploads-purge`}
          />
        </div>
      ),
    },
    {
      number: 12,
      id: "connected-telemetry",
      title: "12. Investigate with Loki, Prometheus & Datadog",
      summary: "Connect read-only Grafana Loki, Prometheus or Datadog, preview telemetry and run a read-only investigation.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            v0.6 adds two optional, read-only connectors: <strong className="text-text">Grafana Loki</strong> for logs and{" "}
            <strong className="text-text">Prometheus</strong> for metrics. They exist only when configured in the API
            environment, and OpsPilot contacts no other address. v0.9 adds <strong className="text-text">Datadog</strong>{" "}
            (logs, APM trace metrics and indexed APM spans) through the same templates, snapshot and read-only
            investigation. Azure Monitor, CloudWatch and custom adapters are planned, not implemented.
          </p>
          <p>First run with the local demo stack (both containers listen on 127.0.0.1 and keep data in tmpfs):</p>
          <CodeBlock
            language="bash"
            code={`# 1. database up and migration 0011 applied (additive; existing incidents are kept)
make infra-up && make migrate

# 2. local Loki :3310 (tenant opspilot-demo) + Prometheus :9390 with a synthetic incident
make telemetry-up

# 3. add to .env (demo needs no credentials)
LOKI_URL=http://127.0.0.1:3310
LOKI_TENANT_ID=opspilot-demo
PROMETHEUS_URL=http://127.0.0.1:9390
TELEMETRY_TEMPLATES_FILE=infra/telemetry/query-templates.json

# 4. restart the API so it reads the settings
make stop && make dev`}
          />
          <ol className="list-decimal space-y-1 pl-4" start={5}>
            <li>On <Link href="/integrations" className="font-semibold text-accent hover:underline">Integrations</Link>, click <strong className="text-text">Test connection</strong> for each connector: connected, authentication failed, unavailable or not configured.</li>
            <li>Open <Link href="/incidents/new?source=connected" className="font-semibold text-accent hover:underline">Connected telemetry</Link> and click <strong className="text-text">Use the local demo incident</strong> (or enter your own service, incident time and window, at most 6 h).</li>
            <li>Keep or change the ticked <strong className="text-text">query templates</strong> (errors and warnings, start-up/config lines, 5xx ratio, p95 latency, request rate, plus any from your templates file). You never type a query.</li>
            <li><strong className="text-text">Preview returned evidence</strong>: per-query status (ok, no data, auth error, unavailable, rejected, truncated), counts, warnings and sample records with their query source.</li>
            <li><strong className="text-text">Create incident & start analysis</strong> stores the results as a snapshot and starts the investigation with <ModelName />; the report cites queries and entries, lists every query, and downloads as Markdown.</li>
            <li>When done: <code className="font-mono">make telemetry-down</code>, then remove the connector lines from <code className="font-mono">.env</code> and restart the API.</li>
          </ol>
          <p>
            <strong className="text-text">Your own telemetry.</strong> For your own backends, set <code className="font-mono">LOKI_URL</code> / <code className="font-mono">PROMETHEUS_URL</code> with read-only credentials in <code className="font-mono">LOKI_BEARER_TOKEN</code> (or <code className="font-mono">LOKI_USERNAME</code> + <code className="font-mono">LOKI_PASSWORD</code>) and the <code className="font-mono">PROMETHEUS_</code> equivalents; https is required for credentials except on loopback. Point <code className="font-mono">LOKI_SERVICE_LABEL</code> / <code className="font-mono">PROMETHEUS_SERVICE_LABEL</code> at the label that holds your service names, and describe your metric names in a templates file (<code className="font-mono">TELEMETRY_TEMPLATES_FILE</code>). Restart the API after every change.
          </p>
          <p>
            <strong className="text-text">Datadog.</strong> Set <code className="font-mono">DATADOG_ENABLED=true</code>,{" "}
            <code className="font-mono">DATADOG_SITE</code> (a documented site such as <code className="font-mono">datadoghq.eu</code>),{" "}
            <code className="font-mono">DATADOG_API_KEY</code> and <code className="font-mono">DATADOG_APP_KEY</code> (an application
            key scoped to <code className="font-mono">logs_read_data</code>, <code className="font-mono">timeseries_query</code>,{" "}
            <code className="font-mono">apm_read</code>) in the API environment only, and restart the API. Test connection reports
            each product separately. Without an account, <code className="font-mono">make datadog-fixture</code> serves synthetic
            Datadog responses on 127.0.0.1; see <code className="font-mono">docs/integrations/DATADOG.md</code>.
          </p>
          <ul className="list-disc space-y-1 pl-4">
            <li><strong className="text-text">Read-only.</strong> No approval, no execution, no claim of verified recovery from historical data. The investigation reads only the stored snapshot.</li>
            <li><strong className="text-text">Unknown stays unknown.</strong> Change history and live state are not in the connected telemetry (traces only when Datadog APM spans are collected, and then possibly partial); failed queries leave that signal unknown, never &ldquo;healthy&rdquo;.</li>
            <li><strong className="text-text">Bounded and safe.</strong> GET to fixed read endpoints (Datadog: plus POST to four documented search/query endpoints only), no redirects, timeouts, line/series/size limits; credentials stay in the API environment and are redacted from errors.</li>
            <li><strong className="text-text">What was verified.</strong> Only the local Loki 3.5.0 and Prometheus 3.5.0 containers with synthetic data were tested. Remote and cloud endpoints (Grafana Cloud, https deployments, Mimir, Thanos, managed Prometheus) were not verified, and only bearer or basic auth is supported. Datadog was tested only against the synthetic contract fixture, not a live organization.</li>
          </ul>
          <p>
            Details, all settings and the interface for adding a provider: <code className="font-mono">docs/integrations/CONNECTORS.md</code>.
          </p>
        </div>
      ),
    },
    {
      number: 13,
      id: "troubleshooting",
      title: "13. Troubleshooting & Essential CLI Commands",
      summary: "Common commands from Makefile and CLI tools.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <p>
            Common operational commands:
          </p>
          <CodeBlock
            language="bash"
            code={`# Run all linters (ruff, mypy strict, import-linter, eslint)
make lint

# Run backend unit tests and web Vitest suite
make test

# Run live integration tests against local Ollama
make test-live

# Re-run full baseline agent evaluation across all scenarios
make evaluate

# Inspect health and schema status
make doctor

# Delete uploaded and connected incidents older than the retention period (API stopped)
make uploads-purge

# Local Loki + Prometheus with synthetic telemetry (v0.6) / remove them
make telemetry-up
make telemetry-down

# Stop background Colima/Docker infrastructure containers
make infra-down`}
          />
        </div>
      ),
    },
    {
      number: 14,
      id: "boundaries-limitations",
      title: "14. Limitations & Security Boundaries",
      summary: "Experimental sandbox simulator notice and threat boundaries.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <div className="rounded-lg border border-danger/30 bg-danger-soft/30 p-3 space-y-1.5">
            <span className="font-bold text-danger">Experimental Simulator Notice:</span>
            <p>
              OpsPilot AI is an experimental, local-first research prototype and operations sandbox. Remediation runs only against seeded, synthetic simulation schemas (<code className="font-mono">sim.*</code>). It has <strong>NO</strong> write access to production infrastructure, cloud providers or live Kubernetes clusters; the optional Loki/Prometheus connectors only read telemetry, and were tested only against local containers with synthetic data.
            </p>
          </div>
          <ul className="list-disc pl-4 space-y-1 pt-1">
            <li><strong className="text-text">No Shell or Arbitrary Execution:</strong> Tools do not accept free-form bash commands, arbitrary file paths, or unstructured SQL.</li>
            <li><strong className="text-text">Uploaded Evidence Is Read-Only:</strong> Incidents created from your files are analyzed, never remediated. The parsers cover common shapes, not every log format; check the preview before analyzing.</li>
            <li><strong className="text-text">Connected Telemetry Is Read-Only:</strong> The optional Loki/Prometheus (v0.6) and Datadog (v0.9) connectors only read from the URLs or Datadog site you configure, with approved templates and bounded windows; their incidents are analyzed, never remediated.</li>
            <li><strong className="text-text">Local-Only Network:</strong> Ollama and PostgreSQL communicate strictly across localhost (127.0.0.1). The only other destinations are the Loki/Prometheus URLs and the Datadog site API host you configure, if any.</li>
            <li><strong className="text-text">Shared Operator Passphrase:</strong> The current release uses an environment-configured operator passphrase; multi-tenant enterprise SSO (OIDC/SAML) is scheduled for future milestones.</li>
          </ul>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Field guide"
        subtitle="From first evidence to a reviewed decision."
        actions={
          <div className="flex items-center gap-2">
            <Link href="/integrations">
              <Button variant="secondary" size="md">
                Data Sources &amp; Integrations →
              </Button>
            </Link>
            <Link href="/architecture">
              <Button variant="secondary" size="md">
                Interactive Architecture →
              </Button>
            </Link>
            <Link href="/safety">
              <Button variant="primary" size="md">
                Safety Center
              </Button>
            </Link>
          </div>
        }
      />

      <nav className="guide-journey" aria-label="Investigation walkthrough"><Link href="/"><strong>Choose evidence →</strong><small>Simulator, files or telemetry</small></Link><Link href="/incidents"><strong>Follow the case →</strong><small>Signals and hypotheses</small></Link><Link href="/safety"><strong>Review the decision →</strong><small>Approval boundary</small></Link><Link href="/incidents"><strong>Inspect the outcome</strong><small>Cited findings and report</small></Link></nav>
      <div className="grid gap-6 lg:grid-cols-12">
        {/* Navigation Sidebar (4 cols) */}
        <div className="space-y-2 lg:col-span-4">
          <div className="dossier-paper sticky top-20 p-3">
            <h3 className="px-3 py-2 font-mono text-xs font-bold uppercase tracking-wider text-muted border-b border-border mb-1.5">
              Field Guide Sections
            </h3>
            <nav className="space-y-1 font-mono text-xs" aria-label="Guide Steps">
              {steps.map((s) => {
                const isActive = activeStep === s.id;
                return (
                  <button
                    key={s.id}
                    aria-current={isActive ? "step" : undefined}
                    onClick={() => setActiveStep(s.id)}
                    className={`flex w-full items-start gap-2.5 rounded-[3px] px-3 py-2 text-left transition-all cursor-pointer ${
                      isActive
                        ? "bg-accent-soft text-accent font-bold shadow-2xs border border-accent/30"
                        : "text-muted hover:bg-panel-2 hover:text-text"
                    }`}
                  >
                    <span className="text-[11px] opacity-75">§{String(s.number).padStart(2, "0")}.</span>
                    <span className="line-clamp-1">{s.title.replace(/^\d+\.\s*/, "")}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </div>

        {/* Active Content Card (8 cols) */}
        <div className="space-y-6 lg:col-span-8">
          {steps
            .filter((s) => s.id === activeStep)
            .map((s) => (
              <Card key={s.id} title={s.title} subtitle={s.summary}>
                {s.number === 1 ? <details className="compact-disclosure"><summary>Product overview and technical background</summary><div className="pt-3">{s.content}</div></details> : <div className="pt-2">{s.content}</div>}

                <div className="mt-8 flex items-center justify-between border-t border-border pt-4">
                  {s.number > 1 ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setActiveStep(steps[s.number - 2].id)}
                    >
                      ← Previous: Step {s.number - 1}
                    </Button>
                  ) : (
                    <div />
                  )}

                  {s.number < steps.length ? (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => setActiveStep(steps[s.number].id)}
                    >
                      Next: Step {s.number + 1} →
                    </Button>
                  ) : (
                    <Link href="/">
                      <Button variant="primary" size="sm">
                        Go to Overview Dashboard →
                      </Button>
                    </Link>
                  )}
                </div>
              </Card>
            ))}

          {/* Quick Scenario Runner Banner */}
          <div className="rounded-xl border border-border bg-gradient-to-r from-panel-2 via-panel to-panel-2 p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h4 className="text-sm font-bold text-text">Ready to run a live investigation?</h4>
                <p className="text-xs text-muted">
                  Simulate INC-001 or inspect the real-time agent workflow in the command center.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Link href="/">
                  <Button variant="primary" size="sm">
                    Simulate Scenario →
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
