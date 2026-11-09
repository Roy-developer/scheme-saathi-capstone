# Evaluation (Role 5)

This folder holds the **evaluation and monitoring foundation** for Scheme Saathi.

## Ownership

| Area | Owner |
|---|---|
| Personas, harness, red-team stubs, experiment configs, evaluation report | Role 5 |
| Prometheus scrape target (`GET /metrics`) emission | Role 5 (instrumentation) |
| Grafana dashboards, Compose, alerts, CI eval gate | Role 6 (later) |

## Layout

```text
eval/
  development/     # unprotected development personas (~20–30 now; grow toward 60)
  held_out/        # policy only — do not commit protected cases here
  red_team/        # attack stubs (full 30+ suite is a later pass)
  experiments/     # E1–E4 config placeholders (not yet runnable end-to-end)
  harness/         # code-first offline scorer
  schema.py        # Pydantic models
  reports/         # generated JSON (gitignored)
```

## Honest-results rules

- The person tuning agents must not write held-out cases.
- The person building defences must not write the final attacks.
- Role 1 checks held-out cases against written policy.
- Gold answers must never enter prompts or agent-facing tools.
- If held-out results are seen and then used to change the system, reclassify those cases as development and disclose it.

## Run the development harness

From the repository root (with the project virtualenv active):

```bash
python scripts/evaluate_eligibility_dev.py
python scripts/evaluate_eligibility_dev.py --scheme IGNWPS-MH --output eval/reports/dev_latest.json
python scripts/evaluate_eligibility_dev.py --scheme IGNOAPS-MH
```

The harness calls `evaluate_mock_eligibility` only (no LLM). It rejects protected or non-development sets. IGNOAPS personas use `typed_facts` (including `name_on_bpl_list`).

## Reflexion playbook (E3)

Frozen playbook: `data/schemes/playbooks/1.0.0.json` (one approved `exclusion_clause` lesson).

```bash
# Free: verify playbook + list check-split cases
python scripts/evaluate_reflexion_playbook_dev.py

# Paid (OpenRouter): before / after playbook on development check cases
python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --runs 3 --yes
python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --playbook 1.0.0 --runs 3 --yes
```

The current lesson targets exclusion clauses. Inclusion check cases (IGNWPS / IGNOAPS) will not retrieve it; E3 gains are expected mainly on PM-KISAN exclusion `check` clauses.

## Deferred (not claimed complete)

- ≥40 protected held-out personas in Role-5-only storage
- Simulated citizen + different-family LLM judge + Cohen's κ
- Live E1–E4 runs and three held-out repeats
- Full 30+ red-team execution against defences
- Grafana / Compose / CI threshold / can't-tell alert
