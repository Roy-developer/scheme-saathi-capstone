# Role 3: Agents and orchestration — what the code does and why

Role 3: Priyanka Velisetty. Prepared with Claude Code (Sonnet 5.5).
Last updated: 2026-11-13.

Role 3 owns the **brain** of Scheme Saathi: the graph that runs a citizen's
journey, the supervisor that plans it, the specialist agents that carry out
each step, the rule extractor and its improvement loop, and the evidence that
this design is worth its cost. Role 3 does **not** decide who is eligible (the
rule engine does, in plain code), and does **not** own the tool servers, the
security controls or the held-out evaluation (roles 4 and 5).

One rule runs through everything below: **the model chooses, our code runs.**
A model can only name an action from a short allow-list. Code validates the
choice, performs it, and returns the result as data. No model writes a
verdict, approves a form or changes a stored fact on its own.

---

## 1. The journey graph (`src/workflow/journey.py`)

A LangGraph state machine. Seven nodes:

| Node | What it does |
|---|---|
| `supervisor` | Writes the visible plan, hands each step to one specialist, replans when a result changes it, ends the run |
| `intake_agent` | Gathers household facts, asking only questions that can still change a verdict |
| `ask_user` | Pauses the graph with `interrupt()` and waits for the person's answer |
| `eligibility_agent` | Asks the rule engine for a verdict on one scheme and reports it |
| `scheme_search_tool` | Hybrid search over source-cited scheme clauses |
| `document_agent` | Read-only: compares the entered documents against the scheme checklist |
| `application_agent` | The only node allowed to write drafts and submit; needs exact human approval |

Every specialist reports back to the supervisor; only intake can route to
`ask_user` and back. The diagram is generated from the compiled graph, so it
cannot drift from the code: `python scripts/export_graph_diagram.py` writes
`docs/GRAPH_DIAGRAM.md`.

**How the L8 minimum bar is met**

- *Typed state:* `src/workflow/state.py` defines `Plan`, `PlanStep`,
  `Handoff`, `CandidateVerdict`, `PlanChange` and `JourneyHistoryEvent` as
  strict models that reject undeclared fields, so an agent cannot pass data
  the contract does not name.
- *Conditional edges:* the supervisor picks the next specialist from state
  (`next_agent`); intake chooses between asking again and returning.
- *Persistent checkpointer:* `AsyncSqliteSaver` in `src/api/app.py`. State is
  saved after every node, so a run survives a restart.
- *Human control:* `ask_user` uses `interrupt()`, and the draft approval gate
  (`src/workflow/application_gate.py`) is a second checkpointed graph with its
  own `interrupt()`, keyed per conversation, draft and revision.
- *Self-correction:* when a verdict contradicts the plan (for example, a
  scheme turns out ineligible), the supervisor replans, bumps the plan version
  and records why (`replan_reason` in `supervisor.py`).

## 2. The supervisor and the planner

`src/workflow/supervisor.py` holds pure functions (no graph, no I/O, so they
are easy to test): `build_initial_plan`, `build_application_plan`,
`advance_plan`, `plan_summary` and `replan_reason`, with goal text in English,
Hindi and Marathi.

`src/workflow/supervisor_agent.py` adds an optional model layer: the model may
*propose* a plan by naming step IDs through `propose_plan` and `finish_plan`.
Code checks the IDs against the known steps and their dependencies. If the
model is absent, fails or proposes something invalid, the deterministic plan
(configuration **C0**) runs instead. The plan is never allowed to invent
steps, decide eligibility or call tools directly.

## 3. The specialist agents

Each specialist is a LangChain `create_agent` run through one shared function,
`run_agent` in `src/workflow/agent_runtime.py`. That function attaches the
same safeguards to every agent, so no agent can opt out:

- **PII masking** (`PIIMiddleware`) on the task message and on every tool
  result, before the model sees them (Aadhaar, PAN, phone, account, email).
- **Tool allow-list:** the agent receives only its own tools.
- **Durable budget** (`DurableBudgetMiddleware`, `conversation_budget.py`):
  model calls, tokens, tool calls and agent steps are counted per conversation
  and saved *before* each call, so a crash cannot reset the allowance. Limits
  live in `agent_config.py` (8 model calls, 24 tool calls, 12 agent steps,
  12,000 tokens, 512 completion tokens, 20 s timeout).
- **Scrubbed trace** (`ScrubbedTraceMiddleware`): one metadata-only event per
  model stop and tool call, with no prompts and no applicant values.
- **Fail closed:** a rejected action raises `AgentActionError`, which stops
  the run instead of continuing.
