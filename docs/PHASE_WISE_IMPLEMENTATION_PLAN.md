# Scheme Saathi: phase-wise implementation plan

This plan splits the redesign in
[END_TO_END_IMPLEMENTATION_PLAN.md](END_TO_END_IMPLEMENTATION_PLAN.md) into
phases. Each phase changes the backend **and** the UI together, so we always
have a working end-to-end app to click through.

> **Replanned on 2026-11-04 for data-driven scheme onboarding.**
> Keep the working foundation; repair the missing agent/control layers.
> This is the single application phase schedule. The end-to-end plan defines
> architecture; catalogue and retrieval plans are parallel workstreams.
> Repair batches remain the schedule; implementation progress is recorded at
> the relevant phase gate and does not substitute for manual acceptance.

## In simple words

**Goal: prepare a reviewed scheme package, add it, and let the existing app
ask its questions and check its rules without scheme-specific Python changes.**

Today, new passages and document lists can be loaded, but household facts and
questions still have a fixed set of fields. A scholarship needing exam marks
cannot work just by adding its passages. We will make the common code read
fact definitions, questions, checks and form fields from reviewed data.

For example, a clearly synthetic scholarship package can define exam marks
as a number from 0 to 100 and supply its three-language question and reviewed
test rules. The same intake, engine, document tools and draft flow must then
work without adding a scholarship branch in Python.

**This is a plan, not an implemented feature.** Keep the tested foundation:
the latest offline suite passed 361 tests, including two integrated UI flows.
Those results cover the current fixed-field implementation, not this redesign.
The LLM still never decides eligibility or approves a form.

**Next:** revise Phases 1–4 in order using the gates below, then test them
together before starting Phase 5. Existing walkthroughs explain the code as
built; update and independently review each when its implementation changes.
No commit, push, paid evaluation or deployment is authorized by this plan.

## How each phase works

1. Build the backend and UI changes for the phase on branch
   `feature/supervisor-redesign`.
2. Add tests for the new behaviour. The full suite must pass
   (`python -m pytest -q`).
3. Run the app locally (FastAPI + Streamlit).
4. Test the phase in the UI using its checklist below.
5. Only if the UI behaves as expected, mark the phase done and start the next
   one.

For this redesign, follow Phases 1–4 in order, preserving the approval/budget
repairs already tested. The earlier R0–R6 table is repair history and remaining
capstone scope, not a second order that skips the new data-driven gates.
Source curation and independent test
labelling may run in parallel. Each sign-off records commit, tester, scenario,
expected/actual outcome and whether it was automated, manual or live-model.
No live paid evaluation or deployment happens solely because it is in this plan.

Rules for every phase:

- Eligibility verdicts, question scoring and approval checks stay in code. The
  LLM never decides eligibility.
- Data stays synthetic. The mock portal never contacts a government service.
- Nothing is deployed unless the team asks for it.

## Phase overview

| Phase | Backend | What you see in the UI | Status |
|---|---|---|---|
| 1. Base | Reviewed fact registry and versioned scheme bundles; deterministic typed rules | Both pilots keep their results; new supported facts load from data | Registry foundation implemented; independent code and walkthrough reviews passed after corrections; human metadata/browser acceptance still open |
| 2. Supervisor and intake | Data-defined questions, validation, confirmation and persistent budgets/hooks | New scheme questions appear without custom UI code | Registry-backed single-scheme intake/UI implemented for explicit development-bundle injection; automated gates pass, manual acceptance remains open |
| 3. Multi-scheme and replan | Meaning-aware fact sharing, discovery and version-bound corrections | Answer once only when meaning matches; changed definitions trigger review | Registry multi-scheme sharing/corrections and monotonic dependency refusal implemented with explicit offline development injection; independent and manual acceptance remain open |
| 4. Documents and approval | Registry-aware document conditions and data-defined mock form mapping | A new scheme reaches exact draft review and practice receipt | Generic development mapping and integrated synthetic UI proof implemented; bundle-scope repair passes automated checks; independent/manual gates remain open |
| 5. Guardrails, memory and evaluation | Registry-aware privacy/memory; full safety, extractor/Reflexion and E1–E4 | Safe referral and consent/forget for supported facts | Paused until revised Phases 1–4 are accepted |
| 6. Operations and final evidence | Validated package publication, migrations, operations and final evidence | New approved bundle works after restart/install | Existing Azure deployment is not proof of these release gates |

### What a prepared scheme package means

Passages alone are not a complete package. Preparation supplies:

| Part | What the common code reads |
|---|---|
| Fact definitions | Stable ID, meaning, person/family scope, answer type, units, validation, privacy policy and version |
| Questions | Reviewed English/Hindi/Marathi prompts, help and enum-choice labels; no executable instructions |
| Rules | Approved sources and deterministic checks referring to registered fact IDs |
| Documents | Versioned shared checklist, evidence, alternatives and supported conditions |
| Mock form | Approved field labels and mappings from confirmed facts, with explicit missing-field behavior |
| Bundle record | Scheme ID and exact compatible versions/hashes of all the above, plus review state/currentness |

Use a shared fact registry rather than copying slightly different versions of
the same question into every scheme. A scheme declares which definitions it
uses. A family-income fact must never silently become personal income.

**Supported does not mean unlimited.** Plan for boolean, date, integer,
decimal and finite-choice answers; bounded text is for approved display/form
fields, not arbitrary policy calculations. Keep a small explicit list of
operators and code-owned derived calculations (such as age). No Python, SQL,
`eval`, arbitrary formulas or LLM-decided rules in packages. A package needing
an unsupported calculation is rejected for developer review, not guessed.

### Proof required across the revised phases

Use the two reviewed pilot packages unchanged as regression baselines. Add a
third **synthetic development-only** scholarship requiring a new numeric fact
and choice question through data files only. It must not appear as an official
scheme in the normal catalogue or count toward gold/source targets.

After the common runtime changes, adding that package must need **no further
edits to `src/`**: load, ask/validate/confirm, share or distinguish facts,
evaluate, correct, check documents, draft, approve and return one mock receipt.
Record the data-only addition separately so this promise is testable.
Reject a malformed/unsupported package without exposing its tools or claiming
the scheme is supported. Preserve pilot verdicts, citations, unknown handling,
bounded calls, exact approval, stale cancellation and scoped deletion.

### Gate reconciliation — 2026-11-03

Later implementation started before Phase 1 and 2 UI sign-offs were recorded.
This does not satisfy the phase-order rule above. Keep the existing work, but
do not treat implementation or automated tests as manual acceptance. Pause new
phase work until the earlier UI gates have been checked and signed off in order.

