# Evaluation (Role 5)

PDF-oriented evaluation and monitoring foundation for Scheme Saathi (L13/L15).

## One command (CI gate)

```bash
python scripts/run_role5_dev_evals.py
```

Runs: eligibility personas, Reflexion inventory, red-team offline checks, E2
defences off/on, κ smoke, simulated-citizen smoke, E1–E4 config inventory.

## PDF coverage map

| Requirement | Command / location |
|---|---|
| Dev personas | `eval/development/personas_v1.json` (43) |
| ≥40 held-out (local, gitignored) | `python scripts/generate_held_out_personas.py` |
| Held-out scoring (Role 5 only) | `python scripts/evaluate_eligibility_held_out.py` |
| Dual-label κ | `python scripts/evaluate_label_agreement_dev.py` |
| Simulated citizen | `eval/harness/simulated_citizen.py` |
| Red-team 30 | `python scripts/evaluate_red_team_dev.py` |
| E2 off/on | `python scripts/evaluate_e2_defences_dev.py` |
| E3 inventory | `python scripts/evaluate_reflexion_playbook_dev.py` |
| Monitoring handoff | `monitoring/` configs for Azure Managed Grafana / separate Container App |

## Honest limits

- κ smoke **copies** labels — Role 1 must dual-label for real.
- Paid E3, live E1/E4, live memory/approval red-team, three held-out repeats still required for the final PDF claim.
- Held-out files under `eval/held_out/local/` must not be committed or shipped in the app image.

See [`docs/EVALUATION_REPORT.md`](../docs/EVALUATION_REPORT.md).
