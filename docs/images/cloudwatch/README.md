# AWS CloudWatch screenshots (v0.11, unreleased) — synthetic fixture data

These screenshots were captured by the Playwright journeys in `apps/web/e2e/cloudwatch.spec.ts` on the isolated E2E
stack (`opspilot_test`, API 8100, web 3100), with `E2E_CLOUDWATCH=1` (the synthetic protocol fixture
`scripts/cloudwatch_fixture.py` on 127.0.0.1:8133, reached through the real AWS SDK with synthetic keys) and the real
local model (`qwen3.5:9b-q4_K_M`) for the analysis.

**Everything shown is fictional, synthetic fixture data** (account 111122223333, region us-east-1). No AWS account,
profile, role or endpoint was contacted. These images show the implementation working against the fixture; they are
**not** evidence of verification against a real AWS account.

| File | Shows |
|---|---|
| `cloudwatch-integrations.png` | Integrations catalogue: AWS CloudWatch provider, connection test with account, per-signal and per-log-group results (readable / access denied / not found), IAM actions, *Synthetic fixture* label |
| `cloudwatch-connection.png` | Connected intake: CloudWatch card after a connection test (partly readable: one log group missing, one denied), approved templates, cost note |
| `cloudwatch-invalid-credentials.png` | Connection status for expired temporary credentials; intercepted response |
| `cloudwatch-insufficient-permissions.png` | Connection status for missing IAM permissions, per log group; intercepted response |
| `cloudwatch-preview.png` | Evidence preview: per-query provenance (log groups, Logs Insights query ID, status, polls, scan statistics), "not queried (no mapping)" rows, sample records with source references, returned metric series |
| `cloudwatch-preview-metrics.png` | Metric records with `cloudwatch/<template>/<service>:point N` sources |
| `cloudwatch-analysis.png` | Investigation workbench: read-only analysis of the CloudWatch snapshot and the cited RCA report |
| `cloudwatch-mobile-intake.png` | Connected intake at 390 px width with the CloudWatch fixture incident |