- **Versioned prompts** per agent and language (`agent_config.py`).

| Agent | File | What the model may do | What code keeps |
|---|---|---|---|
| Intake | `intake_agent.py` | Propose facts that a quarantined, tool-free reader found in the person's text | The person must confirm a fact before the profile changes; confirmed facts are never overwritten; no ID or financial numbers are requested |
| Eligibility | `eligibility_agent.py` | `check_candidate`, then hand off the observed verdict, request clarification for observed missing facts, or refer for help | The verdict comes from the rule engine only; the model cannot supply or change it. If the model is unavailable the rule engine still runs directly |
| Documents | `document_agent.py` | Inspect entered metadata and hand off the matching checklist result | Name and date comparison is code; no OCR or authenticity claim |
| Application | `application_agent.py` | Run the one backend-selected prepare, edit, submit or status action | Never approves or rejects; submits only when code confirms an exact, unexpired approval |

**Choosing what to ask** (`question_picker.py`): `pick_next_registered_fact`
asks only for a fact that a still-undecided rule needs;
`pick_shared_registered_fact` prefers a fact shared by the most unresolved
schemes. This is the "planned" question order in experiment E4.

## 4. Hooks and safeguards that role 3 relies on

Middleware in `agent_middleware.py` and `agent_runtime.py` is the hook layer
around model calls and tool calls. Input guards (`injection_guard.py`,
`input_guardrails.py`, `scam_screen.py`) screen free text before an agent sees
it. The threat model and tool permissions belong to role 4
(`docs/THREAT_MODEL.md`, `docs/MCP_PERMISSIONS_WALKTHROUGH.md`); role 3's job is
that every agent runs through them. `docs/HOOKS_WALKTHROUGH.md` explains each
hook with its test.

## 5. The rule extractor and the improvement loop

`src/rule_extraction_reflexion/` reads official scheme clauses into rules and
improves over time without ever deciding anyone's eligibility.

1. A model writes rules from an approved clause.
2. Code compares them with the approved rule package (the model never sees it).
3. For a difference, the model writes a **lesson**, held as *pending*.
4. A person approves or rejects the lesson; approved lessons are frozen into a
   numbered **playbook** (`data/schemes/playbooks/1.0.0.json`).
5. Next time, the model reads a clause together with the matching lessons.

Nothing activates a rule automatically; people approve everything. Recorded
development results (full detail in
`docs/RULE_EXTRACTION_REFLEXION_CODE_WALKTHROUGH.md`): 6/27 exact on the first
baseline, 8/27 after adding clause headings, 9/15 to 15/15 on unseen "check"
clauses after the approved lesson, and 18/18 with IGNOAPS added. The
frozen-pin check on the development check split (6 cases, 3 repeats, 36 calls,
0 USD on a free model) recorded 9/18 raw exact without the playbook and 18/18
with it, with no regressions (`eval/reports/e3_before_after_dev_2026-11-13.json`).
The sample is small (three schemes, one model) and is not held-out.

## 6. Experiments role 3 supplies code for

The guide asks whether a team of agents is worth its cost. Three
configurations run on the same cases, model, tools and budget:

- **C0** fixed workflow (no model),
- **C1** one agent holding every domain tool,
- **C2** the specialist team.

What exists in the code:

- **C1, the journey single agent** (`src/workflow/single_agent.py`): one agent
  with all ten domain actions (`SINGLE_AGENT_TOOLS`), wired into the same graph
  (`single_agent_provider` in `build_journey_graph`) and running under the same
  PII masking, budget, allow-list and fail-closed rules. It cannot approve a
  form or write portal arguments; approval stays a separate human action.
- **A restricted baseline** (`src/workflow/single_agent_baseline.py`): a
  smaller C1 with only `check_candidate`, `inspect_documents` and
  `finish_baseline`, and no portal-write tool. It refuses to inspect documents
  for an ineligible scheme and cannot finish before every candidate is checked.
  Tests: `tests/test_single_agent_baseline.py`.
- **Parity checks:** `tests/test_e1_arm_parity.py` fails if the arms stop
  sharing capabilities and budget ceilings.
- **E1 harness and live development run:** `eval/harness/e1_runner.py`,
  `scripts/evaluate_e1_workflow.py` and `scripts/run_e1_live.py`.
- **E4 offline path** (`eval/harness/e4_shadow.py`, from main): an isolated,
  non-authoritative shadow eligibility proposal beside the rule engine, plus
  a planned-vs-fixed question count (fixed 187 vs planned 177, same verdicts).
