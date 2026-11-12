# Role 3 work on 2026-11-12: what changed and why

Written for: team members who need to understand, and defend in the viva,
the role 3 (agents and orchestration) additions made on this branch.

Role 3's job in the capstone guide is the graph, the planner, the agents, the
rule extractor and the improvement loop, plus the evidence that they work.
Most of that already existed. This round closed the **evidence gaps** the
guide asks for. Nothing here changes how a citizen's request is decided: the
rule engine still decides every verdict, and a person still approves every
submission.

## What was already done (not touched)

- LangGraph graph with typed state, conditional edges, SQLite checkpointer.
- Supervisor, intake, eligibility, documents and application agents.
- Question picker, rule extractor, Reflexion playbook 1.0.0 (frozen).
  Recorded results: baseline 6/27, then 9/15 to 15/15 with the lesson, 18/18
  with IGNOAPS (`RULE_EXTRACTION_REFLEXION_CODE_WALKTHROUGH.md`).

## What was pending, and the step taken for each

| # | Guide requirement | Gap found | What I added | Why it is needed |
|---|---|---|---|---|
| 1 | L11 / E1: "single-agent baseline with the same tools and budget" | No C1 existed; the E1 config was a stub | `src/workflow/single_agent.py`, a `single` prompt in `agent_config.py`, `tests/test_single_agent_baseline.py` | Without a baseline you cannot say whether a team of agents is worth its cost. |
| 2 | L8: "same persona gets same verdicts in Hindi, Marathi, English"; "measure questions per conversation" | Neither was measured | `eval/harness/interview_sim.py`, `scripts/evaluate_interview_ablation_dev.py`, `tests/test_interview_ablation.py` | These are signature challenge B and the E4 question-order arm. |
| 3 | L8: "stop the process mid-run and resume it" | Only in-process SQLite reopen tests existed | `scripts/demo_resume_after_kill.py` (two scenarios) | A real hard kill is the evidence the guide asks for; reopening a DB in one process is weaker. |
| 4 | L8: "a graph diagram" | None generated | `scripts/export_graph_diagram.py` and `docs/GRAPH_DIAGRAM.md` | Generated from the compiled graph, so it cannot drift from the code. |
| 5 | E1: compare C0, C1, C2 on the same cases | No runner | `eval/harness/e1_runner.py`, `eval/harness/dry_run_model.py`, `scripts/evaluate_e1_dry_run.py`, `scripts/run_e1_live.py`, `tests/test_e1_runner.py` | One harness, config-driven, as the guide requires. |

### Step 1: single-agent baseline (C1)

One agent holds every read tool (`check_candidate`, `inspect_documents`,
`finish_baseline`) and runs through the same `run_agent` path as the team, so
PII masking, durable budget, tool allow-list and traces are identical. It has
no portal-write tool, because approval-gated drafting is the same in every
configuration. Verdicts still come only from the rule engine; the model only
chooses which candidate to check. A rejected action stops the run
(fail-closed). *Why:* a fair comparison needs identical safety controls and
budget, so any difference comes from the decision structure alone.

### Step 2: language parity and question count

A hidden persona card answers in English, Hindi or Marathi using the words
the real parser accepts; each reply goes through the production
`parse_registered_answer`. Two strategies are compared: **planned** (the
production picker asks only what a still-undecided rule needs) and **fixed**
(ask every required fact). Result on 31 development personas: 0 verdict
differences across languages, all verdicts match the expected labels, mean
questions 4.19 planned vs 5.35 fixed. *Why:* shows the verdict does not
depend on the language and that planned questioning asks fewer questions.
*Limit:* one scheme per persona, no model involved, development data only.

### Step 3: kill and resume

`python scripts/demo_resume_after_kill.py` (interview) and `... application`.
A first process starts the work, then dies with `os._exit(137)`; a separate
new process continues from the on-disk checkpoint. The application scenario
kills after a human approval exists on an exact draft; the new process finds
the same fingerprint, refuses a wrong-fingerprint submit (409) and submits
once with the saved approval. The demo uses its own portal ports (8791/8792)
so it cannot collide with a running dev stack, and removes only orphaned
portals on those ports. *Limit:* SQLite checkpointer, single worker.

### Step 4: graph diagram

`python scripts/export_graph_diagram.py` compiles the real graph (no model, no
network) and writes Mermaid to `docs/GRAPH_DIAGRAM.md`, with a note on each
node and where each minimum-bar item lives.

### Step 5: E1 harness, dry run, then a live run

