# Local Phase 5 Gap-Closure Plan

**Status:** Working plan; Phase 5 remains paused for paid evaluation and final held-out runs.  
**Baseline:** `supervisor-redesign-3`, compared with `role5/phase5-gap-closure-plan`.  
**Monitoring input:** `feature/monitoring-otel-on-supervisor`, commit `13dde6b`.

**Latest implementation update:** Memory steps 1-6 are implemented; steps
7-9 have partial test/evidence coverage. On 2026-11-12, the project approver
selected 90-day expiry for consented return-code memory and no automatic expiry
for historical SQLite checkpoints. The existing explicit-forget path and
SQLite restart persistence test support that behavior; no checkpoint pruning
was added. A four-case synthetic memory-on/off report now compares verdicts
and question counts, but independent and full L9 evidence remain open. The
corrected return-code answer was also verified through the real UI
load/correct/resave path; UI integration and app
regressions passed (24); 101 focused memory/journey/API/UI/evaluation tests and
four follow-up memory/custody tests passed. The complete free Role 5
development gate passed with 43/43 eligibility cases and the existing 23
runnable red-team checks. A read-only shared-dev check found telemetry from the
older image, but the current branch is not deployed and no alert rules exist.
The corrected APY evaluation assertion was committed and pushed as
`866d7be`; Frontend Checks run `43147565157` passed the custody guard,
frontend fixtures, and Role 5 development gate. This CI workflow does not build
the application image, so image-level custody and deployment remain unverified.
Synthetic Nemotron workflow smoke was attempted with a project-configured key,
but OpenRouter returned HTTP 404 for structured output on three listed free
routes. No applicant data was sent; the workflow smoke is not counted as
evidence.

This plan replaces the downloaded Round 2 plan as the working sequence for this
local branch. It accounts for the monitoring implementation on the feature
branch and for the gaps verified in the local tree. It is not approval to run
paid evaluations or access held-out cases.

## Implementation strategy — diminishing returns

Follow the Round 2 plan's principle: spend effort where it closes a PDF claim,
removes a prerequisite, or reduces a material risk. Do not equate more code,
tests, or personas with more evaluation evidence.

| Order | Work with highest marginal value now | Why it unlocks value | Stop / move on when |
|---|---|---|---|
| 1 | Close Wave 0-1 governance: verify held-out CI/image custody, obtain threshold and Phase 1-4 acceptance decisions, and complete freeze/authorship contracts. | These are prerequisites for trustworthy comparisons and final held-out work. | Required artifacts are verified and team decisions are recorded; if a sign-off/access dependency is external, mark it blocked rather than polishing around it. |
| 2 | Finish the remaining memory evidence in Wave 2: demonstrate corrected-value reuse through the UI, bounded retention at the actual checkpoint layer, and a compact memory-on/off report. | This closes the L9 evidence gap and enables honest memory-specific security tests. | The policy, correction, expiry, isolation, forget, and on/off evidence match their DoD; stop adding unit tests that do not change that evidence. |
| 3 | Address missing security/E2 classes in Wave 3: own-data, memory isolation, and approval authorization; preserve independent attack authorship and benign controls. | These have higher claim value than further tuning of already-covered injection/ID/scam checks. | At least 30 independently authored attacks actually execute and off/on attack success plus false blocks are reported; do not inflate the runnable count with stubs. |
| 4 | Run E1/E3/E4 and final held-out work in Wave 4 only after approved freeze and custody gates. | This avoids spending paid calls or contaminating held-out cases before results are comparable. | Complete only the specified arms and three repeats; stop rather than add extra runs for cosmetic score gains. |
| Parallel, gated | Wave 5 shared monitoring proof, owned by R6, once a safe environment and credentials are available. | Local exporter/dashboard polish cannot substitute for Azure Monitor data and a working alert. | Stop local polish until shared telemetry and alert evidence can be collected safely. |

**Low-return work to avoid:** adding easy development personas after the
development set is adequate; chasing 43/43 accuracy; tuning more regexes while
memory/approval stubs remain; reformatting dashboards without Azure Monitor data;
rerunning or retuning against held-out results; and reopening planning when no
new evidence, approval, or blocker state has changed.

**Reprioritization trigger:** revisit the order only when a prerequisite is
approved, an artifact changes the claim status, a test exposes a material
control failure, or new evidence changes the risk/effort balance. Record the
specific change and update the status table; otherwise execute the current
highest-value unblocked item.

## 1. Verified local starting point

