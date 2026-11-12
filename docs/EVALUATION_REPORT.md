# Scheme Saathi — Evaluation report (Role 5 / PDF L13–L15)

**Status:** In-repo Role 5 suite expanded toward the PDF bar and gated in CI.
This is still **not** the final frozen held-out submission report until dual
labels, paid E3, live memory/approval attacks, and three held-out repeats are
complete with Role 1.

**How to regenerate development evidence:**

```bash
python scripts/run_role5_dev_evals.py
```

## 1. PDF checklist

| PDF requirement | In-repo status |
|---|---|
| 60+ synthetic personas (~20 dev / ≥40 held-out) | Dev: 43 in `eval/development/` (12 APY); held-out: generate ≥40 into gitignored `eval/held_out/local/` only after freeze |
| Dual independent labels + κ | κ harness ready; smoke uses copied labels — **Role 1 must replace** |
| Simulated citizen (hidden profile) | `eval/harness/simulated_citizen.py` offline stand-in |
| Code-first eligibility scoring | `evaluate_eligibility_dev.py` / held-out script |
| E1 cost-benefit | Config inventoried; live C0/C1/C2 still blocked on Phase freeze |
| E2 defences off/on | **Offline runnable** for injection / ID / scam + clean-case false-block rate; scam screen also on live intake/journey (see §3) |
| E3 Reflexion before/after | Playbook inventory free; **paid** OpenRouter runs pending |
| E4 signature ablation | Rule-engine side via personas; LLM/question ablations pending |
| 30+ red-team | 30 attacks; 23 offline-runnable; memory/approval still stubs |
| L9 memory | Synthetic prototype controls and focused evidence: [`docs/MEMORY_POLICY.md`](MEMORY_POLICY.md), [`tests/test_household_memory.py`](../tests/test_household_memory.py), [`tests/test_journey_graph.py`](../tests/test_journey_graph.py), and [`tests/test_household_memory_api.py`](../tests/test_household_memory_api.py). R1/R2 approval, checkpoint-level retention, cross-household attacks, and verdict-agreement/memory-on-off reporting remain pending. |
| Monitoring / Grafana / alert | Read-only shared-dev query confirms OpenTelemetry metrics from the older `git-13dde6b37e3a` image; current-commit Prometheus, dashboard, and alert proof remain incomplete. |
| CI evaluation gate | Frontend checks runs `run_role5_dev_evals.py` |
| Three held-out repeats | Pending after freeze |

## 2. Development harness results

| Metric | Value |
|---|---|
| Personas | 43 (dataset version 1.2.0) |
| Accuracy | 1.0 (43/43; local development run on 2026-11-12) |
| Schemes | APY-IN, IGNWPS-MH, PM-KISAN-IN, IGNOAPS-MH |

### Memory on/off smoke

[`eval/reports/memory_on_off_dev_latest.json`](../eval/reports/memory_on_off_dev_latest.json)
is a one-case deterministic smoke: both paths reached the same eligibility
verdict, consented memory reused two approved facts, and one question was
avoided. It is not independent validation or full L9 evidence. Regenerate it
with `python scripts/run_role5_dev_evals.py` or
`python scripts/evaluate_household_memory_dev.py`.

## 3. Red-team / E2

```bash
python scripts/evaluate_red_team_dev.py
python scripts/evaluate_e2_defences_dev.py
```

Offline E2 reports attack success with defences **off** vs **on** for injection,
identifier masking, and scam screens (`src/workflow/scam_screen.py`), plus a
**legitimate-work false-block rate** for clean messages (bare UPI / WhatsApp
mentions without fee/OTP lures).

**Live wiring:** the same contextual `screen_scam_text` / `apply_scam_screen`
helper runs on intake free-text descriptions and journey interview replies.
Flagged description text is **not** turned into proposed facts; flagged
replies are rejected with a citizen warning and a `scam_screened` discovery
notice. Guardrail metric: `scheme_saathi_guardrail_blocks_total{guardrail="scam_screen"}`.

**Pattern policy:** UPI / WhatsApp only match with pay/fee/approval/OTP-style
context, so “I get my pension by UPI” stays clean while
“Message WhatsApp and pay ₹200 for fast approval” still flags.

## 4. Held-out (Role-5-only)

```bash
python scripts/generate_held_out_personas.py
python scripts/evaluate_eligibility_held_out.py
```

Do not commit `eval/held_out/local/`. Do not tune against held-out results.

## 5. Label agreement (κ)

```bash
python scripts/evaluate_label_agreement_dev.py
```

Smoke κ uses a copied second labeller. Independent Role 1 labels are required
for the PDF claim (20+ human-calibration labels for an LLM judge if used).

## 6. Reflexion E3

```bash
python scripts/evaluate_reflexion_playbook_dev.py
# paid:
python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --runs 3 --yes
python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --playbook 1.0.0 --runs 3 --yes
```

## 7. Monitoring

Emitted at `GET /metrics` (Prometheus) and through OpenTelemetry instruments
(Azure Monitor export is enabled only when configured):

- `scheme_saathi_conversations_total`
- `scheme_saathi_evaluations_total`
- `scheme_saathi_verdicts_total`
- `scheme_saathi_questions_total`
- `scheme_saathi_masked_id_hits_total`
- `scheme_saathi_request_latency_seconds`

Role 6 handoff: verify the configured Azure Monitor exporter or scrape
`monitoring/prometheus.yml`, then demonstrate the alert and dashboard using the
definitions under `monitoring/`. Configuration alone is not deployment evidence.

## 8. Still required for a full PDF claim

1. Role 1 dual-labels held-out (and preferably development) independently.
2. Paid E3 before/after + report deltas.
3. Live E1 / E4 after agent freeze; three held-out repeats with spread.
4. Live red-team for cross-household memory and approval-gate cases with independent authorship.
5. Different-family LLM judge calibrated on 20+ human labels (if non-code qualities are judged).
6. Role 6 proves the deployed metrics reach the shared monitoring environment and demonstrates a working alert.
