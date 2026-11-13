# E3 inclusion lesson decision (2026-11-13)

Approver: Roy-developer (project lead), recorded at their direction.

## Decisions

- **IGNWPS-MH-ELIGIBILITY-01:** approved (draft text unchanged).
- **IGNOAPS-MH-ELIGIBILITY-01:** approved (draft text unchanged).
- **IGNDPS-MH-ELIGIBILITY-01:** not approved. Reason: its dev split is `null`, and its package `reasons.eligible` text needs a fix first.
- **Paid 1.1.0 arm:** not run now. Budget cap of $20 remains recorded but unspent. Reason: the lessons were drafted from check-split cases, so a run on the same split would measure in-sample results. A held-out run needs its own data approval.

## Consequences

- No playbook 1.1.0 file is created. `data/schemes/playbooks/1.0.0.json` is unchanged.
- E3 claims stay directional, as stated in the results summary `eval/reports/e3_before_after_dev_2026-11-13.json`.
