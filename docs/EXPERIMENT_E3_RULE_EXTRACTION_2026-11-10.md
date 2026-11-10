# E3: did the rule-extractor lessons help? (2026-11-10)

> **Status: superseded, run 1 of E3.** After this run the 10 held-out schemes' errors were read, so they were
> relabelled development, and 8 fresh held-out schemes were added (see docs/RULE_GOLD_SET_SELECTION.md).
> 26 fields were also added to the extractor's field list. These numbers are kept as a record, not as the
> final held-out result.

## Setup
- Extractor: `scripts/extract_scheme_rules.py`, model `openai/gpt-4.1-mini`, temperature 0, same prompt and
  field list in every run. Scorer: `score_many` in `src/rules/extraction.py` (field, operator, value match).
- Gold: 15 schemes in `data/schemes/rule_gold_selection.json`; 5 development, 10 held-out.
- Playbook: `data/schemes/rule_extractor_playbook.json`, frozen 2026-11-10 before any held-out run with lessons.
  Copy: `data/schemes/rule_extracted/playbook_frozen_2026-11-10.json`.
- Lessons were written from development errors only. Approved: LESSON-001, 002, 003.
  **Rejected: LESSON-004**, reviewer's reason: "too specific to a single scheme; it is not a generalizable
  rule for the extractor."
- Runs: 3 before (no lessons, `baseline_run1-3`), 3 after (playbook, `playbook_heldout_run1-3`).
  About 75 model calls in total; cost is well under US$1 (no per-call cost logged).

## Held-out result (10 schemes, 59 gold rules)
| | Precision | Recall | F1 (mean of 3) | F1 per run |
|---|---|---|---|---|
| Before | 0.83 | 0.76 | 0.794 | 0.768, 0.807, 0.807 |
| After | 0.81 | 0.80 | 0.804 | 0.790, 0.810, 0.810 |

**Reading:** F1 rose by 0.01 and the run ranges overlap (0.77-0.81 before, 0.79-0.81 after), so this is
**not a clear improvement**. Recall rose a little, precision fell a little. After-runs were more stable.

## Per scheme (mean F1 before -> after)
| Better | Same | Worse |
|---|---|---|
| NFBSM-MH 0.48 -> 1.00, FASETDP-MH 0.96 -> 1.00, POST-DIS-IN 0.67 -> 0.71, PMJJBY-IN 0.52 -> 0.53 | IGNDPSM-MH 1.00, FADSE-MH 1.00 | IGNDPS-IN 0.94 -> 0.78, APY-IN 0.91 -> 0.80, PRE-DIS-IN 0.77 -> 0.74, PMSBY-IN 0.58 -> 0.52 |

## What changed (held-out errors read after the run, for reporting only)
- **NFBSM-MH (better):** before, the model put the breadwinner's age 18-59 on the applicant's `age`; after, it
  used `deceased_breadwinner_age` and the family-member rule. Fits **LESSON-003** (choose the field the clause states).
- **IGNDPS-IN (worse):** after, the model wrote `age gt 18` from "more than 18 years" and `disability_percent gt 80`
  from "more than 80%". Both quotes exist in the source, which conflicts with itself; the gold follows the owner's
  decision ("18 and above", "80% or more"). Likely **LESSON-002** (copy short exact phrases) made the model follow
  each sentence literally. This is a gold/source conflict as much as a model error.
- **APY-IN (worse):** after, `has_savings_bank_account` was dropped; "citizens of India who have a savings bank
  account" became only a citizenship rule. **LESSON-001** (separate rule per condition in one sentence) did not
  carry over; **LESSON-003** (stricter field use) may have made the model more cautious. Not proven.

## Limits
- One model, 10 held-out schemes, 3 runs each: a difference of 0.01 F1 is within run-to-run variation.
- Held-out errors have now been read. If any lesson or gold rule is changed because of them, these 10 schemes
  must be relabelled as development and new held-out schemes found.
- Gold contains our own modelling decisions (IGNDPS 80%, inclusive ages, PM-KISAN additions), so part of the
  score measures agreement with those decisions.