| Area | Local state | Remaining gap |
|---|---|---|
| Development personas | 43 personas across 4 schemes after importing 12 APY cases; dataset version 1.2.0 | The local harness scored 43/43 on 2026-11-12. This is deterministic development evidence, not independent validation or held-out evidence. |
| Scheme packages | 4 active packages, including APY | Do not imply the separate 15-gold-scheme target is met. |
| Evaluation reports | The local umbrella run generated seven reports under `eval/reports/`; report files were previously ignored | Allowlist the reproducible development artifacts for review; do not treat copied-label κ as calibration. |
| Held-out custody | README and ignore rule exist; no local held-out persona file is present; current CI custody guard passes | Image-level exclusions remain unverified; keep generated cases out of Git. No unstage action is currently needed. |
| Red team / E2 | 30 attacks: 23 runnable, 7 stubs. E2 runs injection, ID masking, and scam checks plus clean-case false-block scoring. | Eligibility-truthful, own-data, memory, and approval paths are not covered by the E2 off/on report. |
| Memory | Consent-gated return-code store records policy/version, approved fact IDs, and 90-day expiry; legacy/expired records are discarded. Approver selected no automatic expiry for historical SQLite checkpoints. | Multi-case memory-on/off evidence and cross-household attack coverage remain open; fact-set/consent-text review is still required before real-applicant use. Synthetic data only. |
| Forget flow | One retryable API operation attempts journey and household deletion and reports partial failure. | Not transactional; verify all backing stores and retry after an incomplete result. |
| Labels / experiments | κ smoke uses copied labels; E1/E4 configs exist, but required arms are not evidenced; paid E3 is pending | Independent labels and frozen, reproducible E1-E4 evidence remain open. |
| Monitoring | OpenTelemetry metrics are the only instrumentation; the Azure Monitor exporter from `13dde6b` is ported into this working tree. The Prometheus implementation has been removed. | The exporter has no shared-environment proof; alert/dashboard behavior, metric accuracy, and Azure configuration remain to be demonstrated. |
| Threat model | ASI06 now documents the consent-gated return-code prototype, controls, and residual risks in `docs/THREAT_MODEL.md`. | Keep it aligned with changes; cross-household attack evidence remains open. |

## 2. Execution order

### Wave 0 — Evidence and custody hygiene (P0)

1. **Partial:** the local custody guard and its three focused tests pass.
   Frontend Checks run `43147565157` on `866d7be` passed the custody guard,
   frontend fixtures, and Role 5 development gate. The workflow does not build
   the application image, and no local Docker/Podman/Nerdctl runtime is
   available; verify image-level exclusions before releasing held-out cases.
2. **Done:** reconciled the 31-persona set with 12 APY cases (43 total), ran
   the local harness, and updated the reports. Do not treat the results as
   independent or held-out evidence.
3. **Done:** the claim matrix exists with evidence, owners, and claim statuses.
4. **Pending sign-off:** Role 1/team leads must approve thresholds and dates
   before score comparisons. Do not invent bars absent from the requirements.
5. **Partial:** the retrieval backlog records controlled before/after Recall@5
   results on 199-query and 30-query development sets. A canonical paired run
   with exact command/config/input hashes and independent label review remains
   open; do not treat AI-reviewed labels as validated evidence.

**Exit:** counts agree with the actual dataset; held-out custody is verified;
claims and thresholds are documented without overstating results.

### Wave 1 — Governance and freeze contract (P0)

1. Record what Phases 1-4 have and have not accepted; Phase 5 remains paused
   for paid and final held-out runs until this review exists.
2. Create `eval/freeze/` manifest pinning model/provider, prompt and middleware
   versions, tool allowlists, budgets, package/registry hashes, playbook hash,
   attack-suite version, and (after Wave 2) memory-policy version.
3. Document independent attack authorship and review metadata. Attack authors
   must not be the defenders of the tested controls.
4. Document held-out secrecy, regeneration, and exposure/reclassification rules.
5. Connect approved evaluation thresholds to the CI gate, which must fail
   below the approved floor. Preserve one representative failed-run explanation.
6. Keep report non-claims aligned with the actual evidence inventory.

**Owners:** R1 and team leads for acceptance/threshold decisions; R3/R5 for
freeze details; R5 for attack and held-out custody.

### Wave 2 — Governed household memory (P0 product gaps, then P1 evidence)

1. A versioned `docs/MEMORY_POLICY.md` documents the prototype policy. The
   project approver selected a 90-day TTL for consented return-code memory and
   no automatic expiry for historical checkpoints on 2026-11-12. Fact-set and
   consent-language review remains required before real-applicant use.
2. **Implemented:** memory records include explicit consent metadata,
   `expires_at`, policy version, and fact identifiers. Legacy records without
   valid consent/expiry are deleted on access.
3. **Implemented:** the save/load path permits only known facts with approved
   definition and privacy reviews; highly-sensitive, unknown, and unreviewed
   facts are excluded or rejected.
