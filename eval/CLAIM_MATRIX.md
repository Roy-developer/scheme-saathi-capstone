# Phase 5 claim matrix

Updated: 2026-11-12. This matrix records local evidence, not team approval.

| Requirement | Evidence | Owner | Status | Claim boundary |
|---|---|---|---|---|
| L9 memory | `docs/MEMORY_POLICY.md`; consent/privacy/expiry tests; one-case functional on/off smoke in `eval/reports/memory_on_off_dev_latest.json` | R2/R5 | Partial | Governed synthetic-data prototype only; R1/R2 approval, checkpoint-level retention, independent cross-household attacks, and multi-case on/off evidence are still required for an L9 claim. |
| L12 Reflexion | `eval/reports/reflexion_e3_inventory.json` | R5 | Dev-only | Inventory does not establish a frozen held-out before/after result. |
| L13 personas and κ | `eval/development/personas_v1.json`; `eval/reports/eligibility_dev_latest.json`; copied-label smoke report | R1/R5 | Dev-only | 43 development personas, including 12 APY; κ uses copied labels; no held-out claim. |
| L13 monitoring | `/metrics`, Prometheus definitions, and opt-in OpenTelemetry Azure Monitor exporter | R5/R6 | Partial | Local instrumentation exists; shared export, dashboard, and alert are not verified. |
| L15 threat model and red team | `docs/THREAT_MODEL.md`; `eval/reports/red_team_dev_latest.json`; `eval/reports/e2_defences_dev_latest.json` | R4/R5 | Partial | 30 attacks listed, 23 offline-runnable; current E2 covers injection, ID masking, and scam checks. |
| E1 cost benefit | `eval/experiments/e1_agent_cost.json` | R3/R5 | Not claimable | Configuration inventory only; no forced-C0/C1/C2 comparative report. |
| E2 defences off/on | `eval/reports/e2_defences_dev_latest.json` | R4/R5 | Dev-only | Results apply only to its offline injection/ID/scam subset and clean cases. |
| E3 Reflexion | `eval/experiments/e3_playbook.json`; inventory report | R5 | Dev-only | Paid and held-out extraction comparisons are not present. |
| E4 signature ablation | `eval/experiments/e4_signature_ablation.json` | R3/R5 | Partial | Rule-engine persona scoring exists; isolated LLM and question-order arms do not. |
| 15 gold schemes | Four active rule packages | R1/R5 | Not claimable | Scheme onboarding is a separate data workstream. |

The local development run on 2026-11-12 scored 43/43 against the four active
packages. `label_agreement_dev_latest.json` explicitly marks `smoke_copy: true`;
its κ value is not independent-label evidence.