Local compilation and the full offline suite passed on 2026-11-03:
`python -m compileall -q src` and
`python -B -m pytest -q -x -p no:cacheprovider --disable-warnings`
(196 passed). This was the local result before commit `770bc5c`.
The initial GitHub validation attempt stopped on a dirty worktree. Subsequently
`770bc5c` was pushed and
[run 41638806677](https://github.com/Roy-developer/scheme-saathi-capstone/actions/runs/41638806677)
validated and deployed it to both apps. The earlier blocker is historical,
not the current deployment status. Manual acceptance and architecture
compliance remain open despite that successful deployment.

### Planning review coverage

Reviewed the original capstone PDF (pp. 1–3, 5–8), the complete local
`Scheme_Saathi_Roles_and_Work_Plan.pdf`, the end-to-end and phase-wise plans,
the catalogue/delivery plan, retrieval backlog, frontend prototype contract
and page-referenced guide. Checked the Phase 1–4 walkthroughs for scope/status
claims and the relevant code/tests for the gaps below. Walkthroughs describe
their implementation slices; their old "uncommitted/not deployed" snapshots
do not override the deployment record above. Setup instructions and policy
review records are not competing implementation schedules.

### Verified gaps and acceptance evidence

These are planning/implementation gaps, not claims that missing tests prove
the current behavior fails. "Partial" means useful code exists but the stated
capstone gate is not met.

| ID | Gap and current evidence | Repair and proof required | Phase / roles |
|---|---|---|---|
| G01 | Bounded supervisor/intake, eligibility and document/application specialist loops are implemented and covered by offline tests; independent manual/live acceptance remains open. | Preserve tested loops, typed handoffs and C0 while adding registry-aware inputs/actions. Prove the new data-only flow and complete the remaining acceptance gates; do not rebuild existing agents. | 2–4 / 3, 4 |
| G02 | Four purpose-specific MCP services and a separate FastAPI mock portal now have automated discovery, routing and permission coverage; manual UI acceptance remains open. | Preserve typed outputs/errors/read-write schemas; complete manual service and portal acceptance and record reviewers. | 1–2 / 4, 6 |
| G03 | Phase 3 now revokes persisted unsubmitted approvals, binds monotonic profile/document/rule versions and blocks unreconciled writes. Submitted receipts remain history. | Independently verify still-eligible/unknown/A→B→A, persistence failure, restart and concurrent submission tests; complete manual acceptance. | 3–4 / 3, 4, 5 |
| G04 | Per-fact attempts, model/token/action/step reservations and independent search counters now survive corrections, same-ID restart and interrupted nodes in separate SQLite checkpoint streams. | Independently verify crash-before-node-return and reservation-write-failure cases; new IDs start independently. | 2–3 / 3, 5 |
| G05 | Synthetic name/date comparison and discrepancy/referral behavior use one typed, versioned checklist loader shared by both document tools. Pilot data is explicitly demo-only; no official source evidence has been prepared or approved. | The separate human data workstream must collect source passages, review each interpretation, and record exact-content approval before source-backed requirements can activate. | 4 + data workstream / 1, 2, 3, 4 |
| G06 | `test_document_agent_blocks_application_writes_but_binds_report` (`tests/test_application_tools.py`; earlier name `test_document_agent_blocks_application_without_portal_access`) already covers missing/unknown/**mismatch** at graph level. Unknown document status is not unknown eligibility. | API/UI mismatch-to-resolution tests; explicit `need_more_information`, `information_only`, `not_eligible` and `tool_error` block draft/approve/submit. Include initially approved drafts becoming uncertain. | 3–4 / 5 with 3, 4, 6 |
| G07 | Document/checklist dependency invalidation and stale refresh are implemented and covered by offline correction/integration tests. | Extend binding to registry/bundle/form versions; preserve fresh review after changes and complete manual/operational acceptance. Refresh must never show stale approval as valid. | 4 / 3, 4, 6 |
| G08 | Exact revision/fingerprint approval, provisional 15-minute expiry, one-use submission and stable retry recovery are implemented and tested offline. | Ratify expiry policy; preserve atomic authorization consumption and identical-retry receipts through the redesign. Complete outstanding process-kill/multi-worker acceptance; never auto-approve during recovery. | 4 / 3, 4, 5 |
| G09 | Confirmed category/age hints now trigger bounded rediscovery; results are deduplicated and additions/overflow/failures are traced. The existing profile has no state/gender and retrieval has no age/gender filter. | Do not invent unsupported filters. Language uses explicit locale; state/gender filtering needs reviewed schema/corpus work, not inference from widow status. Complete independent coverage and manual acceptance. | 2–3 / 2, 3 |
| G10 | Interview questions/plan goals and locale/mode/Citizen/CSC acknowledgement now have EN/HI/MR contracts and automated coverage; independent language review remains open. | Complete reviewed wording throughout Phase 4 controls and confirm that the citizen, not the operator, provides consent and approves drafts. Same confirmed persona gives the same code verdicts. | 2–4, 6 / 1, 3, 6 |
| G11 | Demo notice and short-term SQLite checkpoints are not governed long-term household memory. | Consent flag, pseudonymous household ID, expiry, scoped reads/corrections/deletion; short-term trimming; written policy and memory-on/off comparison. | 5 / 2, 4, 5 |
| G12 | Review assistance and two runtime packages do not establish the rules-extraction signature or 15 gold schemes. | 40–60 reviewed sources; 15 approved gold schemes; extractor scored by field/operator/value/clause, reviewed development-only Reflexion lessons, freeze and independent held-out comparison. | 5 + data workstream / 1, 2, 3, 5 |
| G13 | Unit tests and 43 development queries are not a 60-persona evaluation or C0/C1/C2 comparison. | One config-driven harness for E1–E4, independent simulated citizen, calibrated judge, cost/latency/failure reporting and protected labels. Keep paid runs separately approved. | 5 / 5 with all roles |
| G14 | Phase 2 now has pre-choice masking, actor/action permissions, durable budgets, output validation and scrubbed trace metadata; complete guardrails/referrals remain open. | Complete the threat model, guardrails and 30+ independent attacks in Phase 5, with clean-case false blocks. | 2 then 5 / 4, 5, 6 |
| G15 | Model/prompt versions and SQLite restart persistence are covered offline; streaming, Compose, operations dashboard/alerts and CI evaluation thresholds remain open. | Add the remaining release operations and preserve restart/revision evidence. | 2, 6 / 6 |
| G16 | Earlier manual gates unsigned; different documents had conflicting phase numbers and stale status/metrics. | One phase schedule, named commit/tester evidence, no retroactive sign-off; historical docs/measurements clearly labelled. | All / all roles |

### Earlier repair batches and remaining capstone work

The data-driven gates in Phases 1–6 now control the build order. Keep the
repairs below as safety requirements and historical context, not a claim that
the new generic data layer already exists.

R1–R4 core code and offline checks are already implemented. Their remaining
work is preserving those guarantees through the registry redesign and closing
the explicitly outstanding manual/source/operational gates, not rebuilding
specialists or approval controls.

Roles below are responsibilities, not assigned people. Agree owners/backups,
dates, model IDs, numeric budgets, approval expiry and evaluation thresholds
before the corresponding implementation or paid experiments.

| Batch | Work | Prerequisite | Exit evidence |
|---|---|---|---|
| R0: agree the correction | Approve this gap register and contract changes; preserve C0; assign owners and development-only fixtures. | Source review (this document) | Reviewed examples for dependency versions, stale approval, tool permissions, referral and budgets. No implementation claimed here. |
| R1: repair existing state | G03/G04/G06/G07/G08: revoke stale approvals, preserve counters, define current document binding and fail-closed recovery. Add focused tests first. | R0 | Fact A→B→A never revives approval; still-eligible/unknown corrections and changed document reports block old submission; valid exact retry stays idempotent. |
| R2: safe agent foundation | G01/G02/G14/G15: split services/portal, enforce action-level permissions, mask before models/traces, persist budgets, configure bounded ReAct; initial profile intake. | R0; R1 before new write-enabled loops | Denied tools/actions and exhausted budgets cannot execute; fake-model tests drive multiple allowed choices; Phase 1 then 2 revised/manual gates pass. |
| R3: complete multi-scheme | G09/G10: analyst ReAct, supported filters, bounded rediscovery, shared meaning/scope, correction notices and budget inheritance. | R1, R2; reviewed development sources | Added/removed/information-only candidates, correction and tool failures appear consistently in trace/UI; Phase 3 gate passes. |
| R4: complete applications | G05–G08/G10: document/application ReAct, sourced synthetic comparison, mismatch/referral, fresh approval, expiry/replay and crash recovery. | R1, R2, R3; reviewed document evidence | Full Phase 4 API/UI scenario matrix below passes, including live process restart and stale UI recovery. |
| R5: prove the capstone | G11–G14: memory, extractor/Reflexion, completed guardrails, governed data and E1–E4. | R4 for full journey; curation/independent labels can start after R0 | Frozen configs/data/lessons; reviewed report with failures/costs, memory comparison and agreed CI metrics. |
| R6: release evidence | G10/G15/G16: full Compose, streaming, storage, dashboard/alert, CI threshold, three-language Citizen/CSC final demo and documentation. | R5; earlier phase sign-offs | Clean-machine start, recovery/deletion demo, alert, failed CI example and final sign-off at exact commit. |

Do not delete the deployed baseline, weaken tests, change reviewed rule packages
without evidence/sign-off, inspect held-out cases, or add repeated LLM calls just
to make a specialist appear agentic. No source/memory/evaluation deliverable is
counted complete because its name appears in a plan.

The table below maps the Phase 1 and 2 checklist items to existing automated
evidence. Streamlit AppTest uses mocked backend responses; graph/API tests
exercise separate layers. Neither is a manual browser walkthrough of the
running UI and API together. All nine manual checklist items remain pending.

| Checklist item | Existing automated evidence | Manual check still needed |
|---|---|---|
| Phase 1: widow search and result | `tests/test_ui_app.py::test_evaluating_result_without_prepared_draft_does_not_raise` | Search, choose IGNWPS-MH and compare the displayed result with its synthetic baseline. |
| Phase 1: PM-KISAN search and mock notice | `tests/test_ui_app.py::test_pmkisan_continue_opens_chat_that_asks_then_shows_verdict`; `tests/test_api_eligibility.py::test_pmkisan_journey_uses_graph_and_mcp_rule_engine` | Complete the running search/chat flow and inspect the mock/currentness notice. |
| Phase 1: failed PM-KISAN rule | `tests/test_journey_graph.py::test_failed_rule_stops_the_questions_early`; `tests/test_api_eligibility.py::test_pmkisan_evaluation_flags_reported_2020_exclusion` | Confirm the UI shows `not_eligible` with the deciding rule ID. |
| Phase 1: widow draft, approval and submission | `tests/test_api_applications.py::test_synthetic_application_requires_exact_approval` | Complete the checklist, review, approve and submit through the UI; confirm the mock receipt. |
| Phase 2: one question at a time | `tests/test_journey_graph.py::test_interview_asks_one_question_at_a_time_until_eligible`; PM-KISAN AppTest above | Answer questions in the running UI for both schemes. |
| Phase 2: plan updates | `tests/test_journey_graph.py::test_interview_plan_is_visible_while_waiting`; PM-KISAN AppTest above | Inspect the plan after each answer and when eligibility finishes. |
| Phase 2: stop at a verdict with evidence | `tests/test_journey_graph.py::test_failed_rule_stops_the_questions_early`; `tests/test_api_eligibility.py::test_response_includes_official_source_citation` | Confirm questions stop and the UI displays rule IDs and evidence. |
| Phase 2: unknown answers terminate | `tests/test_journey_graph.py::test_dont_know_is_not_asked_again_and_ends_with_missing_facts` | Answer "I don't know"; confirm no loop and visible missing facts. |
| Phase 2: refresh resumes | `tests/test_ui_app.py::test_refresh_restores_saved_conversation_from_url`; `tests/test_journey_graph.py::test_saved_interview_can_be_reloaded_after_refresh` | Refresh the browser during an interview and continue from the same question. |

---

## Phase 1 — Base

**Goal:** one shared foundation, so both schemes follow the same path.

### Revised work: facts and rules loaded from reviewed data

**Implementation evidence (2026-11-04):** typed registry/store, shared evaluator,
legacy pilot adapter and pinned bundle startup checks are implemented. The
builder reports 86 focused and 375 full offline tests passing. Independent
review found a legacy-label activation bypass; it was repaired with exact
two-pilot bindings and regression tests. Independent follow-up and parent
verification each passed all 14 registry tests. Compile and diff checks pass;
reviewed pilot rule JSON is unchanged. The walkthrough was written by
Claude Sonnet 5.5 and reviewed/corrected by GPT-5.6-Luna. These are local
Python 3.14 results, not Python 3.12 CI or browser acceptance.

New fact/question/privacy review metadata remains pending. Novel packages
remain development-only; approved new-package activation is not implemented.
The synthetic proof uses the shared MCP evaluator, not dynamic UI intake.
Phase 2 implements that next; source approval and later publication gates
are not waived.

- Define strict fact-registry and scheme-bundle models. Validate IDs, types,
  units, bounds, choices, source links, supported operators, scope and exact
  referenced versions before activating a package. Reject unknown keys/IDs,
  duplicate definitions, incompatible versions and derived-fact cycles.
- Replace fixed eligibility fact literals/attribute lookup with a typed fact
  store validated against the loaded registry. Do not replace validation with
  an unchecked dictionary or coerce unknown answers into false/zero.
- Keep approved pilot rule JSON unchanged. A reviewed migration/mapping of
  their current names to registry IDs must preserve every result and citation.
  Plan an additive API/checkpoint adapter; reject ambiguous mappings safely.
  Do not erase existing saved journeys or approvals during migration.
- One common evaluator handles explicitly supported comparisons and derived
  calculations. Validate type/operator compatibility, decimal units and
  boundary behavior. A novel calculation still requires code and tests.
- Keep four MCP services and permission checks. All services load the same
  compatible bundle versions; invalid required startup data fails readiness.

**New Phase 1 gate:** offline tests load a synthetic scheme with a previously
unsupported numeric fact using data only, exercise eligible/not eligible/
unknown boundaries, and reject malformed or unsupported definitions. Existing
pilot verdicts/citations and strict permissions remain unchanged. This gate
does not yet claim the new scheme has passed the UI/application flow.

Code walkthrough: [PHASE1_CODE_WALKTHROUGH.md](PHASE1_CODE_WALKTHROUGH.md).

Existing foundation to preserve (the new registry gate above is additional):

Backend:

- Add the shared typed models: `Plan`, `PlanStep`, `HouseholdProfile`,
  `CandidateVerdict`, `Handoff`.
- Make one rule package schema that fits both widow pension and PM-KISAN. Each
  package lists its `required_facts`.
- Move PM-KISAN into the common rule engine. Remove the PM-KISAN-only
  evaluator and route; the generic `/{scheme_id}/evaluate` route now serves
  every scheme through MCP.
- Send PM-KISAN through the MCP `rule-engine` tool and the LangGraph journey,
  the same as widow pension.

UI:

- Keep the current screens.
- PM-KISAN eligibility calls the journey API instead of the direct endpoint.

UI test checklist:

- [ ] Search "widow pension", choose IGNWPS-MH, check eligibility. Result
      matches today's result.
- [ ] Search "farmer income support", choose PM-KISAN-IN, check eligibility.
      Result matches today's result, including the mock/currentness notice.
- [ ] A failed PM-KISAN rule still shows `not_eligible` with the rule ID.
- [ ] Draft, approve and mock submit still work for widow pension.

Revised foundation gate (G02): preserve rule verdicts while adding four
purpose-specific MCP services, typed success/error schemas, read/write/action
permissions and a separate mock portal service over its own DB. Publish the
tool inventory and test each tool. The generic PDF minimum is three servers;
the Scheme Saathi design names four. Four modules on one server do not pass.

Done when: the new Phase 1 registry gate, these contract/tool checks and all UI items pass; the UI journey
uses the common graph without removing the compatible generic evaluate API.

Automated G02 inventory and evidence: [MCP_TOOL_INVENTORY.md](MCP_TOOL_INVENTORY.md).
API startup discovers four separate stdio processes and checks their exact tool
sets; the mock portal runs as a separate FastAPI process with its own DB. Focused
tests cover discovery, typed errors, invalid inputs, routing and portal HTTP
storage. The manual UI checklist above is still unchecked; no browser acceptance
is claimed.

---

## Phase 2 — Supervisor and intake

**Goal:** the supervisor plans and delegates; intake asks questions instead
of receiving a full fixture profile.

**Automated implementation evidence (2026-11-04):** the journey graph now
accepts the validated fact registry and bundle bindings. A non-legacy bundle
uses versioned typed facts in the actual interview/checkpoint/eligibility path;
localized question metadata drives boolean, date, integer, decimal, and
finite-choice widgets and strict parsing. Numeric bounds/units and stable
choice codes are validated by the registry. Unknown answers remain declined,
and incompatible saved registry versions stop rather than reinterpret values.
The existing pilot profile/question path and evaluator API remain compatible.
New-bundle schemas with pending privacy review fail closed for model
disclosure: initial descriptions are not passed to extraction, and direct
manual answers are used. Dynamic model extraction, multi-scheme sharing and
correction are not claimed here; they require reviewed privacy policy and
Phase 3 work. Development-only synthetic loading is explicit test injection,
not normal production activation.

**Review closure:** code reviewers verified the repaired decimal wire format,
unambiguous choices, validation before checkpoint resume, and exact decimal
UI submission. The builder's full offline run passed 385 tests; parent
registry/question checks passed 48 tests after the final changes. Compile and
diff checks pass. Sonnet 5.5 wrote the walkthrough and GPT-5.6-Luna reviewed
it; a final stale decimal-widget checklist claim was corrected. Manual browser,
native-language, human metadata review and Python 3.12 CI remain open.

### Revised work: questions and answer checks loaded from data

- Generate question widgets/parsers from the registered type and reviewed
  three-language question data. Number bounds/units and choice codes are
  validated by code; labels do not change the stored meaning.
- Extract only allowed, necessary facts for the current tasks. Validate model
  proposals against registered IDs/types and ask for confirmation before
  saving. Reject invented fields and silent overwrites.
- Apply consent, masking and trace/log restrictions from an approved fact
  privacy policy **before** sending any newly introduced field to a model.
  A new schema entry alone never authorizes sending sensitive data.
- Keep bounded ReAct, typed handoffs, deterministic question scoring and
  durable budgets. Adding facts never resets attempts; "don't know" stays
  unknown. Resume a saved conversation with its compatible definition version
  or request a safe migration/reconfirmation.

**New Phase 2 gate:** the synthetic scholarship's number and choice questions
appear from data, validate range/units/choices, support confirmation where
the model proposes a fact and unknown answers, and resume after refresh.
Test invalid model proposals and privacy-denied fields without paid calls.
No scheme-specific question branch may be added to pass the test.

Automated offline evidence: the injected development-only scholarship reaches
the journey's registry questions and deterministic evaluator, repeats an
out-of-range answer, resolves localized choice labels to stable codes,
reloads the pending question, retains a declined number as missing, and rejects
a changed registry version. A model spy confirms the pending-policy household
description is not disclosed. AppTest covers number and choice widgets. The
legacy agent proposal/confirmation tests remain in place. These checks are not
manual browser acceptance, live-model testing or independent language review.

Backend:

- Supervisor node builds a `Plan` (profile → candidate schemes → rules →
  documents → draft) and hands steps to specialists with typed `Handoff`
  messages.
- Intake loop: code picks the next registry fact needed by an unresolved rule.
  Existing pilot profiles retain the bounded model-assisted extraction and
  confirmation path; a new field with unapproved privacy metadata stays on
  deterministic manual questions and is not disclosed to a model.
- The graph pauses after each question and resumes from the checkpoint when
  the user replies.
- Stop asking when verdicts are settled or the user says they don't know.
- New API: `POST /journey/{id}/messages`, `GET /journey/{id}`.
- Repaired architecture: model-proposed, code-validated supervisor planning
  and a bounded intake ReAct specialist, not merely a renamed Python node.
  Extract/confirm facts from the initial description as well as later replies.
- Establish input masking, per-agent/action permissions, durable budgets and
  scrubbed model/tool traces before enabling new agent tool choices. Invalid
  model output, denied actions and exhausted limits stop safely.
- Keep question scoring, fact validation and unknown handling in code.
  Persist per-fact interpretation attempts and conversation budgets across
  correction, same-ID restart, refresh and process restart.

UI:

- A chat box replaces the fixture profile form.
- A plan panel shows the steps and which one is active.

UI test checklist:

- [ ] After choosing a scheme, the app asks one question at a time.
- [ ] Each answer updates the plan panel.
- [ ] Questions stop once the verdict is settled; the verdict shows with rule
      IDs and evidence.
- [ ] Answering "I don't know" does not loop forever; the result says what is
      missing.
- [ ] Refresh the page; the conversation continues from the same point.

Additional gate:

- [x] An initial synthetic household description produces validated,
      confirmed facts; a model cannot silently overwrite a confirmed fact.
- [x] A fake-model trace demonstrates action → tool observation → next action
      or typed handoff; invalid/denied/over-budget actions make no tool call.
- [x] Correcting an unrelated answer does not grant another LLM interpretation
      for an already-attempted fact; new facts/new conversation IDs work.
- [ ] Model IDs/prompts/limits are versioned; paid smoke-test budget is agreed.
- [ ] Reviewed EN/HI/MR questions and plan text preserve the confirmed fact
      meanings; mode/locale reach the backend through a reviewed contract.

The checked items above have automated offline fake-model/SQLite coverage only.
They are not manual browser acceptance, live-model evaluation or independent
language review; those gates remain open.

Done when: these checks pass, no fixture profile is needed to reach a verdict,
and the Phase 1 gate is signed off.

Code walkthrough for new developers: [PHASE2_CODE_WALKTHROUGH.md](PHASE2_CODE_WALKTHROUGH.md)
(updated for the registry-backed intake; no independent walkthrough review is
claimed yet).

Historical Phase 2 slice (not a description of all current code): originally
there were no interview LLM calls; Phase 3 added confirmed answer interpretation.
The files below are reusable, not evidence that ReAct has been completed.

- `src/workflow/supervisor.py`: builds the plan and moves it forward when a
  specialist reports back.
- `src/workflow/question_picker.py`: picks the next missing fact by walking
  the rule package in order (the first rule that still needs a fact wins).
- `src/workflow/questions.py`: fixed English question text and plain-code
  answer reading (yes / no / don't know and day-first dates). The LLM will
  phrase questions and read free text in a later step.
- `src/workflow/journey.py`: supervisor → intake → `ask_user` (`interrupt()`)
  → intake → … → eligibility → supervisor. `resume_journey` continues a paused
  conversation; `get_journey` reloads it.
- API: `POST /api/v1/journey` with `action="interview"`,
  `POST /api/v1/journey/{id}/messages` (409 when nothing is waiting) and
  `GET /api/v1/journey/{id}` (404 when nothing is saved).
- UI: chat with a plan checklist for PM-KISAN; widow pension offers the
  chat or a preset example person (still needed for the draft until
  Phase 4); the URL keeps the conversation ID so a refresh restores it.
- Original limits: English questions/goals and no chat draft. Phase 4 later
  added chat drafting; EN/HI/MR parity and the ReAct repair remain open.

---

## Phase 3 — Multi-scheme and replan

### Revised work: share facts only when their meanings match

- Share a registered ID only when meaning, applicant/family scope, units,
  time period and compatible definition version match. Different scope means
  a different ID even if the labels look similar.
- Derive missing facts and stable question order from loaded packages.
  Discovery accepts supported confirmed filters only; adding a rule package
  never proves retrieval finds it or that a person qualifies.
- Corrections work for all registered types, including number/date/choice
  and explicit unknowns. Recompute affected rules in code and cancel affected
  unsubmitted approvals; conservative conversation-wide cancellation remains
  acceptable until dependency mapping is proven.
- Pin used fact, rule and bundle versions. A changed definition/meaning or
  withdrawn approval stops use of the old result and requires review. A file
  update must not silently reinterpret saved answers. Budgets stay consumed
  across changes/restarts and A→B→A never revives approval.

**New Phase 3 gate:** two schemes share one genuinely common fact once;
personal/family or different-period facts are asked separately. The data-only
scheme is discovered in controlled offline integration, evaluates correctly
and supports typed correction/restart. Unknown rules remain information-only;
errors, limits and changed definitions are visible, never invented verdicts.

**Revised implementation evidence (2026-11-04, builder only):** the existing
journey/API now interviews multiple registry bundles using shared missing-input
counts with stable rule/candidate ordering. Tests add synthetic bundles through
data files only, share exam marks once, and separately ask identically labeled
personal/prior-period and family/current-period income. Injected synthetic search
results exercise search → API interview → typed MCP-core verdicts → corrections;
this is explicitly not live/corpus retrieval evidence. Registry intake and
eligibility remain deterministic, without disclosing answers or derived verdicts
to a model. Explicit validated legacy mappings support pilot co-interviews,
without changing either reviewed pilot package or activation pins.

Content-bound registry/bundle/rule snapshots and a persistent review latch stop
reuse after meaning/scope/period/review/rule/bundle changes or withdrawal. The
safe localized refusal preserves saved facts, clears exposed stale results and
revokes unsubmitted approvals; A→B→A does not clear the latch. A new conversation
requires explicit reconfirmation; no automatic migration or generic new-scheme
form flow is claimed. Reopened SQLite and the real offline portal verify that a
still-eligible decimal/date correction and a changed definition cancel an
approved pilot draft. The UI uses registry labels for generic corrections.

Builder regression selection passed **101 tests** before the final
registry-model-disclosure guard was added. Final validation is recorded in
`CONTRIBUTIONS.md`; no independent review, browser/manual multilingual acceptance,
source/privacy approval, native CI or live-model acceptance is claimed here.

**Independent-review follow-up (2026-11-04):** the reviewer reported three medium
defects, not acceptance. Development bundles now retain typed intake despite
legacy mappings; combined typed/mapped-profile answers validate before resume
or correction writes; and both intake paths share the existing bounded
confirmed-fact discovery before registry question selection. Six new regression
cases pass, the focused registry/discovery/graph/questions/UI selection passed
**130 tests**, and the final single serial full offline suite passed
**401 tests in 219.49s**. Compile and diff checks pass. Both pilot rule hashes are
unchanged. Independent re-review and the remaining manual/source/privacy/CI
gates remain open; no walkthrough update or Phase 4 generic form work is included.
The Phase 3 walkthrough was later updated by its author (see CONTRIBUTIONS);
that guide is **pending independent review**.

**Earlier legacy Phase 3 evidence (historical):** the reviews and test counts
below concern the earlier fixed-field foundation, not independent review of the
registry revision above.

The interrupted Phase 3 implementation has been resumed without replacing the
Phase 1–2 work. `eligibility_agent.py` now runs a bounded specialist loop with
typed rule observations and model-selected verdict/clarification/referral
handoffs. A denied or malformed action never calls the rule tool; the model
cannot supply a verdict. The required deterministic C0 path remains.

Confirmed widow/landholding facts and calculated age supply retrieval query
hints; only supported search arguments are sent. Locale selects language.
There is no confirmed state/gender field or age/gender retrieval filter, so
none is invented. Multi-scheme description extraction may propose these two
discovery facts, but search waits for the person's confirmation. A relevant
confirmed change triggers budgeted rediscovery, deduplicates additions, and
keeps unknown-rule schemes information-only. Four actual search attempts
(including retries) and 20 processed candidate IDs are explicit limits;
overflow IDs, source passages and failure/referral notices remain visible.
Shared questions retain deterministic meaning/scope and stable order.

Single- and multi-scheme corrections, including explicit unknown answers,
revoke all conversation unsubmitted approvals in the portal transaction.
Profile versions and per-scheme document/rule versions never roll back.
Restoring a fact does not restore approval. Portal transactions plus
per-conversation graph serialization prevent submission during invalidation;
expected profile versions reject stale work at the write boundary. A failed
checkpoint or portal transition holds writes closed pending reconciliation.
Submitted receipts remain history.

Model/token/action/step reservations, search attempts and once-per-fact
interpretation attempts are checkpointed **before** dispatch in a separate
budget stream, so a failed node cannot refund work on restart. Tests now
disable dotenv/real credentials/model downloads before collection and isolate
integration databases from demonstration runtime data.

Offline behavior tests cover observations, denied/malformed choices, actual
discovery coverage/overflow/errors, approved-draft corrections and A→B→A,
unknown restoration, persistence failures, SQLite restart and concurrent
submission. English/Hindi/Marathi discovery/stale/referral notices reach the
API and UI; correction refreshes cached portal drafts and removes stale submit
controls. Independent offline verification and the separate walkthrough
readability review passed. Manual browser and independent language acceptance,
and an approved live-model smoke, remain gates.
Earlier live retrieval diagnostics are not acceptance evidence for this repair
or catalogue-wide coverage. Phase 4 specialists are not implemented here.

Verification record: after the independent reviewer fixed confirmed-profile
rediscovery and its regression test, the focused offline suites passed **89
tests**, the portal startup/API selection passed **41 tests**, and the final
isolated full suite passed **301 tests**. Source compilation and `git diff
--check` passed. During an earlier full run, the portal's ten-second readiness
window expired under suite load; it now allows 60 seconds, and a focused
startup/API run passed. No live model or paid service was used. This does not
count as browser, native-language or live-model acceptance.

**Goal:** check every candidate scheme and change the plan when results
disagree with it.

### In simple words

Today the user picks **one** scheme and gets **one** answer. In Phase 3 the
user describes themselves once, and one chat checks **every matching
scheme**.

Example: Kamla, a 52-year-old widow whose family owns farmland.

1. **Search** finds widow pension and PM-KISAN.
2. **Plan:** learn about you → check widow pension → check PM-KISAN.
3. **Questions are asked once.** An answer is shared by every scheme that
   needs it.
4. **Replan:** Kamla confirms that a member of the farmer family covered by
   the rule paid income tax. PM-KISAN is ruled out,
   so the supervisor marks it ❌, writes why, and stops asking PM-KISAN
   questions.
5. **Results table:** if Kamla also confirms the required BPL card, widow
   pension ✅ eligible; PM-KISAN ❌ not eligible (income tax). These are
   synthetic mock results, not government decisions.

### Decisions (updated after the design critique, 2026-11-03)

| Question | Decision |
|---|---|
| Should intake use an LLM to read free-text answers? | **Yes.** E.g. "My husband died last year" can suggest widow = yes. First try today's plain-code reader; use the LLM only when it cannot read an answer. Validate the proposed value and ask for confirmation before saving it. Valid data types do not prove the LLM understood correctly. If it fails, ask for a clear yes/no/date answer. |
| How should the supervisor replan? | **Revised:** a model may propose an allowed plan/action, but code validates transitions, dependencies and reasons supported by tool observations. Existing pure planner remains the C0 baseline and validator/fallback. Specialists require bounded ReAct under the PDF, not an optional later enhancement. |
| Should search write a short LLM answer from the passages? | **Not in Phase 3.** Plan it separately. Citation IDs and number checks alone do not prove that a sentence is supported; that design needs further work. |

Backend:

- Eligibility analyst evaluates every candidate scheme from filtered search,
  not just the selected one. One verdict per scheme.
- Build candidates from distinct scheme IDs, not individual passages.
  Check retrieval with questions that match several schemes: the existing
  one-passage fallback does not establish multi-scheme coverage. Do not claim
  to check every scheme in the catalogue or every potentially matching scheme.
- One shared profile: each fact is asked once and reused by every scheme.
  Reuse only facts with the same meaning and scope: personal income and
  family income are different facts. The question picker skips schemes that
  are already decided and favours facts useful to several undecided schemes,
  with stable rule order to break ties.
- Replan rules (code, not LLM):
  - a scheme is ruled out → mark it ❌ and stop its questions;
  - a new fact opens a scheme (for example farmland) → add a step;
  - a tool fails → retry a limited number of times, then mark the step
    failed and say so. Never invent a verdict.
- Each replan is recorded in a trace: what changed, which rule or event
  caused it, and a code-written reason.
- LLM answer reader in intake, called only when plain-code reading fails.
  Validate the fact type and full profile, then ask the person to confirm
  before saving a proposed value. Allow one model attempt per fact and fall
  back to a clear plain-code question on uncertainty or tool failure.
- Let users correct confirmed facts. Invalidate affected results, recheck
  those schemes and reopen necessary questions; do not keep stale verdicts.
- In the same correction lifecycle, revoke dependent unsubmitted draft
  approvals and mark drafts stale before they can submit. Use monotonic
  dependency versions: still-eligible corrections and changing an answer back
  must not restore old approval. On invalidation failure, block writes pending
  reconciliation. Keep receipts from prior submissions as history.
- Support explicit correction/unknown handling for both single- and multi-
  scheme journeys; do not require a multi-scheme chat to correct a mistake.
- A new fact may trigger another search, but does not itself prove a scheme
  applies. Deduplicate retrieved candidates and keep schemes without rule
  packages information-only.
- Use the implemented bounded rediscovery with confirmed category/age hints
  and supported language selection. State/gender/age filters require actual
  profile and retrieval support; never infer missing facts or claim such
  filters exist today.
  Inspect actual result coverage before claiming an additional scheme was
  checked. Never silently drop excess candidates.
- Bound candidate processing to 20 IDs and retries to one; each of the
  profile facts can trigger at most one LLM interpretation per conversation.
  Search shows up to 20 passages and says that it may miss relevant schemes.
  Never silently truncate a candidate list or claim catalogue-wide coverage.

UI:

- Verdict list for all candidate schemes.
- Replan trace showing what changed and why.
- Show information-only schemes separately, a way to correct answers, and
  any unprocessed candidates or tool errors.

UI test checklist:

- [ ] A query that matches both schemes shows a verdict for each.
- [ ] Give an answer that makes one scheme fail; the plan drops it and the
      trace explains why.
- [ ] Shared questions (for example, date of birth) are asked only once.
- [ ] A tool failure is shown clearly; no fake verdict is shown.
- [ ] Answer "My husband died last year" to the widow question; it is
      understood as yes.
- [ ] Answer something unclear (for example "maybe"); the question is asked
      again, as today.
- [ ] Correct a fact that ruled a scheme out; its result is recomputed.
- [ ] Personal and family facts with different meanings are not merged.
- [ ] An LLM failure falls back to a clear question, without inventing a fact.
- [ ] Test several candidates, duplicate passages, information-only schemes
      and any processing limit, not only the two current rule packages.
- [ ] A confirmed new fact triggers a permitted, budgeted search and a trace
      of newly added candidates; eligibility still comes only from the engine.
- [ ] Approved draft → relevant correction → still eligible / not eligible /
      unknown: approval is revoked in every case. Correcting back does not revive it.
- [ ] Per-fact and conversation budgets survive correction and process restart.

Done when: the eligibility specialist has a bounded ReAct trace, the Phase 2
gate is signed off, all processed candidates have a result or explicit error,
corrections update affected results, replans are visible in the UI and match
the API trace, dependent approvals are invalidated, and an explicitly budgeted
live-model smoke confirms the flow. A live smoke is not evaluation evidence
for catalogue-wide coverage.

### Build order

1. **Several schemes:** keep the candidate list and one result per scheme.
   Schemes without rule packages remain information-only.
2. **Shared interview:** reuse confirmed facts and stop questions for decided
   schemes. Keep "don't know" separate from "no".
3. **Rule-based replanning:** record the old plan, new plan and triggering
   event. Preserve a ruled-out scheme's result rather than deleting it.
4. **LLM assistance:** add only the free-text answer reader, with bounded
   calls, clarification when uncertain, and plain-code fallbacks.
5. **Screen and checks:** show all results and the replan history. Test with
   fakes first, then a small real-LLM flow before marking Phase 3 built.

Outside Phase 3: generated search summaries and the document/application
specialists themselves. Approval invalidation on a profile correction is a
Phase 3–4 dependency, not something to postpone. Bounded agent planning is now
required by the repaired Phase 2–3 architecture.

---

## Phase 4 — Documents and approval

**Goal:** document checks and a real approval pause before submission.

### Revised work: documents and forms use registered facts

- Make checklist conditions reference approved registry IDs with explicit
  supported typed comparisons, not a hardcoded list of pilot fact names.
  Unknown condition inputs require clarification; they never skip a possibly
  required document. Preserve all-required groups and any-one alternatives.
- Enforce the actual scheme bundle's fact allowlist, not just global registry
  membership, for both conditions and form mappings. Reject cross-scheme facts
  at loading/readiness, supported publication and MCP/portal revalidation,
  including when a multi-scheme interview already contains those values.
- Add a strict, data-defined **mock form mapping**: labels, field types,
  allowed fact IDs and necessary extra fields. Validate all values; ask the
  user for required missing information. Do not invent portal fields or
  support executable expressions/arbitrary destination URLs from data.
- Build and fingerprint forms from confirmed values and exact bundle/fact/
  rule/checklist/form-mapping versions. A change to any used dependency
  cancels approval and requires a new check/review. Use the supported locked
  publication path; manual file edits are not a safe update process.
- Preserve human-only approval, expiry, one-use submission, stable identical
  retry receipts, fail-closed recovery, scoped forgetting and localized UI.
  Adding a package cannot add tool privileges or approve its own form.

**New Phase 4 gate:** the synthetic data-only scheme completes the integrated
UI→API→MCP→mock-portal flow without a `src/` change for that scheme. Include
document alternatives/unknown conditions, a new form field, an approved draft
then fact/definition/form/checklist update, fresh review and one receipt on
retry. Existing pilot forms still work. No official data approval or real
government submission is implied by these synthetic tests.

Code walkthrough: [PHASE4_CODE_WALKTHROUGH.md](PHASE4_CODE_WALKTHROUGH.md).

Backend:

- Document checker uses the MCP `check_documents` tool and user-entered
  synthetic name/date fields. Comparisons are deterministic; no document is
  read, OCR-processed or authenticated.
- Bounded document and application ReAct specialists choose only actor-
  allowlisted actions. Code owns metadata comparisons, eligibility authority,
  portal permission and human approval; no agent action can approve or reject.
- The application specialist is the only agent with mock-portal write access.
  The graph pauses with `interrupt()` for a person to approve, edit or reject
  the exact draft revision and fingerprint.
- Replace official-requirement claims with reviewed, source-linked requirements.
  Keep the existing unsourced checklist explicitly labelled demo-only until
  then. Read only synthetic document text/fields, compare name/date metadata
  deterministically and explain correction; never claim authenticity or OCR
  capability that has not been built.
  Source-backed document DATA preparation is a separate parallel workstream;
  consumer integration depends on approved data. This repair does not introduce
  new source passages, structured checklists or requirement approval.
- Unresolved conflicts and can't-tell eligibility go to clarification/human
  referral. The plan must show the resolve/referral step rather than only
  hiding the draft button.
- Bind draft/approval to current profile/document/rule dependency versions,
  revision and fingerprint. Reporting a document missing/mismatched after
  approval revokes it; rechecking only the draft's saved checklist is insufficient.
- Approval expires after 15 minutes as a conservative provisional default;
  this period remains pending team ratification, not a roles-guide agreement.
  The portal consumes authorization once and stores a receipt. An identical
  retry returns that receipt; stale, malformed, expired or replayed authority
  cannot authorize a different action.
- Bind the current document report, profile and rule dependencies, revision
  and fingerprint to each draft. Changes revoke approval monotonically, even
  if values later return to their prior state. Persistence/restart and
  multi-worker failure guarantees still need operational acceptance.
- APIs under `/api/v1/journey/{id}`: `POST /documents`, `POST /drafts`,
  `GET /drafts`, `GET /drafts/{draft_id}`, `PUT /drafts/{draft_id}`, and
  `POST /drafts/{draft_id}/approval`.
- Repair verification keeps the original eight-call model ceiling. Document/
  application recovery is code-selected only for model-unavailable/budget stops,
  reserves remaining durable tool allowance, and never creates consent or
  bypasses dependency/eligibility checks. Completed writes survive failed
  handoffs; exact create retries recover the stored current draft across edits,
  while changed dependencies or inputs produce a new unapproved draft.
  Tokens/steps remain at 12,000/12; 24 durable actions allow deterministic
  checklist rechecks, lost-response recovery and receipt retries without
  additional paid model calls.
- Forget removes only the target conversation's portal dependency rows,
  drafts, approval pauses, journey and durable budget stream; subsequent reads
  do not recreate dependency rows. UUID routes are demo capabilities, not
  authenticated citizen identity.

UI:

- Document checklist per eligible scheme.
- Draft view with Approve, Edit and Reject buttons.

### Shared document checklist implementation and remaining data gate

The shared loader is implemented for `IGNWPS-MH` and `PM-KISAN-IN` using
versioned files in `data/schemes/document_checklists/`. The current entries
are explicitly `demo_only`; they preserve the pre-existing demo IDs and make
no official-requirement claim. `data/schemes/document_evidence.json` has no
source passages yet. This is implementation only, not the parallel
[document-data workstream](SCHEME_CATALOGUE_AND_DELIVERY_PLAN.md#document-evidence-and-checklists-start-with-the-two-pilots).
That work remains a human source-collection, interpretation-review and
approval gate.

Both `schemes-kb.get_documents` and `doc-check.check_documents` load the
active scheme directly from the same strict Pydantic loader on every call;
retrieval ranking is not involved. A source-backed checklist is usable only
when its scheme, stable IDs, evidence references, reviewed passage statuses,
human approval record, and exact checklist/evidence content fingerprints
validate. A citation or URL alone is not approval. Missing, malformed,
unreviewed, rejected, conflicting, superseded or changed data returns an
explicit unverified status and cannot fall back to a demo list.

Each requirement group is required when its supported typed condition applies;
any one alternative satisfies that group. Reports and drafts carry the
checklist and evidence fingerprints, checklist version, and trust status.
Portal transactions hold the cross-process checklist publication lock from
active-file reads through SQLite commit. Supported one-file-at-a-time
publication uses the same lock, validates before atomic replacement, and
advances a persistent revision so A→B→A updates invalidate reports and
unsubmitted approvals even if no portal action observed B. A crash after
revision advance but before replacement may conservatively invalidate
approvals; retry the update. Direct/manual edits bypass this coordination and
are not covered by the guarantee. API journey refreshes bind the current report
and expose stale reports. An exact retry of an already-submitted draft still
returns its saved receipt. The UI displays dynamic groups, alternatives,
conditions, version, trust state and approved-source citations in EN/HI/MR.

Document passages may still help answer search questions. They are evidence
for explanations, not a way to build the authoritative checklist at runtime.
Passage grouping and optional search filtering are retrieval choices, not
permission to drop source wording or change checklist meaning.

**Automated trust-boundary coverage; source-backed data remains off**

- Both tools return/use the same scheme and checklist version.
- Either/or alternatives, required groups and supported conditions behave
  correctly with synthetic inputs.
- Missing files, invalid IDs, broken evidence links, unreviewed/rejected or
  conflicting sources and unapproved checklists never become trusted lists.
- A new checklist version, evidence change or withdrawn approval makes the
  old report and unsubmitted form outdated. Recheck and fresh approval are
  required, even if the old version is restored.
- A coordinated publisher blocks while submission is between its last
  dependency check and SQLite commit; publishing first makes the old report and
  approval stale. An already-submitted exact retry still returns its saved
  receipt without creating another submission.
- API/UI show clear source, unknown, changed-list and recheck messages in
  English, Hindi and Marathi; the two pilot flows pass end to end.

No reviewed rules, corpus passages or source statuses are changed by accepting
this plan. Collecting sources and approving their meaning remain human gates.
The existing synthetic demo can still be tested while this data work is open.

UI test checklist:

- [ ] Missing documents are listed for an eligible scheme.
- [ ] Approve then submit sends the draft to the mock portal.
- [ ] Edit the draft after approving; the old approval is refused.
- [ ] Reject returns to the draft without submitting.
- [ ] Mismatch → correction → recheck → fresh draft/review succeeds; unresolved
      mismatch or unverified requirement blocks progress with clear guidance.
- [ ] Unknown/information-only/not-eligible/tool-error eligibility cannot create,
      approve or submit a draft. Changing an approved case to unknown also blocks it.
- [ ] A still-eligible fact correction, document report change or rule version
      change revokes approval. Returning old values never revives authorization.
- [ ] Expiry, cross-draft/revision replay, duplicate/concurrent submission and
      failure between checkpoint/portal updates produce no extra submission.
- [ ] Stop/restart after draft, approval and submission; recover the correct
      state and same receipt without inventing a human approval.
- [ ] In EN/HI/MR, the UI explains stale drafts, missing documents, mismatch and
      human referral; refresh does not show obsolete cached approval.

Existing graph tests already cover `missing`, `unknown` and `mismatch`
document reports; extend them rather than claim they are absent. Existing
correction-after-draft coverage starts with an **unapproved** draft and becomes
not eligible; it does not establish revocation of a previously approved draft.

Automated Phase 4 coverage now exercises bounded specialist actions and
permissions, deterministic mismatch resolution, approval expiry and one-use
receipts, stale dependency changes, concurrent operations, API/UI refresh and
localized referral. These tests are not browser, independent-language,
process-kill or live-model acceptance.

**Revised bundle-scope repair evidence (2026-11-05):** form fields and checklist
conditions now require actual bundle membership and compatible fact definitions
through loading/readiness, supported publication, MCP and portal revalidation.
Nine new cases reject globally valid cross-scheme references and forged
snapshots, reject incompatible versions/definitions, and accept a legitimate
additional fact only in an explicitly injected development bundle. The related
offline selection passed **139 tests in 217.74s**; the single final serial
full suite passed **411 tests in 375.75s**. Compilation and diff whitespace
checks passed. The integrated synthetic scholarship UI proof and both pilot
flows pass in these selections. Independent re-review and walkthrough updates
are not claimed. Source/privacy/question approval, normal novel activation,
manual browser/language and native Python 3.12/CI remain open; single-file locked
publication is not atomic full-bundle activation. Phase 5 remains paused.

**Derived-fact follow-up (2026-11-05):** checklist evaluation and API/portal
form population resolve bundle-authorized derived values from confirmed typed
inputs through the trusted fact store. All derivation dependencies must also
be bundle-declared; direct derived input is denied and missing dependencies
stay unknown/missing. Four additional regressions cover the birthday boundary,
missing dates, injection and unauthorized dependency closure. Related offline
selection: **143 passed in 177.70s**; single full serial suite: **415 passed in
364.98s**; compileall and diff checks passed. This supersedes the preceding
automated counts, not the independent/manual/source/privacy acceptance gates.

**Walkthrough revision (2026-11-05, author-pending-review):**
`docs/PHASE4_CODE_WALKTHROUGH.md` was rewritten for the data-driven state
(bundle-scoped facts, data-defined forms, shared publication revision, the
synthetic scholarship test). Documentation only; no tests were run for it, no
independent review of the guide has happened yet, and it quotes the evidence
above as reported. Phase 5 remains paused.

**Integrated proof follow-up (2026-11-05):** the existing synthetic data-only
AppTest now covers an exact decimal-mapped field from typed text input through
API preview, portal fingerprint, human approval and receipt retry. A typed
decimal correction after approval in that same real UI/API/MCP/portal flow
stales/unapproves the old draft, blocks old submit, and requires fresh review.
The decimal checklist threshold is exact text `0.12345678901234567`; the
correction preserves exact text `0.12345678901234568`. The expanded test retains
form/checklist publication invalidation and proves one receipt across exact
retry (three drafts total). Final targeted integration/checklist selection:
**34 passed in 152.99s**; single full serial suite: **415 passed in 278.01s**;
compileall and diff checks passed. No runtime implementation change, reviewed
pilot pin change, independent re-review or manual/CI/source/privacy approval.

**Literal decimal receipt clarification (2026-11-05):** the same test now
restores original `.67` through typed correction after `.68` approval is
cancelled; A→B→A leaves both old drafts stale/unapproved and old submits rejected.
A fresh third draft needs fresh human approval and yields original exact
`0.12345678901234567` in submission and same-receipt retry. Exact integration:
**1 passed in 91.01s**; compileall/diff passed. No runtime changes or full-suite
repeat; preceding full-suite evidence predates this test-only clarification.

**Module naming and library simplification (2026-11-05, commits `85fba19` and
`34cafd5`):** the phase-named agent modules became `supervisor_agent.py`,
`intake_agent.py`, `eligibility_agent.py`, `document_agent.py` and
`application_agent.py`, with shared recovery in `agent_runtime.py`. OpenRouter
chat calls now go through `src/llm_client.py` (openai SDK, no automatic
retries), checklist publication uses `filelock`, and several duplicated helpers
were merged (see [THIRD_PARTY_LIBRARIES_REVIEW.md](THIRD_PARTY_LIBRARIES_REVIEW.md)).
No behaviour change was intended; the commit message reports a full local run of
**419 passed**. No acceptance gate above changes.

Done when: the Phase 3 gate and all application lifecycle checks pass, four
specialists satisfy the ReAct/tool-boundary gate, and submission requires
current dependencies plus fresh exact human approval.

---

## Phase 5 — Guardrails, memory and evaluation

### Revised work: prove safety and reuse across scheme types

**Still paused:** start only after the revised Phases 1–4 and their team
acceptance checks pass. The work below is planning, not authorization to run
paid models or inspect protected evaluation cases.

- Carry approved fact privacy/retention policy into masking, consent, scoped
  memory reads, expiry/correction/deletion and safe traces. Deny newly loaded
  fields without a known policy; registry flexibility cannot expand disclosure.
- Evaluate package/schema/operator validation as well as model behavior.
  Test hostile question/source text, unknown IDs, forged approvals, unit/scope
  confusion, unsupported formulas and package updates mid-conversation.
- Expand the extractor output contract to include registered fact references,
  questions and bundle/checklist/form mappings as appropriate. Proposed
  definitions remain untrusted until human review; no automatic publication.
- Freeze registry and bundle versions with prompts/models/budgets in every
  C0/C1/C2 and E1–E4 comparison below. Independently labelled cases must cover
  distinct scheme types, not only the two pilots. The synthetic scholarship
  is development data, never held-out evidence or an approved gold scheme.

**New Phase 5 gate:** report whether data-only onboarding and cross-scheme
facts preserve verdict accuracy/safety, alongside the full capstone metrics
below. New package convenience must not weaken deterministic decisions,
privacy, exact approval or independent evaluation boundaries.

**Goal:** complete the PDF's memory, improvement, security and evaluation
requirements, not only a prompt filter and a question-count comparison.
Minimal masking/hooks/traces already belong before ReAct in Phase 2.

Backend:

- Input guardrails: mask ID numbers, block prompt injection, reject
  out-of-scope requests.
- Output guardrails: no eligibility claim without rule evidence.
- Can't-tell verdicts are referred to a human.
- Evaluation: compare planned question order with a fixed order (number of
  questions, verdict accuracy).
- Long-term memory: pseudonymous household ID, explicit consent and expiry,
  scoped read/correction/forget; written field/retention policy, short-term
  context trimming and memory-on/off comparison. Checkpoints alone do not pass.
- Rules signature: reviewed 40–60 scheme corpus and 15 hand-coded gold schemes;
  prose-to-JSON extractor accuracy, development-only error lessons, human
  approval/rejection of lessons, relevant retrieval and frozen playbook before
  independent held-out scheme evaluation. Review assistance is not this pipeline.
- Governed evaluation: 60+ synthetic boundary personas, about 20 development
  and at least 40 protected held-out; two independent labels per persona/
  candidate, separate scenario families across splits. Role 5 controls hidden
  profiles/answers; builders and agent-facing tools cannot read them.
- Independent simulated citizen answers only what is asked. Use checker code
  first, a different-family judge only for non-code-checkable quality,
  calibrated on 20+ human labels with Cohen's kappa.
- One config-driven harness runs E1–E4 below; report successes, policy
  violations, failures/timeouts, cost and median/p95 latency, not selected demos.
- Threat model and 30+ independent attacks; defenders must not author their
  own final attack evidence. Test own retrieved data path as well as user input.

| Experiment | Comparison and controls |
|---|---|
| E1 | C0 fixed workflow, C1 one agent, C2 specialist team; same model, tools and total budget. Preserve safety/approval controls in every configuration. |
| E2 | Defences off/on over both attacks and clean cases; report attack success and legitimate-work false blocks. Run only in isolated synthetic evaluation, not the live deployment. |
| E3 | Before/after frozen human-reviewed Reflexion playbook; include lesson-generation costs, rejected lesson and regressions. Independent held-out owner executes. |
| E4 | Direct LLM vs rule-engine boundary errors **in an isolated evaluation-only path**, never as live eligibility authority; planned vs fixed question order with the same persona/criteria. |

Repeat final held-out comparisons three times and report spread. Never tune
against exposed held-out cases; reclassify/replace any exposed cases. Choose
thresholds before running comparisons, not after seeing favorable scores.

UI:

- Warning messages for blocked or masked input.
- Referral notice for can't-tell cases.
- Evaluation results available in the docs (not in the citizen UI).

UI test checklist:

- [ ] Typing an Aadhaar-like number shows it masked.
- [ ] A prompt-injection message is refused politely.
- [ ] A case with conflicting answers shows the referral notice.
- [ ] The report compares question counts and verdict accuracy honestly,
      including cases where planned order is no better; improvement is measured,
      not a required conclusion.
- [ ] Consent, expiry, scoped memory access, correction and forget work, with
      a memory-on/off report and reviewed retention/deletion limits.
- [ ] Extractor/gold accuracy and approved/rejected lessons are recorded;
      frozen-playbook held-out evidence is produced by the independent owner.
- [ ] E1–E4, judge agreement, red-team false blocks, costs/latencies/failures and
      three-repeat spread are reported without exposing protected case data.

Done when: Phase 4 is signed off, the governed data/source targets and both
signature challenges have evidence, and memory, safety and E1–E4 pass agreed
thresholds. No threshold or owner is assumed approved by this document.

---

## Phase 6 — Operations and final evidence

### Revised work: publish and operate complete scheme bundles

- Package the registry, questions, rules, checklist evidence and mock form
  mappings so installed builds/containers work without source-tree assumptions.
  Validate compatible versions/hashes at startup and expose safe bundle IDs
  in diagnostics, not applicant facts.
- Extend the supported publication process to a complete compatible bundle.
  Stage and validate all files before activation; readers see one coherent
  version. Coordinate activation with submission and durable revision
  tracking so rollback never restores old approvals.
- Document checkpoint/API migration, failure recovery and safe rollback.
  Saved answers with changed meanings require reconfirmation, not silent
  conversion. Prove behavior on CI Python 3.12 and the deployment platform.
- Demonstrate a clean install and data-only addition of the development
  scheme, plus malformed-bundle rejection, restart, rollback, scoped deletion
  and current-versus-outdated draft UI. Retain the operations gates below.
- Update all four walkthroughs and the frontend contract after implementation
  changes, with independent correctness and simple-English readability review.

**New Phase 6 gate:** publish a compatible bundle and recover safely from
partial publication/restart without mixed versions, lost receipts or restored
approval. Deployment remains a separate explicit request and exact-commit
validation step.

**Goal:** ready for the capstone demo.

Backend:

- Resume a journey after the API restarts.
- Citizen and CSC-assisted modes change the wording and consent text.
- `DELETE /journey/{id}` removes a session.
- Update README, plan docs and the frontend contract.
- FastAPI streaming with safe event contracts; UI displays validated progress
  without exposing model reasoning or raw tool errors.
- One-command Compose starts UI/API, separate MCP services, mock portal, vector
  store, Prometheus and Grafana. Verify storage/restore/migration behavior;
  local SQLite files in an ephemeral container are not a cross-revision backup.
- Traces cover every model/tool call with masking, cost/latency/error outcomes.
  Dashboard: questions/chat, can't-tell rate, waiting approvals, masked-ID hits,
  cost/chat. Demonstrate one alert for an unknown-rate jump.
- CI runs agreed **development** evaluation thresholds as well as unit tests,
  compilation and packaged fixtures; keep a deliberately failing run and its
  explanation. Protected evaluation uses a separate owner-controlled job.
- Clean-machine instructions, redrawn architecture/numbered walkthrough,
  threat model, memory policy, 4–6 page evaluation report, experiment/contribution
  logs, slides and backup demo recording. Do not generate fake completion evidence.

UI:

- Resume a previous session.
- The Citizen/CSC radio works.
- Delete my session button.

UI test checklist:

- [ ] Restart the API mid-conversation; the session resumes.
- [ ] CSC mode shows operator wording.
- [ ] Delete removes the session and its data.
- [ ] Run the full demo checklist in the end-to-end plan.
- [ ] Compose clean-machine start, streaming, data persistence through restart/
      revision replacement, dashboard and working alert are demonstrated.
- [ ] A below-threshold development run fails CI and cannot deploy.
- [ ] EN/HI/MR and Citizen/CSC flows show the same rule verdicts and real mode/
      consent differences, including Hindi widow request → approved mock draft.
- [ ] Refuse under-reporting, flag/ignore a planted scam source, then demonstrate
      scoped forget across stores and report log/backup retention limits.

Done when: the full demo runs without manual fixes. Deploy only if the team
asks.

---

## Progress log

Record each phase sign-off here.

| Phase | Date | Tested by | Result | Notes |
|---|---|---|---|---|
| Data-driven replanning | 2026-11-04 | Copilot CLI (planning only) | Proposed implementation gates; not implemented | Replanned all six phases for a reviewed fact/question registry and compatible scheme bundles. Existing 361-test baseline is preserved as historical implementation evidence, not proof of data-only onboarding. Phases 1–4 must be revised and retested before Phase 5; no rule/source approval, code change, paid run or deployment is authorized. |
| Revised Phase 1 registry and evaluator | 2026-11-04 | Copilot CLI (automated offline checks) | Automated foundation checks pass; independent and manual review open | Registry/MCP/API focused selection: **84 passed**; full offline suite: **373 passed in 221.88s**; `compileall -q src` passed. Added registry-backed typed facts, pinned compatible bundles, unchanged pilot rule files with explicit legacy mappings, and a synthetic data-only numeric/choice evaluator test through the MCP core. Development-only bundles are excluded from default activation. Registry fact/question/privacy review metadata remains pending; no policy/source approval, Phase 2 question/UI integration, independent verifier, or walkthrough is claimed. |
| Phases 1–4 together in the UI | 2026-11-04 | Copilot CLI (automated AppTest integration) | Two integrated C0 English scenarios pass; manual/operational gates remain open | `tests/test_ui_integration.py`: **2 passed in 55.59s**; full offline suite: **361 passed in 197.33s**; compileall passed. Real widget clicks and UI client serialization reach FastAPI, the actual graph, four spawned MCP services and independent local HTTP portal. Only UI HTTP transport is bridged to TestClient; production search vectors/reranking are disabled in the schemes-kb child, retaining real corpus/BM25 ranking. Citizen consent → search/select → interview → rule-engine eligible → still-eligible correction → synthetic document mismatch/resolution → draft → exact approval → receipt → fresh-session URL restore → same-receipt retry (one submitted DB record) and scoped forget pass. CSC citizen-presence gating and previously approved → still-eligible correction → stale refreshed draft/no submit → fresh report/draft/review pass, with old submission rejected. No fabricated workflow/API/portal responses or paid calls; this does not establish manual visual/browser, live-model, independent language, native Python 3.12/CI or process-kill/multi-worker acceptance. No source evidence approval or Phase 5 work. |
| Phase 1 G02 implementation | 2026-11-03 | Copilot CLI (automated checks only) | Service contracts and integration tests passed; manual sign-off pending | Four stdio services and separate local portal verified; targeted 51 tests, final suite 203 passed, compileall passed. No browser acceptance claimed. |
| 1–2 | 2026-11-03 | Copilot CLI (automated checks only) | Manual sign-off pending | Local compilation and 196 offline tests passed; checklist evidence mapped above. No manual browser acceptance recorded. |
| 3–4 (before push) | 2026-11-03 | Copilot CLI (automated checks only) | Historical local check; not sign-off | At that time Phase 4 was uncommitted and cloud validation was blocked. The subsequent deployment record below supersedes that status; earlier manual gates remain open. |
| 1–4 baseline | 2026-11-03 | GitHub Actions | Validation/deployment passed, not phase acceptance | `770bc5c`, run 41638806677; supersedes the earlier local-only deployment status, not the pending manual gates. |
| Plan reconciliation | 2026-11-03 | Copilot CLI (source/code review) | Revised scope proposed; implementation pending | Original PDF and roles guide checked; G01–G16 and R0–R6 define repairs. No new code, paid evaluation or manual acceptance in this review. |
| Phase 2 bounded supervisor and intake | 2026-11-04 | Copilot CLI (automated checks only) | Implementation checks pass; manual gates open | Added model-selected validated supervisor/intake actions, confirmation-before-mutation, EN/HI/MR and Citizen/CSC contract, pre-choice safety controls, and durable counters/attempts. Targeted regression selection: 105 passed; final Phase 2/API/UI selection: 17 passed; full offline suite: 242 passed; compileall passed. Fake-model and reopened-SQLite tests only; no paid/live-model, browser or independent language acceptance claimed. |
| Phase 4 document and approval | 2026-11-04 | Copilot CLI (automated checks only) | Implementation checks pass; independent and manual gates open | Focused Phase 3/4 integration selection: 120 passed; full offline suite: 321 passed in 100.76s; compileall and `git diff --check` passed. Tests use synthetic inputs/mocked models only. No OCR/authenticity, official requirement verification, browser, independent language, live-model, process-kill or multi-worker acceptance is claimed. The 15-minute expiry remains a provisional policy pending team ratification. |
| Phase 4 repair verification | 2026-11-04 | Copilot CLI (automated checks only) | Requested repairs verified; operational/manual acceptance remains open | Focused specialist/API/UI selection: 39 passed; Phase 2/4 and application-lifecycle selection: 74 passed. Final full offline suite: **332 passed in 122.89s**; `compileall -q src` and `git diff --check` passed. Fake-model intake confirmation, eligibility, document recheck, lost-create-response recovery, exact human approval and receipt retry fit the durable eight-call ceiling across SQLite reopen. Scoped forget and EN/HI/MR controls are covered. No Phase 5, paid calls, new source/checklist data, deployment or manual acceptance. Browser, native Python 3.12/CI, independent language, approved live-model, process-kill/multi-worker checks remain open; the 15-minute expiry is still provisional. |
| Shared document checklist | 2026-11-04 | Copilot CLI (automated checks only) | Implementation checks pass; source and manual gates open | Focused checklist/portal/MCP/API/UI selection: 97 passed; full offline suite: **354 passed**; `compileall -q src` passed. Exact checklist/evidence fingerprints, source approval fail-closed behavior, both demo pilot files, alternatives/conditions, stale report/draft invalidation and receipt retry are covered with synthetic data. No source evidence collected or approved, no Phase 5, paid calls, deployment or manual acceptance. Native Python 3.12/CI, browser, independent language and process-kill/multi-worker acceptance remain open. |
