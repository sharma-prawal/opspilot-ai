# Azure Monitor screenshots (v0.10, unreleased) — synthetic fixture data

These screenshots were captured by the Playwright journeys in `apps/web/e2e/azure.spec.ts` on the isolated E2E stack
(`opspilot_test`, API 8100, web 3100), with `E2E_AZURE=1` (the synthetic Logs API fixture
`scripts/azure_monitor_fixture.py` on 127.0.0.1:8129) and the real local model (`qwen3.5:9b-q4_K_M`) for the analysis.

**Everything shown is fictional, synthetic fixture data.** No Azure tenant, subscription or Log Analytics workspace
was contacted. These images show the implementation working against the fixture; they are **not** evidence of
verification against a real Azure workspace.

| File | Shows |
|---|---|
| `azure-integrations.png` | Integrations catalogue: Azure Monitor provider, connection test with per-signal and per-table results, *Synthetic fixture* label |
| `azure-invalid-credentials.png` | Connection status for rejected credentials (`AADSTS7000215`); intercepted response |
| `azure-insufficient-permissions.png` | Connection status for missing RBAC (*Log Analytics Data Reader*), per table; intercepted response |
| `azure-preview.png` | Evidence preview: per-query provenance, sampling and empty-bin notes, sample records with source references, returned metric series |
| `azure-preview-requests.png` | Request and dependency records (spans tab) with partial-operation and sampling markers |
| `azure-analysis.png` | Investigation workbench: read-only analysis of the Azure snapshot and the cited RCA report |
| `azure-mobile-intake.png` | Connected intake at 390 px width with the Azure fixture incident |