`run_e1` runs C0 (fixed workflow, no model), C1 (single agent) and C2 (the
eligibility and document specialists) on the same cases, tools and budget,
and reports task success, errors, model calls, tokens, median and 95th
percentile latency. The model is pluggable:

- **Dry run** (scripted fake model): proves the wiring only; never an E1
  result.
- **Live run** (`scripts/run_e1_live.py`): real OpenRouter calls using the
  model in `.env`, on development personas only, with caps on cases and total
  calls. The key is never printed.

## E1 live result (development personas, not the final claim)

Model `openai/gpt-4.1-mini` for C1 and C2, 31 development cases, 3 repeats
in one event loop, 435 model calls in total, 0 errors. Raw report:
`eval/reports/e1_live_dev_latest.json` (reports are not committed, so these
numbers are copied here).

| Config | Task success (3 repeats) | Model calls / case | Tokens / case | Median latency | 95th-pct latency |
|---|---|---|---|---|---|
| C0 fixed workflow | 31, 31, 31 of 31 | 0 | 0 | about 0 ms | about 0 ms |
| C1 single agent | 31, 31, 31 of 31 | 2.23 | 670 | 2.04 to 2.06 s | 3.1 to 3.7 s |
| C2 specialist team | 31, 31, 31 of 31 | 2.45 | 706 | 2.11 to 2.34 s | 4.6 to 4.7 s |

Reading it honestly:
- Accuracy is identical because the rule engine decides every verdict in all
  three configurations; the models only choose which tool to call and when
  to stop. The agents did not make any verdict worse, and did not make any
  better.
- The team (C2) used about 10% more model calls, about 5% more tokens and
  had a higher 95th-percentile latency than the single agent (C1). For
  these tasks, with one scheme per case, the team bought no accuracy.
- A fixed workflow (C0) is free and equally correct here. Any claim that
  agents are worth their cost has to rest on tasks where the rule engine
  alone is not enough (free-text intake, several candidate schemes), and on
  the held-out set. This run does not show that.
- Token counts come from the scrubbed traces; treat them as indicative, not
  as billed cost.

## Problems found along the way

- **Event loop bug in my own live script.** The first full live run showed
  one C1 error in repeats 2 and 3. Cause: one `asyncio.run` per repeat closed
  the loop under a cached HTTP client. Fixed by running all repeats in one
  loop; the affected run is kept as `eval/reports/e1_live_dev_run1_loop_bug.json`
  and is not quoted.
- **Stale demo.** `scripts/demo_approval_gate_live.py` uses document IDs
  (`age_proof`, `bpl_proof`) that are not on the current IGNWPS-MH checklist,
  so its document step likely fails. Not changed (role 4's demo).
- **Stale status text** in `eval/experiments/e3_playbook.json`: real E3
  results already exist in the walkthrough document.
- **Environment.** The venv was missing `prometheus_client`; installed by you,
  after which the previously failing agent tests passed.

## What the numbers do and do not show

- E1 live numbers in this repo are **development** data. The held-out set
  belongs to role 5, and I did not read it, because the person tuning the
  agent must not see the held-out cases.
- C0, C1 and C2 all get the same verdicts because the rule engine decides
  them in every configuration. The comparison is therefore about cost and
  latency, not accuracy.
- Changing the embedding or vision model in `.env` does not affect E1 (no
  retrieval in it) but does affect retrieval/Recall@5 and needs a re-index.

## Still open for role 3 (needs people or budget, not code)

1. Final E1 run on role 5's held-out set with the fixed final model IDs,
   repeated three times, spread reported.
2. E3 confirmation with more runs (paid) and refreshing its stale status.
3. E4 LLM-direct eligibility arm (evaluation-only path; compare boundary
   errors with the rule engine) on held-out personas.

## Files added or changed

Added: `src/workflow/single_agent.py`, `eval/harness/interview_sim.py`,
`eval/harness/e1_runner.py`, `eval/harness/dry_run_model.py`,
`scripts/demo_resume_after_kill.py`, `scripts/export_graph_diagram.py`,
`scripts/evaluate_interview_ablation_dev.py`, `scripts/evaluate_e1_dry_run.py`,
`scripts/run_e1_live.py`, `docs/GRAPH_DIAGRAM.md`, and three test files.
Changed: `src/workflow/agent_config.py` (new prompt only),
`eval/experiments/e1_agent_cost.json`, `eval/experiments/e4_signature_ablation.json`,
`docs/CONTRIBUTIONS.md`.
