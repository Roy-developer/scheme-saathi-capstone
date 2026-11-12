# Phase 5 claim matrix

Updated: 2026-11-12. This matrix records local evidence, not team approval.

| Requirement | Evidence | Owner | Status | Claim boundary |
|---|---|---|---|---|
| L9 memory | `docs/MEMORY_POLICY.md`; `tests/test_forget_backup.py`; `tests/test_forget_backup_restart.py`; consent/privacy/expiry tests; SQLite restart persistence test; four-case functional on/off report in `eval/reports/memory_on_off_dev_latest.json` | R2/R5 | Partial | Synthetic-data prototype only. Local forget refreshes current backups before success and replays pending deletions on restart; assumes one replica. Azure durability, physical erasure, and deletion from old/external copies are unproven. The approver selected 90-day return-code memory expiry and no automatic historical-checkpoint expiry; independent cross-household attacks and broader L9 evidence remain required. |
| L12 Reflexion | `eval/reports/reflexion_e3_inventory.json` | R5 | Dev-only | Inventory does not establish a frozen held-out before/after result. |
| L13 personas and κ | `eval/development/personas_v1.json`; `eval/reports/eligibility_dev_latest.json`; copied-label smoke report | R1/R5 | Dev-only | 43 development personas, including 12 APY; κ uses copied labels; no held-out claim. |
| L13 monitoring | OpenTelemetry instruments in `src/observability/metrics.py`; `docs/MONITORING.md` records shared-dev `AppMetrics` names from image `git-13dde6b37e3a` | R5/R6 | Partial | Export from an older image is observed; current branch is not deployed, and the Managed Grafana dashboard and alert proof is missing. |
| L15 threat model and red team | `docs/THREAT_MODEL.md`; `eval/reports/red_team_runtime_latest.json`; `eval/reports/red_team_runtime_before_masking_fix.json`; `eval/reports/red_team_dev_latest.json`; `eval/reports/e2_defences_dev_latest.json` | R4/R5 | Partial | All 30 briefs approved; separate local API/graph/MCP/portal runtime run now passes 30/30 after fixing shared PAN and mixed-separator masking (initially 28/30). Scripted offline models and synthetic fixtures do not establish live LLM efficacy, full L9, or expanded E2 off/on coverage. The older helper gate remains separate. |
| E1 cost benefit | `eval/experiments/e1_agent_cost.json` | R3/R5 | Not claimable | Configuration inventory only; no forced-C0/C1/C2 comparative report. |
| E2 defences off/on | `eval/reports/e2_defences_dev_latest.json`; `eval/reports/e2_runtime_dev_latest.json`; `.github/workflows/frontend-checks.yml` | R4/R5 | Dev-only | Offline subset plus five paired local application-boundary scenarios: attacks off 4/5, on 0/5; clean false blocks 0/5 per arm (20 observations). Single-boundary test adapters are not a global off mode; memory consent is not authenticated ownership. Blocking runtime CI steps and synthetic report uploads are wired locally; remote execution and independent frozen coverage remain open. |
| E3 Reflexion | `eval/experiments/e3_playbook.json`; inventory report | R5 | Dev-only | Paid and held-out extraction comparisons are not present. |
| E4 signature ablation | `eval/experiments/e4_signature_ablation.json` | R3/R5 | Partial | Rule-engine persona scoring exists; isolated LLM and question-order arms do not. |
| 15 gold schemes | Four active rule packages | R1/R5 | Not claimable | Scheme onboarding is a separate data workstream. |

The local development run on 2026-11-12 scored 43/43 against the four active
packages. `label_agreement_dev_latest.json` explicitly marks `smoke_copy: true`;
its κ value is not independent-label evidence.
