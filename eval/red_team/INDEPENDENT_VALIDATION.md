# Independent attack authorship / validation

This track upgrades E2/L15 from **implementer-authored development evidence**
to a credible **independent subset** claim. It does not replace the v0.7 suite
or invent human signatures.

## Baseline freeze (do not rewrite)

| Field | Value |
|---|---|
| Suite | `eval/red_team/attacks_v0.json` v0.7.0 |
| Authorship | `project_approver` (see `AUTHORSHIP.md`) |
| Brief approval | Vivian — **for implementation**, not executed security evidence |
| Runtime / E2 | Scripted/offline; CI gate on main |
| Claim | Development evidence only — **not** independent authorship or validation |

Keep v0.7 stable. Independent work lands in a **second evidence lane**.

## Roles

| Role | Who | Must not |
|---|---|---|
| Independent author | Role 4 / Vivian / outsider who did **not** implement the defence under test | Open `attacks_v0.json` expected behaviours or E2 off-adapters before drafting |
| Brief reviewer | Different person from the author | Be the same as the author |
| Control implementer | Role 5 (maps briefs → runtime assertions, keeps CI green) | Fill the independent author fields |
| Execution validator | Author or separate reviewer after a recorded run | Sign “pass” without reading observations |

## Priority subset (first pass)

Twelve IDs in `independent_subset_v1_blank.json`:

1. `RT-MEMORY-001`, `RT-MEMORY-002`, `RT-MEMORY-003`
2. `RT-OTHER-001`, `RT-OTHER-002`
3. `RT-IDLEAK-001`, `RT-IDLEAK-005`
4. `RT-INFLATE-002`, `RT-INFLATE-003`
5. `RT-INJECT-001`, `RT-INJECT-006`
6. `RT-SCAM-003`

Enough for a partial independent claim; expand later if needed.

## Author steps

1. Read `docs/THREAT_MODEL.md` and `docs/POLICY.md` only.
2. Open **only** `eval/red_team/independent_subset_v1_blank.json`.
3. For each row, fill:
   - `independent_attack_input` — synthetic hostile input
   - `independent_expected_behaviour` — what fail-closed looks like
   - `author` — your name/handle
   - `authored_on` — ISO date
   - `did_not_consult_v0_expected_behaviour` — `true` (required for independence)
4. Do **not** set `review_status` yourself.
5. Open a PR. Do not copy-paste from v0 expected behaviours.

## Brief reviewer steps

1. Confirm author ≠ yourself and author is not the control implementer for that boundary.
2. Confirm synthetic data only; no real PII; no held-out custody leakage.
3. Set `reviewed_by`, `reviewed_on`, `review_status` to `approved_for_implementation` or `changes_requested`.

## Implementer mapping (Role 5)

1. Map each approved brief to an existing runtime/E2 assertion or add a narrow new one.
2. If the check is narrower than the brief, keep the brief honest (do not inflate claims).
3. Record run evidence under `eval/reports/` (force-add if needed) and note the freeze pins used.

## Execution validation

After a recorded run for the subset:

1. Validator reads the observation JSON / traces for the subset IDs.
2. Fills `execution_validation` on each row: `validator`, `validated_on`, `run_report`, `accepted` (`true`/`false`), `note`.
3. Only then may CLAIM_MATRIX say “independent subset signed.”

## Gate

```bash
python scripts/check_independent_red_team.py
```

- Exit **0** with `status: blank_pending_author` while rows are empty (scaffold OK).
- Exit **0** with `status: ready_for_brief_review` when authors finished and attestations are true.
- Exit **0** with `status: independent_subset_claimable` only when every priority row has author, reviewer ≠ author, approved brief, and accepted execution validation.
- Exit **2** if someone sets claimable metadata inconsistently (e.g. approved without author, or author == reviewer).

## What this does *not* claim

- Full 30/30 independent authorship
- Live LLM attack resistance (unless a separate live arm is recorded)
- Authenticated household ownership / full L9
- Replacement of v0.7 CI regression