- **E4 question order, three languages** (`eval/harness/interview_sim.py`,
  `scripts/evaluate_interview_ablation_dev.py`,
  `tests/test_interview_ablation.py`): a hidden persona card answers in
  English, Hindi or Marathi, each reply goes through the production
  `parse_registered_answer`, and the *planned* picker is compared with a
  *fixed* order that asks every required fact.

**Development results** (31 development personas, not held-out, one scheme per
case; indicative only):

| Measure | Result |
|---|---|
| Same persona, English vs Hindi vs Marathi | 0 verdict differences; all match the labels |
| Questions per interview | 4.19 planned vs 5.35 fixed |

How to read it: the interview-order figures are code-only (no model calls).
E1 cost and latency come only from the team harness's recorded development
reports in `eval/reports/e1_live_dev*.json`, which carry their own cost fields.
A paid author-side run on another model is not reported here because it has no
recorded budget approval, spend figure or provider/key record. A claim that
agents are worth their cost has to rest on harder tasks and the held-out set.

## 7. Stop mid-run and resume (L8 evidence)

`python scripts/demo_resume_after_kill.py` (interview scenario) and
`... application`. A first process starts the work and dies with
`os._exit(137)`; a separate new process continues from the on-disk checkpoint.
In the application scenario the kill happens after a human approval exists on
an exact draft; the new process finds the same fingerprint, refuses a submit
with the wrong fingerprint (409) and submits once with the saved approval. The
demo uses its own portal ports (8791 and 8792) so it cannot clash with a
running dev stack. Limit: one worker, SQLite checkpointer.

## 8. Tests that cover role 3

`test_journey_graph.py`, `test_supervisor.py`, `test_planning_and_intake_agents.py`,
`test_intake_agent.py`, `test_phase3_agents.py`,
`test_document_and_application_agents.py`, `test_single_agent_journey.py`,
`test_single_agent_baseline.py`, `test_e1_*`, `test_interview_ablation.py`,
`test_cross_journey_isolation.py`, `test_rule_extraction_reflexion.py`,
`test_reflexion_models.py`, `test_reflexion_e3_eval.py`, and the per-agent
PII check in `test_pii_masking.py`. Latest full local run on the merged branch:
1298 passed, 2 failed. Both failures were environmental: a missing local
`azure` package, and a OneDrive file-sync clash on a temporary file in
`tests/fixtures`. Neither is in role 3 code.

## 9. Limits to state honestly

- E1 numbers here are development data. The held-out set belongs to role 5 and
  was never read while tuning agents.
- The planner and intake model layers fall back to deterministic code, so a
  weak model degrades to C0 rather than to a wrong answer.
- The checkpointer is SQLite on a single worker; scaling out needs a shared
  store.
- Reflexion results rest on three schemes and one model.
- `scripts/demo_approval_gate_live.py` (role 4's demo) uses document IDs that
  are not on the current checklist and probably fails; it was not changed.

## 10. What is still open for role 3

1. Final E1 run on role 5's held-out set with fixed model IDs and three
   repeats, reporting the spread.
2. E3 final claim on the protected held-out extraction cases (Role 5). The
   development before/after result is recorded and the experiment file's
   status now reflects it.
3. E4 final claim: the isolated shadow path and the question-order ablation
   already exist offline (`eval/harness/e4_shadow.py`, `tests/test_e4_shadow.py`).
   The shadow proposer there is a scripted stub, so a live LLM arm that reads
   retrieved scheme text, run on held-out personas, is still needed. That run
   belongs to Role 5.
4. The "score the extractor against 15 gold schemes" item in the roles plan:
   only four rule packages are active today (`eval/CLAIM_MATRIX.md` marks the
   15-scheme claim "not claimable"). Extending it depends on Role 1's gold
   rules; the extractor and its scoring code already work per scheme.

## 11. If asked in the viva

- *Why not let the model decide eligibility?* It can be wrong or manipulated;
  rule-engine verdicts are reproducible and traceable to a clause.
- *What stops an agent doing something unsafe?* It only holds an allow-list of
  tools, every call passes PII masking and a durable budget, and a rejected
  action stops the run.
- *What happens if the process dies mid-conversation?* The SQLite checkpoint
  and the saved budget let a new process continue; the kill demo shows it.
- *Show a rejected lesson.* The first lessons were vague ("ensure ... accurately
  reflected") and four new ones repeated each other; the vague ones were
  rejected, and only the clearest duplicate was approved (reflexion walkthrough,
  problems 17 and 18; the review command requires a reason for every rejection).
- *Is the multi-agent team worth it?* On these development cases it cost more
  than a single agent and gained nothing in accuracy; the held-out run decides
  the final claim.
