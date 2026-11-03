# Scheme Saathi: phase-wise implementation plan

This plan splits the redesign in
[END_TO_END_IMPLEMENTATION_PLAN.md](END_TO_END_IMPLEMENTATION_PLAN.md) into
phases. Each phase changes the backend **and** the UI together, so we always
have a working end-to-end app to click through.

## How each phase works

1. Build the backend and UI changes for the phase on branch
   `feature/supervisor-redesign`.
2. Add tests for the new behaviour. The full suite must pass
   (`python -m pytest -q`).
3. Run the app locally (FastAPI + Streamlit).
4. Test the phase in the UI using its checklist below.
5. Only if the UI behaves as expected, mark the phase done and start the next
   one.

Rules for every phase:

- Eligibility verdicts, question scoring and approval checks stay in code. The
  LLM never decides eligibility.
- Data stays synthetic. The mock portal never contacts a government service.
- Nothing is deployed unless the team asks for it.

## Phase overview

| Phase | Backend | What you see in the UI | Status |
|---|---|---|---|
| 1. Base | Shared typed models; one rule engine for both schemes; PM-KISAN through MCP and the graph | Same screens; PM-KISAN uses the same path as widow pension | Built; automated regression checks pass; manual UI gate pending |
| 2. Supervisor and intake | Supervisor makes a plan; intake asks one question at a time | Chat box instead of fixture form; plan panel | Built; automated regression checks pass; manual UI gate pending |
| 3. Multi-scheme and replan | Eligibility checks every candidate; plan changes when a result contradicts it | Verdict list for all schemes; replan trace | Built; pilot smoke test previously reported; not signed off while earlier gates remain open; broader retrieval evaluation pending |
| 4. Documents and approval | Document checker; application agent pauses with `interrupt()` | Document checklist; approve, edit or reject the exact draft | Built locally, uncommitted; automated regression checks pass; manual UI gate and earlier sign-offs pending |
| 5. Guardrails and evaluation | Input/output checks; refer can't-tell cases to a human; planned vs fixed question order | Warnings and referral notice | Not started |
| 6. Polish and demo | Resume after crash; Citizen/CSC mode; docs | Resume a session; CSC mode works | Not started |

### Gate reconciliation — 2026-11-03

Later implementation started before Phase 1 and 2 UI sign-offs were recorded.
This does not satisfy the phase-order rule above. Keep the existing work, but
do not treat implementation or automated tests as manual acceptance. Pause new
phase work until the earlier UI gates have been checked and signed off in order.

Local compilation and the full offline suite passed on 2026-11-03:
`python -m compileall -q src` and
`python -B -m pytest -q -x -p no:cacheprovider --disable-warnings`
(196 passed). These results cover the current local worktree, not a pushed
commit. The GitHub validation script stopped because the worktree is dirty;
no cloud validation or deployment was performed.

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

Code walkthrough: [PHASE1_CODE_WALKTHROUGH.md](PHASE1_CODE_WALKTHROUGH.md).

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

Done when: all items pass and no scheme bypasses the graph.

---

## Phase 2 — Supervisor and intake

**Goal:** the supervisor plans and delegates; intake asks questions instead
of receiving a full fixture profile.

Backend:

- Supervisor node builds a `Plan` (profile → candidate schemes → rules →
  documents → draft) and hands steps to specialists with typed `Handoff`
  messages.
- Intake loop: code picks the question that settles the most open verdicts;
  the LLM only phrases it and extracts the answer into the profile.
- The graph pauses after each question and resumes from the checkpoint when
  the user replies.
- Stop asking when verdicts are settled or the user says they don't know.
- New API: `POST /journey/{id}/messages`, `GET /journey/{id}`.

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

Done when: no fixture profile is needed to reach a verdict.

Code walkthrough for new developers: [PHASE2_CODE_WALKTHROUGH.md](PHASE2_CODE_WALKTHROUGH.md).

What was built (no new LLM calls in the interview; search already uses an
LLM to rewrite queries):

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
- Known limits: questions and plan goals are English only; the widow chat
  does not prepare a draft.

---

## Phase 3 — Multi-scheme and replan

