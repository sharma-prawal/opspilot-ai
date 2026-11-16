# v0.4 reasoning review and local model comparison

Lightweight developer report for OpsPilot AI v0.4.0 (`feature/ai-reasoning-v04`). It is not a benchmark: six
public synthetic scenarios (INC-001…003, NEG-001…003), one trial each at temperature 0, plus the INC-001 rejection
path. The C1 held-out cases and their labels were not used. Numbers come from `opspilot-eval agent --out DIR`
(supplementary runs; the official `BASELINE.md` is untouched) and are tabulated by `scripts/model_comparison.py`.
Raw traces are in `datasets/evaluation/history/v0.4-model-comparison/`.

Two views are kept apart throughout:

- **Raw model** — the RCA the model returned: hypotheses, confidence, evidence gaps, escalation and its proposed plan,
  before any deterministic gate.
- **System** — what the gated workflow did (`mitigated`, `no_action_required`, `escalated`, `proposal_blocked`).
  The safety gates were not changed in v0.4, so a system outcome can be correct while the raw model was wrong.

## 1. Diagnosis: qwen3:8b weaknesses in the published traces

Source: the 13 published v0.2.1/v0.3.0 traces (`datasets/evaluation/results/traces_latest/`, git `2116ef1`) and a
fresh re-run on this branch (`qwen3-8b-before/`), which reproduced the same raw plans. The system outcome was
correct in every run; the raw model plan was acceptable in only 4 of 13 published runs (2 of 6 in the re-run), and
the gates rejected 9 proposed steps.

The decisive facts were present in the prompt evidence each time. The failures are reasoning failures, not
retrieval or tooling failures.

| Weakness | Where | What the model did | What the evidence said |
|---|---|---|---|
| Failure to recognise that no action is required | NEG-001 (both trials) | Top hypothesis "settlement-worker 2.3.1 caused ledger-service connection reset" (0.90); proposed rolling back `dep-sw-2311` | `http_5xx_ratio … returned to baseline (recovered)`, health `healthy`; the deployment was on another service, 309 min before onset, correlation **0.00**. Gate: correlation < 0.3 |
| Hallucinated causal link / ignored dependency evidence | NEG-002 | Top hypothesis "transaction-api 3.17.3 caused fx-rates circuit-breaker misconfiguration" (0.85, `deployment_regression`) for a release that only changed OpenAPI docs and log format | 113/113 ERROR logs name `upstream fx-rates-provider timed out`; the provider is unhealthy, external (`vendor:fx-provider`) and did not change; the runbook says there is no internal action. Gate: causal-consistency |
| Hallucinated identifiers / unsupported actions | NEG-002 | `pause_consumer transaction-api` (not a consumer), `quarantine_messages settlement-events PAYMENT_TIMEOUT` (that queue has 0 failures), plus the rollback — while also setting `escalation.required = true` | Queue evidence: consumer is `settlement-worker`, pending 0, dead-lettered 0, failures none. Gates: two `invalid` rejections |
| Over-confidence and no evidence gaps under insufficient evidence | NEG-003 | 0.95 on the deployment, 0.85 on the config change, `evidence_gaps: []`, no escalation, proposed rollback | `dep-ls-0292` correlation 0.90 vs `cfg-ls-0144` 0.88; `search_logs` for ledger-service failed (log backend unavailable). Gate: ambiguity |
| Speculative extra step (unsafe) | INC-002 trial 2 | Correct rollback plus `scale_connection_pool ledger-db → 200` | No configuration evidence for the pool size; the current runbook advises against raising the pool. Gate: capacity (`unsafe`) |
| Incomplete / misordered plan | INC-003 (both trials) | `rollback → pause_consumer → quarantine`; no `resume_consumer` | Policy re-ordered to containment → resolution → recovery and appended the resume (D27) |
| Impact misread | 11 of 13 runs | `impact_ongoing = false` in every run, including the 11 where the anomaly was unrecovered | Impact is computed from evidence (D26) and overrides the model |
| Calibration | all runs | Rival hypotheses at 0.95 / 0.85 / 0.75 at once; supervisor triage always `unknown 0.3` (by design) | — |
| Tool calling / structured output | all runs | No failure: 0 schema retries, 0 citation violations | The agent calls MCP tools from code; the model only returns schema-constrained JSON |

Root causes in the prompt design:

1. The decisive signals (impact recovered, change correlation, error attribution to a dependency, missing logs) were
   scattered across 18–34 evidence items and the model weighted recency and the word "deployment" over them.
2. The prompt stated the right rules as one long paragraph; nothing forced the model to decide *whether* to act
   before writing a plan. In the JSON schema the plan came before the escalation decision.
3. Confidence semantics were undefined, so rival hypotheses were scored independently.
4. Catalogue parameter rules ("use exact IDs") did not say where the valid identifiers are.

## 2. Configurable local models

