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
| 1. Base | Shared typed models; one rule engine for both schemes; PM-KISAN through MCP and the graph | Same screens; PM-KISAN uses the same path as widow pension | Not started |
| 2. Supervisor and intake | Supervisor makes a plan; intake asks one question at a time | Chat box instead of fixture form; plan panel | Not started |
| 3. Multi-scheme and replan | Eligibility checks every candidate; plan changes when a result contradicts it | Verdict list for all schemes; replan trace | Not started |
| 4. Documents and approval | Document checker; application agent pauses with `interrupt()` | Document checklist; approve, edit or reject the exact draft | Not started |
| 5. Guardrails and evaluation | Input/output checks; refer can't-tell cases to a human; planned vs fixed question order | Warnings and referral notice | Not started |
| 6. Polish and demo | Resume after crash; Citizen/CSC mode; docs | Resume a session; CSC mode works | Not started |

---

## Phase 1 — Base

**Goal:** one shared foundation, so both schemes follow the same path.

Backend:

- Add the shared typed models: `Plan`, `PlanStep`, `HouseholdProfile`,
  `CandidateVerdict`, `Handoff`.
- Make one rule package schema that fits both widow pension and PM-KISAN. Each
  package lists its `required_facts`.
- Move PM-KISAN into the common rule engine. Remove the direct
  `/PM-KISAN-IN/evaluate` shortcut.
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

**Goal:** the orchestrator plans and delegates; intake asks questions instead
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

---

## Phase 3 — Multi-scheme and replan

**Goal:** check every candidate scheme and change the plan when results
disagree with it.

Backend:

- Eligibility analyst evaluates every candidate scheme from filtered search,
  not just the selected one.
- Replan triggers (for example: a scheme fails, a new fact opens a new
  scheme, a tool fails). Each replan is recorded in a trace.
- Self-correction loop with retry limits.

UI:

- Verdict list for all candidate schemes.
- Replan trace showing what changed and why.

UI test checklist:

- [ ] A query that matches both schemes shows a verdict for each.
- [ ] Give an answer that makes one scheme fail; the plan drops it and the
      trace explains why.
- [ ] Shared questions (for example, date of birth) are asked only once.
- [ ] A tool failure is shown clearly; no fake verdict is shown.

Done when: replans are visible in the UI and match the trace in the API.

---

## Phase 4 — Documents and approval

**Goal:** document checks and a real approval pause before submission.

Backend:

- Document checker uses the MCP `doc-check` tool (synthetic metadata only). It
  reports missing items; it does not judge authenticity.
- Application agent drafts the form. It is the only agent with write access to
  the mock portal.
- The graph pauses with `interrupt()`. Approve, edit or reject is bound to the
  exact draft fingerprint.
- New API: `POST /journey/{id}/approval`.

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
| | | | | |
