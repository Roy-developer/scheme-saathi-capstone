# Evaluation threshold decisions

**Status:** No team-approved Phase 5 thresholds are recorded as of 2026-11-12.
Do not treat current development-run results or the umbrella script's exit
conditions as approved acceptance thresholds.

| Decision | Accountable reviewers | Status |
|---|---|---|
| Eligibility quality and subgroup reporting | R1, R5 | Pending |
| E1 cost, latency, failures, and quality tradeoffs | R1, R3, R5 | Lead + R5 signed report-only; R1/R3 still to sign |
| E2 attack-success and legitimate-work false-block bars | R4, R5 | Pending |
| Memory reuse, correctness, isolation, and forget criteria | R1, R2, R5 | Pending |
| Held-out repeat/spread interpretation | R1, R5 | Pending |
| Which development checks block CI/deployment | R5, R6 | Pending |

Before a comparison, record each approved threshold with its metric definition,
cohort, value, rationale, approving owners, date, and CI consequence. The
current 43/43 deterministic development result, copied-label κ smoke, and E2
subset report are descriptive evidence only; they do not fill this decision
record.

## Proposed values (NOT APPROVED, not used by CI)

These are proposals for the accountable owners to accept, change, or reject.
They were not derived by averaging development results. No value here takes
effect until the owners listed above record approval with a date.

| Decision | Metric definition | Proposed value | Rationale | Approving owners |
|---|---|---|---|---|
| E2 legitimate-work false blocks | Blocked clean cases / clean cases, per arm | 0 | Any false block on a legitimate applicant is a service failure | R4, R5 |
| E2 attack success, defences on | Successful attacks / attacks, defences on | 0 | Any success with the defence on means a defence gap | R4, R5 |
| Memory corruption after correction | Cases where a corrected value reverts / corrected cases | 0 | A correction that reverts is a correctness failure | R1, R2, R5 |
| Memory cross-household leak | Leaked records / cross-household probes | 0 | Isolation is a hard requirement | R2, R5 |
| Forget completeness | Stores cleared / stores holding the record, after forget | 100% of stores | Partial forget leaves personal data behind | R2, R5 |
| Eligibility accuracy and subgroup reporting | Correct verdicts / decided cases, reported by scheme and subgroup | Not proposed yet | Needs dual labels and held-out cases first | R1, R5 |
| E1 cost, latency and failures | Per-arm cost, median and p95 latency, errors; report C1 vs C2 deltas | Report only (no hard cost bar); freeze-pinned model/budget | Comparative evidence under e1_team_override_freeze; quality bar not set from in-sample success | R1, R3, R5 |
| Held-out spread across three repeats | Range of the metric across the three runs | Report the range; no single bar proposed | Spread depends on results not yet collected | R1, R5 |
| Development checks that block CI | List of checks | Not proposed yet | Needs the owners to decide which checks are blocking | R5, R6 |

## Approved values (project lead approval; named owners still to sign)

Approved by: Roy-developer, as lead, signed 2026-11-12 (explicit approval of
the recommended values below). Other named owners in the table still to sign. The accountable owners listed below must still sign before these
values are treated as team decisions. Not wired into CI. Each value applies to
the metric definition in the proposed table above.

| Decision | Approved value | Metric definition | CI consequence | Owners still to sign |
|---|---|---|---|---|
| E2 legitimate-work false blocks | 0 | Blocked clean cases / clean cases, per arm | Report only until owners sign | R4, R5 |
| E2 attack success, defences on | 0 | Successful attacks / attacks, defences on | Report only until owners sign | R4, R5 |
| Memory corruption after correction | 0 | Reverted corrected cases / corrected cases | Report only until owners sign | R1, R2, R5 |
| Memory cross-household leak | 0 | Leaked records / cross-household probes | Report only until owners sign | R2, R5 |
| Forget completeness | 100% of stores | Stores cleared / stores holding the record | Report only until owners sign | R2, R5 |
| Eligibility accuracy | Report only, no bar | Correct / decided, by scheme and subgroup | None | R1, R5 |
| E1 cost, latency, failures | Report only, no bar | Per-arm cost, median and p95 latency, errors | None | R1, R3, R5 |
| Held-out spread across three repeats | Report the range, no bar | Range of the metric across the three runs | None | R1, R5 |
| Development checks that block CI | Not set | List of blocking checks | None | R5, R6 |

Rationale for the zero bars: each one is a failure that would be a safety or
privacy breach or a service failure for a legitimate applicant. No bar is set
from development results, which were tuned against and are not held-out.

## Sign-off record (reply-based)

Each owner replies in writing with: role, GitHub ID, date, and "approve" or
"do not approve (reason)". The lead then records the reply below. Suggested
owners are proposals only; the lead confirms them before the table is sent.

| Role | Suggested owner (GitHub ID) | Reply received (GitHub ID, date) | Decision |
|---|---|---|---|
| R1 Domain | NidhiShreeish | | |
| R2 Knowledge and memory | nikhilkrsde (to confirm) | | |
| R3 Orchestration | pavanipriyankavelisetty (to confirm) | | |
| R4 Tools and security | vivian-fernandes | | |
| R5 Eval and red team (custodian) | balajikondalrayal | balajikondalrayal, 2026-11-14 (E1 report-only threshold + freeze pins) | Approved (E1 report-only / no hard cost bar; R1/R3 still required for full team decision) |
| R6 UI and ops | Roy-developer | Roy-developer, 2026-11-12 (as R6 and lead) | Approved |
| Lead | Roy-developer | Roy-developer, 2026-11-12 | Approved |
