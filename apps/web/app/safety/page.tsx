"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, PageHeader } from "@/components/ui";

export default function SafetyPage() {
  const [activeCaseStudy, setActiveCaseStudy] = useState<"inc002" | "neg002">(
    "inc002",
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Safety Architecture & Human-In-The-Loop"
        subtitle="How OpsPilot AI separates probabilistic LLM suggestions from invariant, deterministic safety enforcement."
        actions={
          <div className="flex items-center gap-2">
            <Link href="/architecture">
              <Button variant="secondary" size="md">
                Interactive Architecture →
              </Button>
            </Link>
            <Link href="/guide">
              <Button variant="primary" size="md">
                Developer Guide
              </Button>
            </Link>
          </div>
        }
      />

      <section aria-labelledby="boundary-title">
        <h2
          id="boundary-title"
          className="mb-4 font-serif-heading text-xl font-bold"
        >
          Every action crosses an approval boundary.
        </h2>
        <ol className="boundary-flow" aria-label="Safety enforcement sequence">
          <li>
            <strong>Model proposal</strong>
            <small>A candidate action, never authorization.</small>
          </li>
          <li>
            <strong>Evidence gates</strong>
            <small>Unsafe or unsupported proposals stop here.</small>
          </li>
          <li>
            <strong>Operator approval</strong>
            <small>Review the exact action and parameters.</small>
          </li>
          <li>
            <strong>Action server</strong>
            <small>
              Verify the signed, expiring action token. Execute in the
              simulator.
            </small>
          </li>
          <li>
            <strong>Fresh verification</strong>
            <small>
              Check simulator metrics and postconditions. Unknown fails closed.
            </small>
          </li>
        </ol>
        <p className="mt-3 text-xs text-muted">
          HMAC signatures authorize individual actions. Recovery is checked
          against fresh observations; it is not cryptographically certified.
        </p>
      </section>
      <details className="compact-disclosure">
        <summary>Why the model cannot execute directly</summary>
        <div className="rounded-2xl border border-border bg-gradient-to-br from-panel via-panel to-panel-2 p-6 shadow-sm">
          <div className="max-w-3xl space-y-3">
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-warn-soft px-2.5 py-0.5 text-xs font-bold text-warn">
                Zero-Autonomous Execution Principle
              </span>
              <span className="text-xs text-muted">
                Invariant Defense in Depth
              </span>
            </div>
            <h2 className="text-lg font-bold text-text sm:text-xl">
              Why Generative AI Models Must Never Have Direct Execution
              Privileges
            </h2>
            <p className="text-xs text-muted leading-relaxed">
              Large Language Models are probabilistic token generators. When
              investigating production outages, they can hallucinate parameters,
              misidentify coincidental deployments as causal, follow prompt
              injections found in application logs, or recommend outdated
              procedures.
            </p>
            <p className="text-xs text-muted leading-relaxed">
              OpsPilot AI enforces a strict boundary:{" "}
              <strong>
                The LLM only suggests hypotheses and candidate actions.
              </strong>{" "}
              Before an action can even be surfaced to a human operator, it must
              pass a suite of hard mathematical and evidence-based safety gates
              written in deterministic code. Finally, any state-changing
              execution requires an authenticated human operator.
            </p>
          </div>
        </div>
      </details>

      {/* Visual Case Studies: Model Suggestion vs Safety Gate Decision */}
      <details className="compact-disclosure">
        <summary>Explore documented safety cases · INC-002 / NEG-002</summary>
        <div className="mt-4">
          <Card
            title="Documented Case Studies: The Safety Gate in Action"
            subtitle="Illustrations of documented simulator cases; these are not live investigation results."
            actions={
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-panel-2 p-1">
                <button
                  onClick={() => setActiveCaseStudy("inc002")}
                  className={`rounded-md px-3 py-1 text-xs font-semibold transition-all cursor-pointer ${
                    activeCaseStudy === "inc002"
                      ? "bg-accent text-white shadow-xs"
                      : "text-muted hover:text-text"
                  }`}
                >
                  INC-002: Connection Pool Explosion
                </button>
                <button
                  onClick={() => setActiveCaseStudy("neg002")}
                  className={`rounded-md px-3 py-1 text-xs font-semibold transition-all cursor-pointer ${
                    activeCaseStudy === "neg002"
                      ? "bg-accent text-white shadow-xs"
                      : "text-muted hover:text-text"
                  }`}
                >
                  NEG-002: Red-Herring Deployment
                </button>
              </div>
            }
          >
            {activeCaseStudy === "inc002" ? (
              <div className="space-y-4 pt-1">
                <div className="rounded-lg border border-border bg-panel-2/40 p-3.5 text-xs text-text-muted">
                  <strong className="text-text">Scenario Context:</strong>{" "}
                  Ledger database connection pool is at 93% capacity due to a
                  slow table scan query introduced in a recent deployment. A
                  superseded wiki runbook in the knowledge base previously
                  recommended &quot;raise pool size to 80&quot;.
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Left: Probabilistic AI Model */}
                  <div className="rounded-xl border border-border bg-panel-2/60 p-4 space-y-3">
                    <div className="flex items-center justify-between border-b border-border/80 pb-2">
                      <span className="font-mono text-xs font-bold text-purple">
                        Illustrative proposal from documented scenario
                      </span>
                      <Badge tone="warn">Probabilistic Suggestion</Badge>
                    </div>
                    <div className="rounded bg-panel p-2.5 font-mono text-xs text-text space-y-1">
                      <div>
                        action:{" "}
                        <span className="text-accent font-bold">
                          scale_connection_pool
                        </span>
                      </div>
                      <div>
                        service:{" "}
                        <span className="text-text-muted">ledger-db</span>
                      </div>
                      <div>
                        pool_size:{" "}
                        <span className="text-warn font-bold">80</span>
                      </div>
                      <div>
                        rationale: &quot;Expand pool to accommodate spike&quot;
                      </div>
                    </div>
                    <p className="text-xs text-danger leading-relaxed">
                      <strong>The Danger:</strong> The database maximum
                      connection limit is 100. Across 4 service replicas,
                      setting pool to 80 requires 320 connections. Executing
                      this would cause exhaustion of the datastore’s available
                      connections in this documented scenario.
                    </p>
                  </div>

                  {/* Right: Deterministic Safety Gate */}
                  <div className="rounded-xl border border-success/40 bg-success-soft/30 p-4 space-y-3">
                    <div className="flex items-center justify-between border-b border-success/30 pb-2">
                      <span className="font-mono text-xs font-bold text-success">
                        Deterministic Safety Gate Intercept
                      </span>
                      <Badge tone="danger">BLOCKED: Unsafe</Badge>
                    </div>
                    <div className="rounded bg-panel p-2.5 font-mono text-xs text-text space-y-1">
                      <div>
                        gate_rule:{" "}
                        <span className="text-text-muted">
                          CapacitySafetyGate
                        </span>
                      </div>
                      <div>
                        formula:{" "}
                        <span className="text-muted">
                          replicas × pool + clients ≤ 0.9 × max_conns
                        </span>
                      </div>
                      <div>
                        projected:{" "}
                        <span className="text-danger font-bold">
                          340 &gt; 90 max allowable
                        </span>
                      </div>
                      <div>
                        decision:{" "}
                        <span className="text-danger font-bold">
                          REJECTED (unsafe)
                        </span>
                      </div>
                    </div>
                    <p className="text-xs text-success leading-relaxed">
                      <strong>The Result:</strong> The safety gate blocks the
                      pool resize automatically. The agent proceeds to evaluate
                      the secondary proposal (revert deployment{" "}
                      <code className="font-mono text-text">dep-ls-0291</code>),
                      which passes all gates and cleanly mitigates the incident.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-4 pt-1">
                <div className="rounded-lg border border-border bg-panel-2/40 p-3.5 text-xs text-text-muted">
                  <strong className="text-text">Scenario Context:</strong>{" "}
                  Third-party foreign exchange provider is experiencing an API
                  outage, causing 502 Bad Gateway errors on{" "}
                  <code className="font-mono">forex-gateway</code>. An engineer
                  deployed an unrelated copy change to the frontend 15 minutes
                  before onset.
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Left: Probabilistic AI Model */}
                  <div className="rounded-xl border border-border bg-panel-2/60 p-4 space-y-3">
                    <div className="flex items-center justify-between border-b border-border/80 pb-2">
                      <span className="font-mono text-xs font-bold text-purple">
                        Illustrative proposal from documented scenario
                      </span>
                      <Badge tone="warn">False Correlation</Badge>
                    </div>
                    <div className="rounded bg-panel p-2.5 font-mono text-xs text-text space-y-1">
                      <div>
                        action:{" "}
                        <span className="text-accent font-bold">
                          rollback_deployment
                        </span>
                      </div>
                      <div>
                        deployment_id:{" "}
                        <span className="text-text-muted">dep-ta-1092</span>
                      </div>
                      <div>
                        rationale: &quot;Roll back recent deployment before
                        onset&quot;
                      </div>
                    </div>
                    <p className="text-xs text-danger leading-relaxed">
                      <strong>The Danger:</strong> The LLM saw a recent
                      deployment in git and assumed it was the cause, despite
                      errors clearly citing downstream connection timeouts to{" "}
                      <code className="font-mono">fx-partner.net</code>. Rolling
                      back would cause unnecessary churn and customer
                      disruption.
                    </p>
                  </div>

                  {/* Right: Deterministic Safety Gate */}
                  <div className="rounded-xl border border-warn/40 bg-warn-soft/30 p-4 space-y-3">
                    <div className="flex items-center justify-between border-b border-warn/30 pb-2">
                      <span className="font-mono text-xs font-bold text-warn">
                        Deterministic Safety Gate Intercept
                      </span>
                      <Badge tone="warn">BLOCKED: Causal Inconsistency</Badge>
                    </div>
                    <div className="rounded bg-panel p-2.5 font-mono text-xs text-text space-y-1">
                      <div>
                        gate_rule:{" "}
                        <span className="text-text-muted">
                          CausalConsistencyGate
                        </span>
                      </div>
                      <div>
                        check:{" "}
                        <span className="text-muted">
                          ≥80% error logs cite external dependency
                        </span>
                      </div>
                      <div>
                        dependency_status:{" "}
                        <span className="text-danger font-bold">
                          fx-partner UNHEALTHY
                        </span>
                      </div>
                      <div>
                        decision:{" "}
                        <span className="text-warn font-bold">
                          WITHHELD (escalated)
                        </span>
                      </div>
                    </div>
                    <p className="text-xs text-warn leading-relaxed">
                      <strong>The Result:</strong> Gate rejects the rollback.
                      Investigation concludes with outcome{" "}
                      <code className="font-mono text-text">escalated</code> and
                      directs the operator to page the external third-party
                      integrations team.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </Card>{" "}
        </div>
      </details>

      {/* The 7 Invariant Safety Gates */}
      <Card
        title="The Seven Invariant Safety Gates"
        subtitle="Evaluated in code (packages/agents/opspilot_agents/remediation.py) before any action reaches an operator."
      >
        <div className="safety-gate-list">
          <details>
            <summary>
              <strong>1. Impact Gate</strong>
              <span>Require fresh evidence of ongoing impact.</span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                Evaluates system state via tri-state logic (
                <code className="font-mono text-accent">ongoing</code>,{" "}
                <code className="font-mono text-accent">recovered</code>,{" "}
                <code className="font-mono text-accent">unknown</code>). Ongoing
                requires affirmative unrecovered anomaly. Conflicting or
                insufficient metrics classify as unknown, blocking remediation.
              </p>
              <div className="mt-3">
                <Badge tone="warn">insufficient_evidence</Badge>
              </div>
            </div>
          </details>
          <details>
            <summary>
              <strong>2. Evidence Grounding</strong>
              <span>Use resource targets found in collected evidence.</span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                Target deployment IDs, services, queues, and datastores in the
                action must exist verbatim in gathered evidence. Prevents
                hallucinated resource targets.
              </p>
              <div className="mt-3">
                <Badge tone="danger">invalid</Badge>
              </div>
            </div>
          </details>
          <details>
            <summary>
              <strong>3. Temporal Correlation</strong>
              <span>Link rollback targets to the incident onset.</span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                Rollback targets must have a measured temporal correlation score
                ≥ 0.3 relative to the onset timestamp. Changes made days earlier
                cannot be rolled back.
              </p>
              <div className="mt-3">
                <Badge tone="warn">unwarranted</Badge>
              </div>
            </div>
          </details>
          <details>
            <summary>
              <strong>4. Ambiguity Margin</strong>
              <span>Withhold action when candidate causes are too close.</span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                If two candidate changes correlate within 0.15 of each other (≥
                0.5), automated proposal is withheld. Only a human engineer may
                discriminate between close candidate causes.
              </p>
              <div className="mt-3">
                <Badge tone="warn">withheld_uncertain</Badge>
              </div>
            </div>
          </details>
          <details>
            <summary>
              <strong>5. Causal Consistency</strong>
              <span>
                Check whether an unchanged dependency explains the errors.
              </span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                Refuses reverting service X when ≥ 80% of X&apos;s errors
                explicitly identify an unhealthy, unchanged downstream
                dependency.
              </p>
              <div className="mt-3">
                <Badge tone="warn">unwarranted</Badge>
              </div>
            </div>
          </details>
          <details>
            <summary>
              <strong>6. Capacity Boundaries</strong>
              <span>Keep pool expansion within safe datastore limits.</span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                Database pool scale actions must mathematically verify that{" "}
                <code className="font-mono">
                  replicas × pool + clients ≤ 90%
                </code>{" "}
                of usable datastore connections and ≤ 2× expansion per step.
              </p>
              <div className="mt-3">
                <Badge tone="danger">unsafe</Badge>
              </div>
            </div>
          </details>
          <details>
            <summary>
              <strong>7. Action Plan Shape</strong>
              <span>Order containment, resolution and recovery safely.</span>
            </summary>
            <div className="safety-gate-detail">
              <p>
                Enforces canonical order: Containment → Resolution → Recovery.
                If a consumer queue is paused, a resume step is automatically
                appended by policy.
              </p>
              <div className="mt-3">
                <Badge tone="info">policy_adjusted</Badge>
              </div>
            </div>
          </details>
        </div>
      </Card>

      {/* Cryptographic Human-In-The-Loop Tokens */}
      <details className="compact-disclosure">
        <summary>
          Action authorization and recovery verification details
        </summary>
        <div className="mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card
              title="Cryptographic Action Tokens"
              subtitle="Signed, expiring authorizations preventing tampering or duplicate executions"
            >
              <div className="space-y-3 text-xs leading-relaxed text-text-muted">
                <p>When an operator approves an action in the UI:</p>
                <ul className="list-disc pl-4 space-y-1">
                  <li>
                    <strong className="text-text">
                      Deterministic Parameter Hash:
                    </strong>{" "}
                    All action arguments are serialized canonically and hashed
                    via SHA-256. Any modification to parameters invalidates
                    approval.
                  </li>
                  <li>
                    <strong className="text-text">Single-Use Token:</strong> An
                    HMAC-signed token binds approval to the action ID and
                    parameter hash, with a configured short lifetime.
                  </li>
                  <li>
                    <strong className="text-text">
                      Independent MCP Check:
                    </strong>{" "}
                    The MCP action server does not trust the API runner. It
                    independently connects to PostgreSQL to re-check the token
                    and atomically claim the action before calling the
                    simulator.
                  </li>
                  <li>
                    <strong className="text-text">
                      Automatic Expiry &amp; Sweeper:
                    </strong>{" "}
                    Pending approval requests have a separately configured
                    expiry (one hour by default). A background sweeper marks
                    them <code className="font-mono">approval_expired</code> and
                    resumes the graph into report escalation.
                  </li>
                </ul>
              </div>
            </Card>

            <Card
              title="Affirmative Recovery Verification"
              subtitle="Why 'improved' is never accepted as 'recovered'"
            >
              <div className="space-y-3 text-xs leading-relaxed text-text-muted">
                <p>
                  After an action executes, the system refuses to mark an
                  incident{" "}
                  <code className="font-mono text-success">mitigated</code>{" "}
                  without affirmative, fresh empirical proof:
                </p>
                <ul className="list-disc pl-4 space-y-1">
                  <li>
                    <strong className="text-text">
                      Residual Error Bounds:
                    </strong>{" "}
                    A 500 error rate drop from 40% to 10% is not mitigated.
                    Post-action metrics must return within baseline plus strict
                    residual limits.
                  </li>
                  <li>
                    <strong className="text-text">
                      Health Postconditions:
                    </strong>{" "}
                    Alerting services and all transitive dependencies must be
                    positively observed{" "}
                    <code className="font-mono text-success">healthy</code> with
                    timestamps after the action completed.
                  </li>
                  <li>
                    <strong className="text-text">
                      Missing Telemetry Fails Closed:
                    </strong>{" "}
                    Missing, stale, or timeout reads are treated as{" "}
                    <code className="font-mono">unknown</code>, forcing
                    verification verdict to{" "}
                    <code className="font-mono text-warn">INCOMPLETE</code> and
                    escalating to human on-call.
                  </li>
                </ul>
              </div>
            </Card>
          </div>{" "}
        </div>
      </details>
    </div>
  );
}