4. **Implemented:** API and English/Hindi/Marathi UI require explicit memory
   consent; the control is unchecked by default and resets on forget.
5. **Implemented:** expiry is checked on reads; writes refresh the 90-day
   expiry. Clock injection covers the memory unit tests.
6. **Implemented:** one forget operation attempts both stores, returns an
   error on partial failure, and can be retried safely. Unit and integration
   tests cover the combined flow.
7. **Partial:** the existing Save action replaces approved facts for the
   entered return code; unit, real-graph, and UI integration tests cover
   updating a corrected value and reusing it on the next visit. Active journey
   state caps conversation turns and handoffs at 40. Historical SQLite
   checkpoints have no automatic expiry per the approver's decision; the
   existing restart-persistence test passes and explicit forget deletes a
   conversation thread. **Backup fix implemented locally:** a durable pending
   marker precedes live deletion, current snapshots are refreshed before 204,
   and pending deletions replay before startup serves requests. Synthetic
   tests cover failed refresh, mixed snapshots, retry, concurrent API requests,
   and preservation of an unrelated journey. This assumes one backend replica;
   Azure durability, physical erasure, and deletion of old external copies
   remain unverified. See `tests/test_forget_backup.py`,
   `tests/test_forget_backup_restart.py`, and `docs/MEMORY_POLICY.md`.
8. **Partial:** tests cover consented versus fresh journeys, saved-fact
   correction/reuse, return-code isolation, policy filtering, and combined
   forget failure/success. `eval/reports/memory_on_off_dev_latest.json` records
   four deterministic synthetic functional cases; independent labels and
   memory/approval attack evidence remain open.
9. **Partial:** ASI06, the policy, focused tests, and four-case smoke report are
   linked from the evaluation report. Full L9 evidence remains open.

**Progress:** Steps 1-6 implemented; steps 7-9 are partial. The approved
retention choices are documented and the focused memory/checkpoint tests pass
(26); the Wave is not exited.

**Exit:** explicit consent, expiry, privacy filtering, correction, and complete
forget behavior are demonstrated. Do not claim full L9 until the on/off report
and evidence pack are also complete.

### Wave 3 — Security and E2 (P0 partial, P1 full claim)

1. Refresh the threat model against the actual memory and approval code.
2. The project approver authored and Vivian reviewed seven case briefs; both
   are confirmed independent of the control implementers. Each now maps to an
   allowlisted local pytest case executed by the Role 5 development gate; the
   latest run passed all seven. This is development evidence, not full L9 or
   independent 30-case evidence. Vivian approved RT-SCAM-001 through
   RT-SCAM-003 and all 20 remaining revised briefs with advisory scores above 80.
   All 30 briefs are approved for implementation; historical AI objections and
   full-app validation gaps remain open, not pending human approval.
   A separate 2026-11-12 application-path runtime run executed all 30 approved
   cases: initially 28 passed and two failed. RT-IDLEAK-004 (mixed separators)
   and RT-IDLEAK-005 (PAN) leaked synthetic identifiers into model input and
   saved checkpoint state. Shared masking rules now cover both; the rerun
   passed 30/30 and focused masking tests passed 101/101. Results and case-level
   boundaries are in `eval/reports/red_team_runtime_latest.json` and
   `docs/EVALUATION_REPORT.md`; the original failed run is retained separately.
   The run uses real local API/MCP/portal paths with scripted offline models;
   it does not establish live LLM efficacy or expanded E2 off/on evidence.
   On 2026-11-12, an isolated headless Chrome search with a synthetic
   pending-review scam passage showed its OTP lure and clickable example link
   without a scam-specific warning. The passage was injected into the test
   search child only, not the real corpus. The shared search adapter now
   ignores only flagged passages and shows a safe warning, preserving clean
   matches. Headless Chrome rechecks covered mixed, all-scam, and clean search
   results; the regression is covered by API/UI and adapter tests.
   This closes the reproduced path, not all red-team or L9 gaps.
3. **Implemented locally:** synthetic PAN/Aadhaar input through the real intake
   path is checked at model and checkpoint boundaries; the separate E2 run
   compares masking on/off with a clean intake control.
4. **Partial:** `scripts/evaluate_e2_runtime.py` executes five derived scenarios
   for confirmed facts, own-data privacy, memory consent, scoped draft reads,
   and human approval, with clean controls in each arm (20 observations).
   Attack success is off 4/5 versus on 0/5; clean false blocks are 0/5 in both
   arms. Off means one named boundary removed using isolated test-only
   adapters; remaining controls stay active. The fact-filter off attack still
   requires confirmation and is not counted as a successful silent overwrite.
   This is not all 30 attacks paired, authenticated household ownership,
   live LLM efficacy, or independent frozen E2 evidence.