The investigation model is the `LLM_MODEL` setting; no application code names a model. The embedding model
(`EMBEDDING_MODEL`, `qwen3-embedding:0.6b`) is unchanged and separate: swapping it needs a re-index.

- `uv run opspilot models [--model NAME] [--probe]` reports the configured chat and embedding models, their local
  Ollama capabilities, runner, quantization and context length, and (with `--probe`) makes one schema-constrained
  call through the production adapter. Exit code 1 when a model is unusable.
- `/health/dependencies` includes the active LLM's details; `/api/v1/system/overview` has an `inference` block
  (provider, model, think, ctx, temperature, embedding model and dimensions). The web UI renders these everywhere it
  previously hard-coded "Qwen3 8B".
- The chat adapter no longer retries non-retryable responses (404 model not pulled, 501 structured output
  unavailable), so a wrong model fails in seconds with the server's message.

### Compatibility check (Ollama 0.40.14, Apple Silicon, 24 GB)

The agent needs JSON-schema structured output (`format`). MCP tools are called by code, not by model tool-calling,
so model `tools` support is informational.

| Tag | Build reported by Ollama | Structured output | Usable |
|---|---|---|---|
| `qwen3:8b` | GGUF Q4_K_M, llama.cpp, 8.2B | ✅ probe passed | ✅ baseline |
| `qwen3.5:9b` (default tag) | **safetensors nvfp4, MLX runner**, 9.7B | ❌ HTTP 501 `structured output is unavailable` (plain chat works) | ❌ |
| `qwen3.5:9b-q4_K_M` | GGUF Q4_K_M, llama.cpp, 9.0B | ✅ probe passed | ✅ compared below |
| `gpt-oss:20b` | not pulled | — | not needed: the first comparison was conclusive |

On this Mac the default `qwen3.5:9b` tag resolves to an MLX build. Use the explicit GGUF tag
`qwen3.5:9b-q4_K_M`, which is also the same quantization family as the `qwen3:8b` baseline.

## 3. Comparison

Equivalent conditions for every run: same commit per column pair, same prompts, knowledge base, tools, scenario
seeds, temperature 0, `num_ctx` 8192, `think=false`, one trial per scenario plus the INC-001 rejection path. "Before"
is the unchanged v0.3.0 agent; "after" is this branch (section 4). The qwen3.5 "after" run was repeated and gave
identical outcomes, plans and scores (`qwen3.5-9b-after-repeat/`).

| Metric (6 scenarios) | qwen3:8b before | qwen3:8b after | qwen3.5:9b before | qwen3.5:9b after |
|---|---|---|---|---|
| **System** outcome correct (gated workflow) | 6/6 | 6/6 | 2/6 | **6/6** |
| Root cause correct (determinable cases) | 3/4 | 4/4 | 4/4 | 4/4 |
| **Raw** model plan acceptable | 2/6 | 1/6 | 2/6 | **6/6** |
| Raw steps the gates had to reject | 5 | 8 | 6 | **0** |
| Model itself abstained / escalated on NEG-001…003 | 0/3 | 1/3 | 0/3 | **3/3** |
| Model's `impact_ongoing` agrees with evidence | 1/6 | 6/6 | 5/6 | 5/6 |
| Citation violations (invented evidence IDs) | 0 | 0 | 0 | 0 |
| Schema retries / LLM failures | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 0 |
| Unsafe or forbidden actions executed | 0 | 0 | 0 | 0 |
| Mean RCA call (s) | 28.1 | 42.2 | 36.1 | 24.5 / 40.3 (repeat) |
| Mean end-to-end per scenario (s) | 34.2 | 48.7 | 42.0 | 30.8 / 49.2 (repeat) |
| Loaded size at ctx 8192 (`ollama ps`) | 5.6 GB | 5.6 GB | 4.9 GB | 4.9 GB |
| Disk | 5.2 GB | | 6.6 GB | |

Latency is noisy on a shared laptop: the identical qwen3.5 repeat was 65 % slower because the test suite ran beside
it, and the qwen3:8b "after" run followed a model swap. The longer v0.4 prompt adds a few seconds per RCA call.
Treat the two models as similar in speed. Either leaves roughly 17 GB free on a 24 GB Mac next to the embedding
model.

### Per scenario, after

| Scenario | qwen3:8b raw plan → system | qwen3.5:9b raw plan → system |
|---|---|---|
| INC-001 schema migration | rollback + spurious quarantine (blocked) → mitigated | rollback → mitigated |
| INC-002 pool exhaustion | rollback + pool increase + quarantine (both blocked) → mitigated | rollback → mitigated |
| INC-003 poison messages | pause → rollback → quarantine (resume appended by policy) → mitigated ¹ | rollback → quarantine → mitigated |
| NEG-001 recovered blip | no plan, `no_action_needed` → no_action_required | no plan, `no_action_needed` → no_action_required |
| NEG-002 external FX provider | correct cause (0.8) but pause + quarantine proposed (blocked) → proposal_blocked | correct cause (0.98), no plan, escalate to `vendor:fx-provider` → escalated |
| NEG-003 ambiguous + logs down | 0.7 confidence, pause + rollback + quarantine (blocked) → proposal_blocked | 0.65 confidence, 2 evidence gaps, no plan, escalate → escalated |

