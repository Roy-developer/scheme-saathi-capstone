# E3 PDF path status (2026-11-13)

Tracks Reflexion before/after beyond the directional 1.0.0 check-split closure.

## Team override (2026-11-13)

**Decision:** Do **not** require ≥40 unseen extraction cases. Use **all live package
clauses** (currently **13** unique `source_clause_id` values in
`src/rules/packages/`).

| Field | Value |
|---|---|
| Bar | `team_override_all_live_clauses` |
| Case file | `eval/held_out/extraction/local/cases_all_live_clauses_v1.json` (gitignored) |
| Rebuild | `python scripts/build_extraction_all_live_clauses.py` |
| Claim level | **Team override — not PDF unseen held-out** (11/13 clause IDs already appear in the development extraction file) |
| Dual labels | Waived for this override; gold = approved package rules |
| Go-ahead | Team-override all-live-clauses evaluate is **authorised** (free-model / recorded budget; still not a PDF ≥40 unseen claim) |

## Checklist

| # | Item | Status |
|---|---|---|
| 1 | Build playbook **1.1.0** / **1.1.1** | **Done** (1.1.1 adds APY + pension-boolean accuracy lessons) |
| 2 | Extraction set for before/after | **Done under override** — n=13 all live clauses |
| 3 | Before/after ×3 | **Done with 1.1.1** (free Nemotron) |
| 4 | Explicit evaluate go-ahead | **Authorised** for team-override bar (this doc) |
| 5 | Record result | **1.1.1:** 4/13 → **12/13** all-runs, 0 regressions (`eval/reports/e3_team_override_before_after_2026-11-13.json`) |
| — | PDF ≥40 unseen held-out | **Explicitly waived** by team override |
| — | IGNDPS `reasons.eligible` copy-paste | **Fixed** in `src/rules/packages/igndps_mh.v1.json` |

## Commands

```bash
python scripts/build_extraction_all_live_clauses.py   # if local file missing
python scripts/evaluate_extraction_held_out.py --dry-run
python scripts/evaluate_extraction_held_out.py --before --runs 3 --yes
python scripts/evaluate_extraction_held_out.py --after --playbook 1.1.0 --runs 3 --yes
```

## Go-ahead log

| When | Who | Decision |
|---|---|---|
| 2026-11-13 | Role 5 / team (chat override) | Team-override all-live-clauses evaluate is **authorised**. Waives ≥40 unseen bar. Results must be labelled team-override, not PDF held-out. |

## What must not be done

- Call this run a **PDF unseen held-out** result.
- Hand-edit `eval/freeze/manifest.json` (use `scripts/build_freeze_manifest.py`).
- Learn / tune lessons from the `team_override` split.
