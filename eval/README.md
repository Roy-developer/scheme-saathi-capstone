# Evaluation & red-team (Role 5)

Owner: Vivian Fernandes. Source of truth for the plan: the team's capstone
guide and `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md`. This folder is new as of
7 Nov 2026 — nothing here existed before; everything below is in progress.

## Layout

| Folder | Holds | Who may read it |
|---|---|---|
| `eval/personas/` | Dev-split personas + the schema (`schema.py`) | Everyone |
| `eval/held_out/` | Held-out personas, labelled, frozen before the final run | **Not** the person tuning the agent (Priyanka). Treat as read-restricted even though git can't enforce that — don't link it from docs anyone browses casually, and don't paste held-out cases into chat with whoever is actively tuning prompts/rules. |
| `eval/red_team/` | The 30+ attack suite | **Not** Balaji (builds the defences). Same convention as above. |
| `eval/report/` | Evaluation report, experiment log, judge calibration results | Everyone, once final |

## Integrity rules (from the capstone guide, non-negotiable)

1. Expected outcomes are written **before** the agent ever runs on a case.
2. The held-out split is never read by whoever tunes the agent.
3. The red-team attack list is never read by whoever builds the defences.
4. If a change is made after seeing held-out results, those cases move to
   the dev split and the experiment log says so — never silently re-used.
5. Gold answers never enter prompts or tool code.

## Persona format

`eval/personas/schema.py` defines `Persona`, built directly on the project's
own `HouseholdProfile` and `VerdictResult` contracts (`src/rules/models.py`,
`src/workflow/state.py`) so a persona's expected outcome can be compared
field-for-field against what the journey API actually returns. See that
file's docstrings for the shape; one persona = one JSON file.

## Status (7 Nov 2026)

- [x] Folder scaffold
- [x] Persona schema
- [ ] 30 dev-split personas (target: Sat 8 Nov)
- [ ] Two-person labelling with Nidhi, held-out split frozen (target: Sun 9 Nov)
- [ ] Simulated-citizen harness
- [ ] Judge + Cohen's kappa calibration
- [ ] Red-team suite (30+ attacks)
- [ ] E1–E4 experiment runs
- [ ] Evaluation report (4–6 pages)
