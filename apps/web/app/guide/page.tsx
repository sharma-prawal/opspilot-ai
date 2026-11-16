"use client";

import Link from "next/link";
import { useState } from "react";
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
              <strong className="text-text">Local &amp; Air-Gapped:</strong> All inference runs locally on your laptop using Ollama (Qwen3 8B and Qwen3-Embedding). Zero telemetry or source code leaves your machine.
            </li>
            <li>
              <strong className="text-text">Deterministic Safety Gates:</strong> Hard Python rules evaluate every AI remediation proposal against impact, correlation, ambiguity, and capacity constraints before any action can be presented to an operator.
            </li>
            <li>
              <strong className="text-text">Human-in-the-Loop (HITL):</strong> Every state-changing action requires an authenticated operator decision. Approvals mint single-use, 60-second cryptographic tokens independently verified by the MCP action server.
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
                <li><strong className="text-text">Ollama:</strong> 0.40+ serving <code className="text-accent font-mono">qwen3:8b</code> and <code className="text-accent font-mono">qwen3-embedding:0.6b</code>.</li>
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
            code={`# Step 1: Install tools, start containers, pull models, and run migrations
make bootstrap ARGS=--install

# Step 2: Verify all dependencies, Ollama models, and database schemas
make doctor`}
          />
          <p>
            The <code className="font-mono text-text">make doctor</code> command verifies:
          </p>
          <ul className="list-disc pl-4 space-y-0.5">
            <li>PostgreSQL 17 container is healthy on port 5433 and pgvector extension is enabled.</li>
            <li>Ollama service responds on 127.0.0.1:11434 with models <code className="font-mono">qwen3:8b</code> and <code className="font-mono">qwen3-embedding:0.6b</code>.</li>
            <li>Database migrations are up to date and all 3 schemas (<code className="font-mono">ops</code>, <code className="font-mono">kb</code>, <code className="font-mono">sim</code>) exist.</li>
            <li>Operational runbooks and postmortems are ingested with 1024-dimensional embeddings.</li>
          </ul>
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
      id: "troubleshooting",
      title: "11. Troubleshooting & Essential CLI Commands",
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

# Stop background Colima/Docker infrastructure containers
make infra-down`}
          />
        </div>
      ),
    },
    {
      number: 12,
      id: "boundaries-limitations",
      title: "12. Limitations & Security Boundaries",
      summary: "Experimental sandbox simulator notice and threat boundaries.",
      content: (
        <div className="space-y-3 text-xs leading-relaxed text-text-muted">
          <div className="rounded-lg border border-danger/30 bg-danger-soft/30 p-3 space-y-1.5">
            <span className="font-bold text-danger">Experimental Simulator Notice:</span>
            <p>
              OpsPilot AI is an experimental, local-first research prototype and operations sandbox. It is configured to run only against seeded, synthetic simulation schemas (<code className="font-mono">sim.*</code>). It is <strong>NOT</strong> connected to production infrastructure, cloud providers, or live Kubernetes clusters.
            </p>
          </div>
          <ul className="list-disc pl-4 space-y-1 pt-1">
            <li><strong className="text-text">No Shell or Arbitrary Execution:</strong> Tools do not accept free-form bash commands, arbitrary file paths, or unstructured SQL.</li>
            <li><strong className="text-text">Local-Only Network:</strong> Ollama and PostgreSQL communicate strictly across localhost (127.0.0.1) without egress.</li>
            <li><strong className="text-text">Shared Operator Passphrase:</strong> The current release uses an environment-configured operator passphrase; multi-tenant enterprise SSO (OIDC/SAML) is scheduled for future milestones.</li>
          </ul>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Developer & Operator Getting Started Guide"
        subtitle="Complete step-by-step walkthrough: installation, local runtime, operator authentication, scenario execution, and safety mechanisms."
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

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Navigation Sidebar (4 cols) */}
        <div className="space-y-2 lg:col-span-4">
          <div className="sticky top-20 rounded-xl border border-border bg-panel p-3">
            <h3 className="px-3 py-2 text-xs font-bold uppercase tracking-wider text-muted">
              Guide Table of Contents
            </h3>
            <nav className="space-y-1" aria-label="Guide Steps">
              {steps.map((s) => {
                const isActive = activeStep === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => setActiveStep(s.id)}
                    className={`flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left text-xs transition-all cursor-pointer ${
                      isActive
                        ? "bg-accent-soft text-accent font-semibold shadow-xs"
                        : "text-muted hover:bg-panel-2 hover:text-text"
                    }`}
                  >
                    <span className="font-mono text-[11px] opacity-75">{s.number}.</span>
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
                <div className="pt-2">{s.content}</div>

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
