# Monitoring (Role 5 -> Role 6)

The API emits all instrumentation through OpenTelemetry. Azure Monitor export
(Application Insights) is enabled only when `APPLICATIONINSIGHTS_CONNECTION_STRING`
is configured. Managed Grafana reads from Azure Monitor.

## Metrics

OpenTelemetry instruments use the `scheme_saathi.*` namespace:

| Guide panel | OTel instrument |
|---|---|
| Questions | `scheme_saathi.questions` |
| Can't-tell rate | `scheme_saathi.verdicts` with `result="need_more_information"` |
| Pending approvals | `scheme_saathi.pending_approvals` |
| Masked-ID hits | `scheme_saathi.masked_id_hits` with `field_type=...` |
| Cost | `scheme_saathi.cost_usd` |
| Latency, tokens, guardrails | `scheme_saathi.request_latency`, `scheme_saathi.llm_call_duration`, `scheme_saathi.tokens`, `scheme_saathi.guardrail_blocks` |

Also emitted: `scheme_saathi.conversations` and `scheme_saathi.evaluations`.
Verdict `cant_tell` is normalized to `need_more_information`.

## Local proof

Without an Application Insights connection string, recording is backend-free
and no metrics leave the process. To check emission locally, use the in-memory
reader in `tests/test_observability_metrics.py`:

```bash
python -m pytest -q tests/test_observability_metrics.py
```

## Azure handoff

1. Store `APPLICATIONINSIGHTS_CONNECTION_STRING` in the deployment secret store;
   never commit it or put it in a report.
2. Verify the API exports metrics to the intended Application Insights resource
   and capture a sanitized query/result as deployment evidence.
3. Build the Managed Grafana dashboards and alerts against Azure Monitor /
   Application Insights data.
4. Do not bake Grafana into the shared FE/BE app image.

The OpenTelemetry exporter being configured in code is not proof of an Azure
export, dashboard, or alert in the shared environment.

## Shared development spot check (2026-11-12)

A read-only check of the shared development environment found:

- The API health endpoint returned HTTP 200 and the container app references an
  Application Insights connection-string setting.
- The running image is `git-13dde6b37e3a`, not the current
  `supervisor-redesign-3` commit. A sanitized `AppMetrics` query over the last
  24 hours returned `scheme_saathi.conversations`,
  `scheme_saathi.request_latency`, `scheme_saathi.questions`,
  `scheme_saathi.evaluations`, and `scheme_saathi.verdicts`. The query grouped
  only by metric name and did not read dimensions or applicant data.
- No Azure metric alert rules were configured. A Grafana resource exists, but
  its dashboard contents and alert behavior were not verified.

This confirms some telemetry from the older shared-dev image only. It does not
complete the current-commit, dashboard, or alert proof.

## Cost estimate

USD histogram uses environment defaults (override as needed):

- `SCHEME_SAATHI_COST_INPUT_USD_PER_1K` (default `0.00015`)
- `SCHEME_SAATHI_COST_OUTPUT_USD_PER_1K` (default `0.0006`)

## Readiness

**Implemented locally:** OpenTelemetry instruments and opt-in Azure Monitor exporter.

**Still needs live evidence or follow-up:**

| Signal / gate | Remaining work |
|---|---|
| Journey verdict rate | Journey can re-count accumulated `eligibility_results` on each turn |
| Pending approvals | Up/down counter is tracked per process and not backed by portal truth across replicas/restarts |
| Cost / tokens / LLM latency | Estimates; helper LLM paths are not fully counted, and agent `PIIMiddleware` redactions do not increment masked-ID hits |
| Guardrail blocks | Injection and scam screens are instrumented; attack coverage and UX remain evaluation work |
| Azure Monitor | Configure the secret in the shared environment and prove data arrives |
| Managed Grafana | Build and prove dashboards and alerts against Azure Monitor data; configuration files alone are not proof |