¹ The existing scorer requires the model itself to resume a paused consumer, so this raw plan counts as not
acceptable, although the prompt now tells the model that the system appends the resume (policy D27).

### What separates the models

- **qwen3.5:9b follows the decision procedure.** Given the same facts it abstains on a recovered incident,
  escalates an external dependency and escalates ambiguity, with no gate needed. Its hypotheses are calibrated
  (rivals at 0.0–0.25 next to a 0.95–1.0 leader).
- **qwen3:8b improved in diagnosis but not in plan discipline.** It now reads impact correctly (6/6) and finds the
  NEG-002 cause, but it still tends to attach queue or capacity steps to any plan; the gates remove them.
- **Before the changes, qwen3.5 failed differently**: it set `escalation.required=true` to mean "urgent" while
  proposing the right rollback, which the (unchanged) uncertainty policy correctly treats as "withhold". It also
  read a past postmortem as current evidence in NEG-001.

## 4. Improvements made (agent side only; no safety gate changed)

1. **Deterministic evidence digest** (`packages/agents/opspilot_agents/synthesis.py`): the RCA prompt now opens
   with `investigation_facts.key_findings` — impact already ended; no change correlates; the errors name an unhealthy
   dependency that did not change (and whether it is external); two changes are similarly correlated; an evidence
   source could not be read; queue state and dead-letter residue. Facts are computed from the same evidence, with
   thresholds imported from `remediation.py`, and sit inside the untrusted `<evidence>` block.
2. **Explicit decision before the plan**: `RcaOutput.decision` (remediate / no_action_needed / escalate) is generated
   before `remediation_plan`, with a short ordered decision procedure, a definition of confidence as a shared
   probability, and `escalation.required` defined as "hand over instead of a plan", never urgency.
3. **Decode-time identifier constraints** (`prompts.rca_schema`): per investigation, cited evidence IDs and plan
   `deployment_id` / `service` / `queue` / `error_code` are JSON-schema enums over observed values. Ollama enforces
   them while decoding (verified live). This removed fabricated IDs seen during iteration
   (`dep-ledger-service-2.9.1`, `ev-error-attribution`, `ev-key_findings-1`). Citation filtering and the gates still
   run behind it; the test fake deliberately bypasses the constraint so those checks stay tested.
4. **Plan rules**: historical incidents are patterns, not current evidence; no `resume_consumer` (the policy adds
   it); no restart or pool increase as a fallback next to a rollback; recovery when the facts show residue.
5. **Tool / model compatibility**: `opspilot models --probe`, fail-fast on non-retryable Ollama errors.

### Iterations (for transparency)

Six prompt revisions were run; intermediate traces are not kept in the repository. Small models reacted unevenly to
wording: an early revision that described the full containment → resolution → recovery order made qwen3:8b propose
`resume_consumer` on a running consumer (NEG-002) and a leftover `restart_service` (NEG-003) that the gates let
through (see section 5); later revisions removed that wording. Raw-plan acceptability for qwen3:8b ranged 1/6–3/6
across revisions and never matched qwen3.5's 4/6–6/6.

## 5. Findings for the owner (not changed here)

The brief kept the safety policies unchanged. Two pre-existing gaps in the plan gates surfaced when a revision
produced more multi-step plans (the evaluation approves every step):

1. `resume_consumer` is admitted for a consumer that is already running (the gate only checks that the service is
   a consumer). In the simulator the action fails with "no effect" (`remediation_failed`), but the gate should not
   admit it.
2. A containment step (`restart_service` on a service that is abnormal) is admitted even when the plan's resolution
   step was rejected as ambiguous; NEG-003 executed a restart. D25/D27 assume containment is paired with a resolution.

Both are reproducible with `qwen3:8b` and the r1/r2 prompt wording and would be closed by two small rules in
`remediation.py`/`enforce_plan_shape`. They need an owner decision because they change safety policy.

## 6. Recommendation

Use **`qwen3.5:9b-q4_K_M`** as the default investigation model on Apple Silicon with Ollama 0.40.x: correct system
outcome 6/6, raw plan acceptable 6/6, zero gate interventions, self-abstention on all three negative scenarios,
similar latency and 0.7 GB less loaded memory than `qwen3:8b` (1.4 GB more disk). Keep `qwen3:8b` as the supported baseline: with the v0.4
prompt it is still correct end to end 6/6, but only because the gates remove its extra steps.

Caveats: six self-authored scenarios, one trial at temperature 0 (a repeat was identical), and the prompt was
iterated on these same scenarios, so these are development results, not an unbiased estimate. The safety gates and
human approval remain the controls that make outcomes safe, whatever model is configured.
