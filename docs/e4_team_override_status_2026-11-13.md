# E4 team-override status (2026-11-13)

Tracks Scheme Saathi signature ablation beyond a PDF ≥40 unseen held-out bar.

## Team override (2026-11-13)

**Decision:** Do **not** require ≥40 unseen held-out personas for this E4 record.
Use the **development persona set** (`eval/development/personas_v1.json`,
currently **46** persona×scheme cases).

| Field | Value |
|---|---|
| Bar | `team_override_dev_personas` |
| Case file | `eval/development/personas_v1.json` |
| Claim level | **Team override — not PDF unseen held-out** |
| Dual labels / simulated citizen | Waived for this override; gold = persona `expected_by_scheme` |
| Go-ahead | Team-override E4 signature ablation is **authorised** (free-model / recorded budget; still not a PDF ≥40 unseen claim) |

## Checklist

| # | Item | Status |
|---|---|---|
| 1 | Isolated non-authoritative LLM arm | **Done** (`eval/harness/e4_llm_arm.py`) |
| 2 | Shadow stub + offline rule/picker Q-order | **Done** |
| 2b | Journey-facing planned vs fixed Q-order | **Done** — interview graph + simulated citizen; 46/46 same verdicts (fixed 159 vs planned 157 questions) |
| 3 | Full LLM-arm under freeze (team override) | **Done** — 46/46 scored, 138 calls, 0 provider errors |
| 4 | Multilingual verdict agreement (en/hi/mr) | **Done** — 32/46 all-three agree (rate 0.6957) |
| 5 | Cost-per-case | **Done** — free route $0.00 / case (`cost_per_case_usd`) |
| — | PDF ≥40 unseen held-out | **Explicitly waived** by team override |
| — | Recorded report | `eval/reports/e4_team_override_signature_ablation_2026-11-13.json` |

## Commands

```bash
python scripts/evaluate_e4_signature_ablation.py --team-override --dry-run
python scripts/evaluate_e4_signature_ablation.py --team-override --llm-arm --multilingual --yes
# Journey Q-order is on by default; skip with --no-journey-question-order
```

## Go-ahead log

| When | Who | Decision |
|---|---|---|
| 2026-11-13 | Role 5 / team (chat override) | Team-override E4 signature ablation is **authorised**. Waives ≥40 unseen persona bar. Results must be labelled team-override, not PDF held-out. |

## What must not be done

- Call this run a **PDF unseen held-out** result.
- Write LLM proposals into live journey state or treat them as authority.
- Tune from held-out custody sets under this override.
