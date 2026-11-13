# Phase 1-4 acceptance checklist

This is a sign-off record, not a summary of unit-test status. Automated checks
and local model smoke tests do not replace manual, independent, or deployment
acceptance.

## Evidence already present

- [x] Automated C0 English UI/API/MCP/mock-portal journeys are recorded in
      `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md`.
- [x] Local automated coverage exercises registry facts, corrections,
      document checks, exact approval, and mock receipt behavior.
- [x] A synthetic-data free Nemotron client smoke was run on 2026-11-12; it is
      not an E1 comparison or a freeze.
- [x] Local synthetic backup tests exercise pending-deletion recovery, including
      a mixed snapshot and a concurrent save. This does not establish Azure
      share durability or multi-worker behavior.

## Facts and source review (2026-11-12)

All four active bundles have recorded approval for a **synthetic mock only**.
These decisions are not confirmation of current government policy or approval
for real applicant data.

| Scheme | Outstanding source and fact review |
|---|---|
| IGNWPS-MH | Source currentness and independent language review remain open; the BPL card interpretation is a reviewer decision, not a source-stated document requirement. |
| PM-KISAN-IN | Current landholding cutoff, transfers, guideline currentness and State/UT verification remain unresolved. Mock-only question/privacy metadata approval is not an independent privacy or native-speaker review. |
| IGNOAPS-MH | Central versus Maharashtra age criteria, citizenship and other-pension conditions remain unresolved. Mock-only question/privacy metadata approval is not an independent privacy or native-speaker review. |
| APY-IN | Later eligibility circulars were not independently ruled out. Three APY intake questions and their privacy metadata, native-language wording and broader data flow remain pending review. The mock refuses pre-2022-10-01 application dates pending review of historical rules. |

The scheme-specific records are `docs/IGNWPS_MH_RULE_REVIEW_2026-10-30.md`,
`docs/PMKISAN_RULE_REVIEW_2026-11-02.md`,
`docs/IGNOAPS_MH_RULE_REVIEW_2026-11-08.md`,
`docs/APY-IN_RULE_REVIEW_2026-11-11.md`, and
`docs/APY-IN_FACT_INTAKE_REVIEW_2026-11-11.md`. Do not infer a new approval
from this summary.

The latest full offline pytest attempt stopped on a Streamlit timeout; the
affected test passed alone and the UI integration tests passed in separate
local-port runs. A single green full-suite run is not established.

## Acceptance still open

- [ ] R1 confirms fact definitions, privacy policies, questions, scheme sources,
      and expected results.
- [ ] Manual browser acceptance for EN/HI/MR and Citizen/CSC flows.
- [ ] Independent language and accessibility review.
- [ ] Restart/process-failure and multi-worker persistence/deletion acceptance.
- [ ] Shared deployment acceptance and operational monitoring proof.
- [ ] Named team lead records whether Phases 1-4 are accepted and lists any
      exceptions before authorizing paid or final held-out Phase 5 runs.

**Sign-off:** Pending. No approver or date is recorded.
