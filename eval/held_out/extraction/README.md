# Extraction evaluate set (Role 5) — team override

**Do not commit protected case files under `local/`.**

## Team override (active)

Target is **all live package clauses** (currently **13**), not PDF ≥40 unseen
held-out. Rebuild:

```bash
python scripts/build_extraction_all_live_clauses.py
```

| Path | Role |
|---|---|
| `manifest.json` | Committed: IDs, sha256, status |
| `local/cases_all_live_clauses_v1.json` | Gitignored case file |
| Gold | Approved package rules (dual-label waived for this override) |

**Claim level:** `team_override_all_live_clauses` — **not** PDF unseen held-out
(most clause IDs already appear in `rule_extraction_cases_dev.json`).

## Commands

```bash
python scripts/evaluate_extraction_held_out.py --dry-run
python scripts/evaluate_extraction_held_out.py --before --runs 3 --yes
python scripts/evaluate_extraction_held_out.py --after --playbook 1.1.0 --runs 3 --yes
```

## Custody

`scripts/check_held_out_custody.py` fails if `eval/held_out/extraction/local/`
is tracked. Keep full JSON local; commit only the manifest.
