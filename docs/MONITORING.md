# Monitoring (Role 5 → Role 6)

Implements the L13/L16 monitoring bar from the Monitoring & Evaluation guide:
Prometheus counters on FastAPI, five Grafana panel definitions, and one working
alert rule. **No Docker Compose** — local proof is `GET /metrics`; production
dashboards use Azure Managed Grafana or a separate Container App.

## Metrics (`GET /metrics`)

| Guide panel | Metric |
|---|---|
| Questions | `scheme_saathi_questions_total` |
| Can't-tell rate | `scheme_saathi_verdicts_total{result="need_more_information"}` |
| Pending approvals | `scheme_saathi_pending_approvals` |
| Masked-ID hits | `scheme_saathi_masked_id_hits_total{field_type=...}` |
| Cost | `scheme_saathi_cost_usd` |
| (+ latency / tokens / guardrails) | `scheme_saathi_request_latency_seconds`, `scheme_saathi_llm_call_seconds`, `scheme_saathi_tokens_total`, `scheme_saathi_guardrail_blocks_total` |

Verdict label `cant_tell` is normalized to `need_more_information` (engine name).

## Security note

`GET /metrics` is **intentionally unauthenticated** for local demos and internal
scrapes. Anyone who can reach the BE URL can read counters (traffic shape, scheme
IDs, rough cost). That is fine for a shared-lab demo; for a public ingress, put
`/metrics` behind auth, an IP allowlist, or an internal-only route before go-live.

## Local proof (no Compose)

```bash
source .venv/bin/activate
python -m uvicorn src.api.app:app --reload --port 8000
curl -s http://127.0.0.1:8000/metrics | grep scheme_saathi
```

## Azure deploy (recommended)

1. Keep metrics emission on the **BE Container App** only (`/metrics`).
2. Point **Azure Managed Grafana** (or a separate Grafana/Prometheus Container App)
   at that scrape URL — do **not** bake Grafana into the shared FE/BE app image.
3. Import dashboard JSON from `monitoring/grafana/dashboards/scheme_saathi_overview.json`.
4. Apply alert logic from `monitoring/alerts.yml` (`HighCantTellRate`: need_more_information
   rate > 20% for 5 minutes) in Azure Monitor / Grafana alerts.

Reference scrape config (for a standalone Prometheus if used):
`monitoring/prometheus.yml` — set the target to your BE hostname, not Compose.

## Cost estimate

USD histogram uses env defaults (override as needed):

- `SCHEME_SAATHI_COST_INPUT_USD_PER_1K` (default `0.00015`)
- `SCHEME_SAATHI_COST_OUTPUT_USD_PER_1K` (default `0.0006`)

## Readiness (honest)

**Safe now:** scrape BE `GET /metrics` for a demo dashboard (questions, latency,
some verdicts / masked IDs / agent tokens will move with live traffic).

**Do not trust yet as production signals:**

| Signal | Why |
|---|---|
| `HighCantTellRate` | Journey re-counts accumulated `eligibility_results` on every turn → rate can skew |
| Pending approvals gauge | In-memory per process; wrong across Azure replicas / restarts; not DB-backed |
| Cost / tokens / LLM latency | Estimate only; helper LLM paths (`run_accounted_model_call`, intake structured asks) not fully counted; agent `PIIMiddleware` redactions do not increment masked-ID hits |
| Guardrail blocks | Injection + scam screens on live intake/journey; scam patterns are contextual (still expand coverage / UX as attacks grow) |
| Conversation duration | Guide metric not implemented |

**Before claiming monitoring complete:** (1) record journey verdicts once per new
result, (2) pending count from portal truth or single lifecycle, (3) tokens/latency
on helper LLM calls, (4) wire Azure scrape + alert manually, (5) restrict `/metrics`
if the BE ingress is public.
