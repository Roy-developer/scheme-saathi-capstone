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
| 60+ synthetic personas (~20 dev / ≥40 held-out) | Dev: 31 in `eval/development/`. Held-out: generate ≥40 into gitignored `eval/held_out/local/` |
| Dual independent labels + κ | κ harness ready; smoke uses copied labels — **Role 1 must replace** |
| Simulated citizen (hidden profile) | `eval/harness/simulated_citizen.py` offline stand-in |
| Code-first eligibility scoring | `evaluate_eligibility_dev.py` / held-out script |
| E1 cost-benefit | Config inventoried; live C0/C1/C2 still blocked on Phase freeze |
| E2 defences off/on | **Offline runnable** for injection / ID / scam — scam helper is **not** on the live journey yet (see §3) |
| E3 Reflexion before/after | Playbook inventory free; **paid** OpenRouter runs pending |
| E4 signature ablation | Rule-engine side via personas; LLM/question ablations pending |
| 30+ red-team | 30 attacks; 23 offline-runnable; memory/approval still stubs |
| Monitoring / Grafana / alert | `/metrics` + `monitoring/` JSON/rules for Azure Managed Grafana or separate Container App |
| CI evaluation gate | Frontend checks runs `run_role5_dev_evals.py` |
| Three held-out repeats | Pending after freeze |

## 2. Development harness results

| Metric | Value |
|---|---|
| Personas | 31 |
| Accuracy | 1.0 (regenerate with umbrella script) |
| Schemes | IGNWPS-MH, PM-KISAN-IN, IGNOAPS-MH |

## 3. Red-team / E2

```bash
python scripts/evaluate_red_team_dev.py
python scripts/evaluate_e2_defences_dev.py
```

Offline E2 reports attack success with defences **off** vs **on** for injection,
identifier masking, and scam screens (`src/workflow/scam_screen.py`).

**Honest scope for the scam row:** `screen_scam_text` is called only from
`eval/harness/` and unit tests today. The live FastAPI / journey path does
**not** invoke it (unlike `screen_free_text` on intake). So E2 “defences on”
for scam attacks measures this **offline helper**, not production chat
behaviour. Injection E2 is closer to live because the intake quarantine path
still runs the injection screen.

**Why it is not wired into the journey yet:** several patterns are too broad
for citizen messages (e.g. bare `\bUPI\b` and `\bwhats?app\b` would flag
ordinary replies such as “I get my pension by UPI”). Wiring as-is would drive
a high legitimate-work false-block rate. A follow-up (tools/security or Role 5
with Role 4) should tighten patterns to fee/OTP/QR *contexts*, add clean-case
false-positive coverage to E2, then call the screen from journey/intake and
`record_guardrail_block("scam_screen", …)`. Until then, treat scam E2 as a
unit-level defence probe, not a live-app claim.

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

Emitted at `GET /metrics`:

- `scheme_saathi_conversations_total`
- `scheme_saathi_evaluations_total`
- `scheme_saathi_verdicts_total`
- `scheme_saathi_questions_total`
- `scheme_saathi_masked_id_hits_total`
- `scheme_saathi_request_latency_seconds`

Role 6 handoff: `monitoring/prometheus.yml`, `monitoring/alerts.yml` (can't-tell
rate alert), Grafana dashboard JSON under `monitoring/` (Azure Managed Grafana / separate Container App — no Compose).

## 8. Still required for a full PDF claim

1. Role 1 dual-labels held-out (and preferably development) independently.
2. Paid E3 before/after + report deltas.
3. Live E1 / E4 after agent freeze; three held-out repeats with spread.
4. Live red-team for cross-household memory and approval-gate cases with independent authorship.
5. Different-family LLM judge calibrated on 20+ human labels (if non-code qualities are judged).
6. Role 6 wires Compose so Prometheus/Grafana scrape the deployed API in the shared environment.