5. **Wired locally:** `frontend-checks.yml` has dedicated blocking runtime
   red-team and E2 gates, excludes those modules from the broad pytest step,
   and uploads only the two synthetic JSON reports even on failure.
   Gate commands are validated locally; a remote Actions run remains pending
   commit/push. Independent authorship/validation requirements remain separate.

**Exit:** at least 30 independently authored attacks actually execute,
including own-data, memory, and approval cases; reported E2 scope matches
implemented checks. Claim the offline subset and scoped local runtime evidence
separately; independent frozen E2 evidence and a remote CI run remain open.

### Wave 4 — Frozen evaluation claims (P0 hygiene, then P1 results)

1. Maintain at least 60 synthetic personas overall (about 20 development and
   at least 40 held-out); the current 43 development cases exceed the guide's
   approximate development count. Keep related variants together when
   splitting. Do not generate or access held-out cases until custody and freeze
   gates are approved.
2. Verify the simulated citizen uses a different model with a hidden profile
   card and answers only what the user asks; prevent the agent/evaluator from
   seeing the hidden card.
3. Obtain two independent teammate labels for each persona against every
   candidate scheme, record disagreements, and replace copied-label κ.
   If using an LLM judge, use a different model family, calibrate against at
   least 20 human-labelled outputs, and report Cohen's κ.
4. Add a forced-C0 path (fixed workflow/single retrieval prompt without agent
   decisions) and compare C0, C1, and C2 on the same cases, model, tools, and
   budget under the same freeze pins and safety controls.
5. Add E4's isolated, non-authoritative LLM eligibility comparison and
   fixed-vs-planned question-order ablation.
6. Only after the freeze and custody gates, run at least 40 held-out cases
   through the approved final evaluations three times and report spread.
   Never commit held-out case files or tune against their results.
7. Complete E3 before/after evidence under identical pins; use human-reviewed
   lessons, include lesson-generation cost, and report lessons that worsened
   results. Run held-out extraction only when separately authorized.
8. For every configuration, report task success, policy violations, attack
   success, legitimate-work false blocks, cost per case, median and p95
   latency, errors, failures, and timeouts. Record commands, artifacts, and
   input hashes so results can be reproduced.
9. Keep the 15-gold-scheme target as a separate data workstream; report the
   current four-package coverage honestly.

**Exit:** every PDF-facing number links to frozen inputs, an evidence artifact,
an owner, and an honest claim status; retrieval and agent evaluation reports
meet the PDF's denominators, label/calibration protocol, and metric checklist.

### Wave 5 — Monitoring deployment evidence (implementation present; P1 handoff)

The local working tree records metrics only through OpenTelemetry. The
Prometheus implementation and `/metrics` route have been removed. OpenTelemetry
metrics export through Azure Monitor when `APPLICATIONINSIGHTS_CONNECTION_STRING`
is configured. A read-only shared-dev check found `scheme_saathi.*` AppMetrics
from the older `git-13dde6b37e3a` image, but the current branch is not deployed,
and no Azure metric alert rules were configured. Managed Grafana dashboards and
alerts are Phase 6 work on `feature/monitoring-otel-on-supervisor`; the live
dashboard and alert proof remain open.

1. Check that journey results are not counted repeatedly across turns and that
   labels/values are safe and bounded. Verify dashboard coverage for questions
   per conversation, can't-tell rate, pending approvals, masked-ID hits, and
   cost per conversation.
2. Configure the connection string only through the deployment secret store;
   never commit or print it.
3. In the shared environment, verify data arrives in the intended
   Application Insights resource, and that the Managed Grafana dashboard reads
   it. Include a sanitized query and timestamp as evidence.
4. Demonstrate a working alert and dashboard. Existing configuration files and
   local tests alone do not satisfy this gate.
5. Verify exported telemetry contains no prompts, applicant facts, return
   codes, or other sensitive values.

**Exit:** Role 6 supplies shared-environment export and alert evidence.
Until then, monitoring is implemented locally but is not a completed deployment
claim.

## 3. Dependencies and stop conditions

- Waves 0-1 precede any paid or final held-out run.
- Wave 2 precedes memory/approval red-team claims and the memory-on/off report.
- Wave 3 must report actual execution rather than suite size.
- Wave 4 runs only against the approved freeze; held-out exposure requires
  reclassification and replacement.
- Wave 5 may proceed in parallel, but it does not authorize or unblock paid
  evaluation by itself.
- Role 1 must decide TTL, labels, and thresholds; Role 2 owns memory semantics;
  Role 3 owns C0/C1 and question-order changes; Role 4 owns guardrail fixes;
  Role 5 owns evaluation/attack evidence; Role 6 owns deployment monitoring.
