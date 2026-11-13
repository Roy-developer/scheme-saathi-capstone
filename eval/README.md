# Evaluation (Role 5)

PDF-oriented evaluation and monitoring foundation for Scheme Saathi (L13/L15).

## Core development gate

```bash
python scripts/run_role5_dev_evals.py
```

Runs: eligibility personas, Reflexion inventory, red-team offline checks, E2
defences off/on, κ smoke, simulated-citizen smoke, deterministic synthetic
memory on/off smoke, and E1–E4 config inventory.

`frontend-checks.yml` also runs the following as separate blocking CI steps,
without repeating their modules in the broad pytest step:

```bash
python scripts/evaluate_red_team_runtime.py
python scripts/evaluate_e2_runtime.py
```

The two synthetic runtime JSON reports upload even on failure. This wiring is
local until the workflow changes are pushed and run in GitHub Actions.

## PDF coverage map

| Requirement | Command / location |
|---|---|
| Dev personas | `eval/development/personas_v1.json` (43; 12 APY; dataset version 1.2.0) |
| ≥40 held-out (local, gitignored) | `python scripts/generate_held_out_personas.py` |
| Held-out scoring (Role 5 only) | `python scripts/evaluate_eligibility_held_out.py` |
| Dual-label κ | `python scripts/evaluate_label_agreement_dev.py` |
| Simulated citizen | `eval/harness/simulated_citizen.py` |
| Red-team 30 | `python scripts/evaluate_red_team_dev.py` |
| E2 off/on | `python scripts/evaluate_e2_defences_dev.py` |
| Application-boundary E2 off/on | `python scripts/evaluate_e2_runtime.py` (five paired scenarios; dedicated CI step) |
| Application-path red-team 30 | `python scripts/evaluate_red_team_runtime.py` (scripted offline models; dedicated CI step) |
| Memory on/off smoke | `python scripts/evaluate_household_memory_dev.py` |
| E3 inventory | `python scripts/evaluate_reflexion_playbook_dev.py` |
| Monitoring handoff | OpenTelemetry export to Azure Monitor; live Managed Grafana evidence remains with Role 6 |

## Honest limits

- κ smoke **copies** labels — Role 1 must dual-label for real. E4 team-override records model-assisted dual-label κ via `python scripts/evaluate_e4_label_agreement.py` (`smoke_copy: false`, still not independent human Role-1).
- The current local development run scored 43/43 against the four active packages; this is not independent validation or held-out evidence.
- The memory on/off report is one deterministic synthetic case; it is not an independent or multi-case L9 evaluation.
- Local application-path red-team evidence passes 30/30. The separate E2 runtime report records five single-boundary comparisons (20 observations): attacks off 4/5, on 0/5; clean false blocks 0/5 in each arm. Off uses isolated unsafe adapters, not a deployable global off mode. Neither report establishes live LLM efficacy or independent validation.
- Paid E3 held-out, live E1, PDF held-out E4 (if claimed), independent attack validation, and three held-out repeats still required for the final PDF claim.
- E4 team override: `python scripts/evaluate_e4_signature_ablation.py --team-override --llm-arm --multilingual --yes` (waives ≥40 HO; not a PDF HO claim).
- Held-out files under `eval/held_out/local/` must not be committed or shipped in the app image.

See [`docs/EVALUATION_REPORT.md`](../docs/EVALUATION_REPORT.md).
