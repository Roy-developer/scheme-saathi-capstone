# Monitoring (Role 5 -> Role 6)

The API keeps the Prometheus endpoint and additionally exports the same
instrumentation through OpenTelemetry. Azure Monitor export is enabled only
when `APPLICATIONINSIGHTS_CONNECTION_STRING` is configured. This preserves the
local scrape path while allowing the OpenTelemetry implementation from
`feature/monitoring-otel-on-supervisor` to be used in Azure.

## Metrics

`GET /metrics` exposes the Prometheus series used by the local dashboard:

| Guide panel | Prometheus metric |
|---|---|
| Questions | `scheme_saathi_questions_total` |
| Can't-tell rate | `scheme_saathi_verdicts_total{result="need_more_information"}` |
| Pending approvals | `scheme_saathi_pending_approvals` |
| Masked-ID hits | `scheme_saathi_masked_id_hits_total{field_type=...}` |
| Cost | `scheme_saathi_cost_usd` |
| Latency, tokens, guardrails | `scheme_saathi_request_latency_seconds`, `scheme_saathi_llm_call_seconds`, `scheme_saathi_tokens_total`, `scheme_saathi_guardrail_blocks_total` |

OpenTelemetry instruments use the `scheme_saathi.*` namespace for those same
signals, including conversations, evaluations, verdicts, questions, masked IDs,
pending approvals, cost, tokens, LLM/request latency, and guardrail blocks.
Verdict `cant_tell` is normalized to `need_more_information`.

## Local proof

```bash
python -m uvicorn src.api.app:app --reload --port 8000
curl -s http://127.0.0.1:8000/metrics
```

Without an Application Insights connection string, OpenTelemetry recording is
backend-free; the Prometheus endpoint remains available for local checks.

## Azure handoff

1. Store `APPLICATIONINSIGHTS_CONNECTION_STRING` in the deployment secret store;
   never commit it or put it in a report.
2. Verify the API exports metrics to the intended Application Insights resource
   and capture a sanitized query/result as deployment evidence.
3. If using Prometheus/Grafana instead, point the scraper at the API's
   `/metrics` route and use the dashboard and alert definitions under `monitoring/`.
4. Do not bake Grafana into the shared FE/BE app image.

The OpenTelemetry exporter being configured in code is not proof of an Azure
export, dashboard, scrape, or alert in the shared environment.

## Cost estimate

USD histogram uses environment defaults (override as needed):

- `SCHEME_SAATHI_COST_INPUT_USD_PER_1K` (default `0.00015`)
- `SCHEME_SAATHI_COST_OUTPUT_USD_PER_1K` (default `0.0006`)

## Readiness

**Implemented locally:** Prometheus scrape endpoint, existing dashboards/alert
definitions, OpenTelemetry instruments, and opt-in Azure Monitor exporter.

**Still needs live evidence or follow-up:**

| Signal / gate | Remaining work |
|---|---|
| Journey verdict rate | Journey can re-count accumulated `eligibility_results` on each turn |
| Pending approvals | Prometheus gauge is per process and not backed by portal truth across replicas/restarts |
| Cost / tokens / LLM latency | Estimates; helper LLM paths are not fully counted, and agent `PIIMiddleware` redactions do not increment masked-ID hits |
| Guardrail blocks | Injection and scam screens are instrumented; attack coverage and UX remain evaluation work |
| Azure Monitor | Configure the secret in the shared environment and prove data arrives |
| Alert / dashboard | Demonstrate a working shared-environment alert or scrape; configuration files alone are not proof |
| Public ingress | Restrict `/metrics` if it is reachable outside trusted internal networks |
