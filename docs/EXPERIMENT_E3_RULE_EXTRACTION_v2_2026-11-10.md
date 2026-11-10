# E3 (v2): did the rule-extractor lessons help? (2026-11-10)

Replaces the first E3 run (docs/EXPERIMENT_E3_RULE_EXTRACTION_2026-11-10.md), whose held-out schemes were
exposed and relabelled development.

## Setup
- Extractor `scripts/extract_scheme_rules.py`, model `openai/gpt-4.1-mini`, temperature 0. The same prompt
  and field list in all 6 runs; the only difference is the playbook.
- Scorer `score_many` (field, operator, value must match). Gold: `data/schemes/rule_gold_selection.json` v0.2.0,
  15 development and 8 held-out schemes, all `human_reviewed`.
- Lessons written from the 15 development schemes only (v2 baseline runs 1-3). Held-out errors were not read
  before freezing.
- Playbook 2.0.0, frozen 2026-11-10 (`data/schemes/rule_extracted/playbook_v2.0.0_frozen.json`):
  9 approved lessons (001, 002, 003, 005-010). **Rejected: LESSON-004** ("too specific to a single scheme;
  it is not a generalizable rule for the extractor"). All reviews by Priyanka Velisetty.
- Runs: before = `v2_baseline_run1-3` (no lessons, all 23 schemes); after = `v2_playbook_heldout_run1-3`
  (held-out 8 only). About 93 model calls in total; cost is well under US$1 (no per-call cost logged).

## Held-out result (8 schemes, 58 gold rules)
| | Precision | Recall | F1 (mean of 3) | F1 per run | Range |
|---|---|---|---|---|---|
| Before (no lessons) | 0.62 | 0.49 | 0.548 | 0.486, 0.583, 0.577 | 0.49-0.58 |
| After (playbook 2.0.0) | 0.65 | 0.55 | **0.598** | 0.590, 0.593, 0.611 | 0.59-0.61 |

**Reading:** F1 rose by 0.05. Every after-run (lowest 0.590) is above every before-run (highest 0.583), and
the after-runs vary less. Precision and recall both rose. Rules discarded by the code checks fell from 8.3
to 6.0 per run. This is a modest but consistent improvement; with 3 runs and 8 schemes it is not a large-sample result.

## Per scheme (mean F1, before -> after)
| Better | Same | Worse |
|---|---|---|
| TFEFVS-MH 0.30 -> 0.68, TCE-SC-IN 0.22 -> 0.50, PMAY-U-IN 0.34 -> 0.61, PMKMDY-IN 0.69 -> 0.75 | AABYM-MH 0.73 | PSGS-DIP-IN 0.77 -> 0.56, PRE-ST-IN 0.46 -> 0.34, PG-IGSSGC-IN 0.62 -> 0.50 |

Three schemes got worse. Which lesson caused this is **not yet known**: all 9 lessons were applied together.
Finding it needs a leave-one-lesson-out run, or reading those three schemes' errors. Reading them is allowed
for the report, but if any lesson or gold rule is then changed, these schemes become development.

## Limits
- 8 held-out schemes, 5 of them education schemes; one model; 3 runs per arm.
- Gold includes the team's modelling decisions (inclusive ages, 80% or more, the completed scheme rules), so
  part of the score measures agreement with those decisions.
- Scorer gives no credit for equivalent integer forms (`lt 3` vs `lte 2`).
- Lesson-generation cost: lessons were drafted from the baseline output and reviewed by hand; no extra model
  calls were made for reflection.

## Leave-one-lesson-out (27 extra runs, held-out 8 schemes, same settings)
Each approved lesson was removed once (8 held-out schemes x 3 runs per variant). Raw runs:
`data/schemes/rule_extracted/loo/`. Reference: all 9 lessons F1 0.598; no lessons F1 0.548.

| Lesson removed | Mean F1 | Change vs all-9 | Reading |
|---|---|---|---|
| 001 person type + age range | 0.600 | +0.002 | no effect |
| 002 short exact quotes | 0.578 | -0.020 | helps |
| 003 use only stated fields | 0.561 | -0.037 | helps |
| 005 unique rule_id | 0.553 | -0.045 | helps most |
| 006 exact field names | 0.602 | +0.003 | no effect |
| 007 age range ends | 0.601 | +0.003 | no effect |
| 008 pension field | 0.612 | **+0.014** | **only one that may hurt** |
| 009 disability yes/no + number | 0.605 | +0.007 | no clear effect |
| 010 other person's age | 0.601 | +0.002 | no effect |

**Reading:** the gain comes mostly from LESSON-005, 003 and 002 (removing any of them loses 0.02-0.045 F1).
LESSON-008 is the only one whose removal raises F1 (+0.014), but its three runs (0.602-0.617) overlap
the all-9 runs (0.590-0.611), so this is a weak signal, not proof. Six lessons make no measurable
difference (within +/-0.01). **No single lesson explains the three schemes that got worse**
(PSGS-DIP, PRE-ST, PG-IGSSGC): removing any one lesson leaves them near 0.3-0.6, so the drop looks like
run-to-run variation plus small effects, not one bad lesson.

Limits: 3 runs per variant; differences under about 0.02 are within the run-to-run spread seen in the baseline
(0.49-0.58). This tests removal of one lesson at a time and cannot show interactions between lessons.
