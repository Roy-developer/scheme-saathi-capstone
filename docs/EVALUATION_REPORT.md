# Scheme Saathi — Evaluation report (foundation draft)

**Status:** Role 5 foundation (scope 1A) plus Reflexion E3 inventory against playbook `1.0.0`.
This is not the final 4–6 page held-out report.
**Dataset:** `eval/development/personas_v1.json` (31 synthetic boundary personas across IGNWPS-MH, PM-KISAN-IN, IGNOAPS-MH).
**Scorer:** deterministic `evaluate_mock_eligibility` only (no LLM judge).
**Reflexion:** committed playbook `data/schemes/playbooks/1.0.0.json` verified; paid before/after extraction runs still pending.

## 1. Scope and limits

What this draft covers:

- Code-first scoring of development personas for `IGNWPS-MH` and `PM-KISAN-IN`
- Starter red-team stubs (`eval/red_team/attacks_v0.json`, 9 attacks, not executed)
- Prometheus metric emission at `GET /metrics` (no Grafana yet)

What this draft does **not** claim:

- ≥40 protected held-out personas
- Dual independent labelling (Role 1 review pending)
- Simulated citizen or different-family LLM judge / Cohen's κ
- Live E1–E4 experiments or three held-out repeats
- Full 30+ red-team execution with defences off/on
- Compose, Grafana dashboards, CI evaluation gate, or can't-tell alert

## 2. Development harness results

Regenerate with:

```bash
python scripts/evaluate_eligibility_dev.py --output eval/reports/eligibility_dev_latest.json
```

Latest offline run (`scripts/evaluate_eligibility_dev.py`, after IGNOAPS personas):

| Metric | Value |
|---|---|
| Personas | 31 |
| Cases (persona × scheme) | 31 |
| Correct | 31 |
| Incorrect | 0 |
| Accuracy | 1.0 |
| Missing-field mismatches | 0 |
| IGNWPS-MH | 13/13 (1.0) |
| PM-KISAN-IN | 12/12 (1.0) |
| IGNOAPS-MH | 6/6 (1.0) |

Per-persona detail: regenerate `eval/reports/eligibility_dev_latest.json` (gitignored).

### Reflexion playbook inventory

| Item | Value |
|---|---|
| Playbook | `1.0.0` |
| Approved lessons | 1 (`exclusion_clause`) |
| Reviewer | `Roy-developer` |
| Check-split cases | see `python scripts/evaluate_reflexion_playbook_dev.py` |
| Paid E3 before/after | **pending** (needs OpenRouter `--yes`) |

## 3. Protocol notes

- Expected outcomes were authored before scoring.
- UI fixture alias `cant_tell` normalizes to engine `need_more_information`.
- In-repo harness **rejects** `protected: true` / non-development sets.
- Held-out storage: see `eval/held_out/README.md` (policy only; no cases committed).

## 4. Experiments (config stubs only)

| ID | Intent | Status |
|---|---|---|
| E1 | C0 / C1 / C2 cost-benefit | `eval/experiments/e1_agent_cost.json` — not runnable |
| E2 | Defences off/on | `eval/experiments/e2_defences.json` — not runnable |
| E3 | Playbook before/after | Playbook `1.0.0` ready; inventory free; paid `scheme_rules evaluate` still pending |
| E4 | LLM vs rules; planned vs fixed questions | `eval/experiments/e4_signature_ablation.json` — rule-engine side partially covered by this harness |

## 5. Monitoring

Emitted Prometheus series (scrapable at `/metrics`):

- `scheme_saathi_conversations_total`
- `scheme_saathi_evaluations_total`
- `scheme_saathi_verdicts_total`
- `scheme_saathi_questions_total`
- `scheme_saathi_masked_id_hits_total`
- `scheme_saathi_request_latency_seconds`

Dashboards, alerts, and Compose wiring remain Role 6.

## 6. Next Role 5 work

1. Dual-label development personas with Role 1; expand toward 60 with held-out elsewhere.
2. Grow red-team suite to 30+ and execute E2 in isolation.
3. Calibrate a different-family judge; report κ.
4. Run E1–E4 after Phase 5 freeze; three held-out repeats; finalize this report.