Implementation walkthrough:
[PHASE3_CODE_WALKTHROUGH.md](PHASE3_CODE_WALKTHROUGH.md).
Candidate storage, shared interview, search-screen entry point and
code-written history for completed candidate checks, bounded retries,
tool-failure history, answer correction, and confirmed free-text answer
reading are implemented. Search requests up to 20 passages and clearly
warns that it may miss schemes; the API rejects candidate lists over 20.
The live-model multi-scheme flow and the available 43-query development set
were exercised. Retrieval was measured as a BM25-only diagnostic because
the free embedding key is not configured; broader-catalogue evaluation
requires additional reviewed scheme sources and validated query labels.

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
| How should the supervisor replan? | **Code decides and writes the reason.** No LLM planner or reason writer in Phase 3. Consider checked LLM plan suggestions later if real user scenarios show a need. |
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
- A new fact may trigger another search, but does not itself prove a scheme
  applies. Deduplicate retrieved candidates and keep schemes without rule
  packages information-only.
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

Done when: all processed candidates have a result or explicit error,
corrections update affected results, replans are visible in the UI and match
the API trace, and a small real-LLM flow confirms the intake works.

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

Outside Phase 3: an LLM planner, generated search summaries, document
checking and application submission. These remain separate work.

---

## Phase 4 — Documents and approval

**Goal:** document checks and a real approval pause before submission.

Code walkthrough: [PHASE4_CODE_WALKTHROUGH.md](PHASE4_CODE_WALKTHROUGH.md).

Backend:

- Document checker uses the MCP `check_documents` tool (synthetic metadata only). It
  reports missing items; it does not judge authenticity.
- Application agent drafts the form. It is the only agent with write access to
  the mock portal.
- The graph pauses with `interrupt()`. Approve, edit or reject is bound to the
  exact draft fingerprint.
- APIs under `/api/v1/journey/{id}`: `POST /documents`, `POST /drafts`,
  `GET /drafts`, `GET /drafts/{draft_id}`, `PUT /drafts/{draft_id}`, and
  `POST /drafts/{draft_id}/approval`.

UI:

- Document checklist per eligible scheme.
- Draft view with Approve, Edit and Reject buttons.

UI test checklist:

- [ ] Missing documents are listed for an eligible scheme.
- [ ] Approve then submit sends the draft to the mock portal.
- [ ] Edit the draft after approving; the old approval is refused.
- [ ] Reject returns to the draft without submitting.

Done when: submission is impossible without approval of the exact draft.

---

## Phase 5 — Guardrails and evaluation

**Goal:** safe inputs and outputs, human referral, and measured question
order.

Backend:

- Input guardrails: mask ID numbers, block prompt injection, reject
  out-of-scope requests.
- Output guardrails: no eligibility claim without rule evidence.
- Can't-tell verdicts are referred to a human.
- Evaluation: compare planned question order with a fixed order (number of
  questions, verdict accuracy).

UI:

- Warning messages for blocked or masked input.
- Referral notice for can't-tell cases.
- Evaluation results available in the docs (not in the citizen UI).

UI test checklist:

- [ ] Typing an Aadhaar-like number shows it masked.
- [ ] A prompt-injection message is refused politely.
- [ ] A case with conflicting answers shows the referral notice.
- [ ] The evaluation report shows planned order asks fewer questions.

Done when: all guardrail cases behave as expected and the evaluation report is
written.

---

## Phase 6 — Polish and demo

**Goal:** ready for the capstone demo.

Backend:

- Resume a journey after the API restarts.
- Citizen and CSC-assisted modes change the wording and consent text.
- `DELETE /journey/{id}` removes a session.
- Update README, plan docs and the frontend contract.

UI:

- Resume a previous session.
- The Citizen/CSC radio works.
- Delete my session button.

UI test checklist:

- [ ] Restart the API mid-conversation; the session resumes.
- [ ] CSC mode shows operator wording.
- [ ] Delete removes the session and its data.
- [ ] Run the full demo checklist in the end-to-end plan.

Done when: the full demo runs without manual fixes. Deploy only if the team
asks.

---

## Progress log

Record each phase sign-off here.

| Phase | Date | Tested by | Result | Notes |
|---|---|---|---|---|
| 1–2 | 2026-11-03 | Copilot CLI (automated checks only) | Manual sign-off pending | Local compilation and 196 offline tests passed; checklist evidence mapped above. No manual browser acceptance recorded. |
| 3–4 | 2026-11-03 | Copilot CLI (automated checks only) | Not signed off | Later implementation exists, but earlier gates remain open. Phase 4 is local and uncommitted; cloud validation is blocked by the dirty worktree. |
