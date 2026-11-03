# Phase 3 code walkthrough: one conversation, several scheme results

This guide follows the current code from search to a shared interview, then
through rule checks, plan history, corrections and the screen. It explains
the data changes as well as the happy path. Read it beside the code; the
Python excerpts below are actual source excerpts unless labelled otherwise.

Start with [Phase 1](PHASE1_CODE_WALKTHROUGH.md) for profiles, rule packages
and the deterministic engine, then [Phase 2](PHASE2_CODE_WALKTHROUGH.md) for
the supervisor, chat and checkpoint. Those guides describe their own phases:
Phase 3 adds optional LLM answer reading, so Phase 2's statement that the
interview uses no LLM is no longer true for unsupported free text.

Plan: [Phase-wise implementation plan](PHASE_WISE_IMPLEMENTATION_PLAN.md),
section **Phase 3 — Multi-scheme and replan**.

> **Scope and safety.** This is a synthetic pilot, not a government
> eligibility or approval service. `eligible` means that the supplied facts
> meet the current mock rule package. It does not verify documents, resolve
> all policy questions or authorize a benefit. Search finds candidates,
> not eligibility. A model may propose an answer; only the deterministic
> rule engine produces an eligibility result.
>
> The main Phase 3 flow is implemented. Two important plan promises are
> narrower in the current code: new facts do **not** automatically discover
> more schemes, and the LLM-attempt list is reset on correction/restart, so
> its bound is **not conversation-wide**. Sections 7–8 explain this precisely.

---

## 1. What changes from Phase 2?

Imagine a person who may need both widow pension and farmer support. One
conversation should collect their facts, but checking one scheme must not
overwrite the other scheme's result.

| Question | Phase 3 answer |
|---|---|
| Three passages mention two schemes. How many candidates? | Two distinct scheme IDs; keep all three passages |
| Where are results kept? | A summary map and a full-result map, keyed by scheme ID |
| Who asks questions? | One intake step, using one shared `HouseholdProfile` |
| Which fact comes next? | The missing fact useful to the most undecided candidate packages |
| Who checks eligibility? | The existing MCP tool and deterministic engine, once per supported candidate, with at most one retry |
| Who writes plan-change reasons? | Python code, using the saved result and deciding rule IDs |
| What if a tool fails? | An explicit error, not an invented rejection |
| What if an answer changes? | Clear current results, reopen intake if needed, recheck all candidates |
| What if plain code cannot read a reply? | One model attempt per fact in the current attempt-list lifetime; validate and confirm a proposed value |

### The whole path

```text
Streamlit screen                         src\ui\app.py
  -> HTTP client                         src\ui\api_client.py
  -> FastAPI route                       src\api\app.py
  -> journey graph                       src\workflow\journey.py
       supervisor -> intake -> ask_user [pause]
                         ^         |
                         +-- reply-+
       intake done -> supervisor
          -> eligibility(candidate A) -> supervisor
          -> eligibility(candidate B) -> supervisor -> END
                 |
                 -> MCP adapter -> MCP tool -> deterministic engine

Every graph step can be checkpointed; GET reads the saved state.
Search is a separate request: supervisor -> intake -> search -> supervisor.
```

The interview is shared; final candidate checks are **sequential**, not
parallel. Intake already uses the local engine to avoid pointless questions.
The later eligibility step still calls the MCP rule engine to obtain each
full result and its evidence.

### Developer navigation / read order

Use this order if you are rebuilding the feature from the inside out.

| Read | File | Responsibility and connection |
|---|---|---|
| 1 | `src\rules\models.py`, `src\api\eligibility.py` | Existing profile and rules; explain `None`, derived age and verdict precedence |
| 2 | `src\workflow\state.py` | Typed plans, handoffs, summaries and history items |
| 3 | `src\workflow\question_picker.py` | Pure functions; local engine decides which schemes still need facts |
| 4 | `src\workflow\questions.py` | Fixed questions, direct parsing and fact-specific model-proposal parsing |
| 5 | `src\workflow\intake.py` | External query rewriting and structured answer interpretation; does not decide eligibility |
| 6 | `src\workflow\supervisor.py` | Build and advance the plan without I/O |
| 7 | `src\workflow\journey.py` | Wire nodes, state updates, pauses, retries, history and corrections together |
| 8 | `src\workflow\eligibility.py`, `src\workflow\scheme_search.py` | MCP callers; validate tool output and raise `MCPToolError` on failure |
| 9 | `src\api\app.py` | Load packages/checkpointer, expose start/resume/correction/read routes |
| 10 | `src\ui\api_client.py`, `src\ui\app.py` | HTTP requests, screen state, results, history and refresh restoration |

Useful words:

- **Candidate:** a scheme to consider, not a positive eligibility decision.
- **Map:** a dictionary indexed by scheme ID, such as
  `eligibility_results["IGNWPS-MH"]`.
- **Handoff:** a typed report or work assignment through the supervisor.
- **Interrupt:** a graph pause waiting for a reply.
- **Reducer:** the rule LangGraph uses to combine an update with saved state.
  Most fields replace the old value; some history lists append instead.
- **Replan:** here, a code-written plan/version update. It is not an
  autonomous LLM planner.

---

## 2. One synthetic person to follow

We will follow **Kamla**, born **30 October 1976**, with the application date
fixed to **30 October 2026** (age 50). Use synthetic facts only.

Suppose search returns these passages, in order:

1. A widow pension passage (`IGNWPS-MH`).
2. A farmer support passage (`PM-KISAN-IN`).
3. Another widow pension passage.

That yields two candidates, in that order. For the interview example,
prefill `income_tax_paid_last_assessment_year=True`: Kamla has already
reported that a family member covered by the rule paid income tax.
This prefill is supplied explicitly to the API; **search does not extract
and save it from her query**.

With that fact, PM-KISAN is already ruled out by the mock exclusion rule.
Intake therefore asks only widow-pension questions:

| Input / event | State change | Output |
|---|---|---|
| Start interview with two IDs and the tax fact | Save candidates/profile; default application date if absent | Ask `is_widow` |
| “My husband passed away last year.” | Direct parser cannot read it; a confident model may propose `True` | Ask Kamla to confirm; do **not** save widow fact yet |
| “yes” to the confirmation | Save `is_widow=True` after validation | Ask date of birth |
| “30/10/1976” | Save ISO date `1976-10-30`; derived age is 50 | Ask whether she can show the BPL card |
| “yes” | Save `bpl_card_shown=True`; no useful blanks remain | Run the two final candidate checks |
| Widow check completes | Save its full result and summary | Mock `eligible`; plan 1 → 2 |
| Farmer check completes | Save its independent result and summary | Mock `not_eligible`, `PMKISAN-INCOME-TAX-01`; plan 2 → 3 |

The free-text row is a **possible confirmed interpretation**, not a guarantee
that a live model will understand that sentence. Uncertainty or failure takes
the direct-answer path explained in section 8.

Later Kamla corrects the tax answer to “no”. That removes one exclusion,
but does **not** prove PM-KISAN eligibility. The graph must ask the still
unknown farmer facts, then run both candidates again (section 7).

---

## 3. Store candidates separately from passages and results

### 3.1 Search groups IDs, not evidence

Find `scheme_search_tool` inside `build_journey_graph` in
`src\workflow\journey.py`:

```python
candidate_scheme_ids = list(
    dict.fromkeys(passage.scheme_id for passage in passages)
)
```

`dict.fromkeys` keeps each ID's first occurrence. Our three passages produce
`["IGNWPS-MH", "PM-KISAN-IN"]`. The node separately stores every passage's
JSON, so deduplicating candidates does not discard source text or citations.

The default `_search_with_mcp` requests `SEARCH_PASSAGE_LIMIT`, currently
20. Twenty **passages** need not mean twenty **schemes**: many passages can
belong to one scheme. The returned message explicitly says search may not
find every relevant scheme. Ranking, thresholds and a single-best-passage
fallback can narrow results; that fallback does not establish multi-scheme
coverage.

### 3.2 Validate an explicit candidate request

`JourneyRequest` accepts `candidate_scheme_ids` for `interview` or
`evaluate`. Its field has `max_length=MAX_CANDIDATE_SCHEMES` (20), and
`validate_candidates`:

1. Rejects candidate lists on `search`.
2. Rejects using `scheme_id` and a nonempty candidate list together.
3. Rejects blank IDs, strips surrounding whitespace and deduplicates,
   preserving order.

The length check applies to the submitted list **before** deduplication:
21 entries are invalid even if some repeat. The API does not silently keep
only the first 20. Unknown nonblank IDs are allowed as candidates; they
become information-only if there is no loaded rule package.

A nonempty explicit list selects `multi_scheme=True`, even when it contains
only one ID. An empty list does not start a zero-candidate multi-scheme run;
without `scheme_id`, intake asks the caller to choose a scheme.

### 3.3 Why two maps and one legacy field?

`JourneyState` in `journey.py` stores plain JSON so the checkpointer can save
it. `JourneyResponse` rebuilds typed models for the API.

| Field | Contents | Why it exists |
|---|---|---|
| `candidate_scheme_ids` | Ordered unique IDs | The work list |
| `candidate_verdicts` | `CandidateVerdict` per ID | Small summary, including information-only and tool-error outcomes |
| `eligibility_results` | Full `EligibilityResponse` per successful rule-tool call | Reasons, deciding rules, evidence, notices, missing fields and unresolved checks |
| `eligibility_result` | One full result or `None` | Compatibility with the old single-scheme flow |

In `state.py`, `CandidateVerdict` has `scheme_id`, `result`,
`missing_fields` and `deciding_rule_ids`. A summary is not a substitute for
the full evidence-bearing response.

After a successful check, `eligibility_agent` returns this map update:

```python
"eligibility_results": {
    **state.get("eligibility_results", {}),
    result.scheme_id: result.model_dump(mode="json"),
},
```

Read `**` as “copy existing entries first”. Then save this scheme's entry.
Without that copy, the next node update would replace the whole map and
lose Kamla's widow result. Checking the same ID again replaces its entry.
The summary map is merged in the same way.

During checking, the legacy field holds the latest successful result.
At multi-scheme completion, the supervisor explicitly sets it to `None`:
there is no single overall eligibility verdict. A normal `scheme_id`
request retains its old single-result behavior and also fills the maps.

### 3.4 Missing package is not failed eligibility

In a multi-scheme run, an unsupported candidate reaches
`eligibility_agent`, which stores `result="information_only"` in the
summary map, without calling the tool or inventing a full result.
Intake excludes such candidates from question picking.

The old single-scheme path stops at intake with `information_only`. The
location differs, but neither path guesses eligibility.

### 3.5 New request versus refresh

`run_journey` starts again from `START`. It resets current candidates,
result maps, legacy result, passages, profile and pending interview fields.
Thus an old widow verdict is not attached to Kamla's next search.

`get_journey` only reads the checkpoint and calls `_to_response`; it does not
start another search or rule check. Missing new fields in an older saved
state use empty defaults.

**Important reducer detail:** these state declarations append:

```python
plan_change_history: Annotated[list[dict[str, Any]], add]
journey_history: Annotated[list[dict[str, Any]], add]
```

`handoffs` and `conversation` append too. Passing `[]` for these fields in
`run_journey` does **not** erase saved history: old list + empty list is
still the old list. Reusing an ID clears the result maps but retains these
histories, even though a new request starts plan numbering at 1. Do not
describe this as a fresh audit trail. Use a new conversation ID for a
separate thread; deleting the saved thread is a different API operation.

---

## 4. Pick one useful question for all undecided schemes

### 4.1 The actual algorithm

Open `pick_shared_fact` in `src\workflow\question_picker.py`. After creating
`counts = Counter()`, it does:

```python
for package in packages:
    verdict = evaluate_mock_eligibility(profile, package)
    if verdict.result != "need_more_information":
        continue
    facts = dict.fromkeys(
        fact for rule in package.rules for fact in rule.input_facts
        if getattr(profile, fact) is None and fact not in skipped_facts
    )
    counts.update(facts.keys())
return max(counts, key=counts.get) if counts else None
```

Step by step:

1. Evaluate each package against the **current shared profile**, locally.
   A decided scheme contributes no more questions. This decision does not
   depend on whether its final MCP result has already been stored.
2. Walk the remaining package's rules in file order. `rule.input_facts`
   expands derived `age` into `date_of_birth` and `application_date`.
3. Keep only unknown (`None`), unskipped profile fields.
4. Deduplicate within that package before counting. Two age rules must not
   give date of birth two votes from the same scheme.
5. Pick the largest count. Equal counts keep first insertion order:
   candidate order, then rule order, then input-fact order.
6. If no eligible-to-ask fact remains, return `None`; intake can finish.

**“Most useful” here means highest count**, not information gain, cost
optimization or an LLM judgment.

### 4.2 A small counting example

The picker test uses a synthetic second package built from the widow
package's BPL rule. It is not another supported government scheme.

| Missing fact | Widow package | Synthetic BPL-only package | Total |
|---|---:|---:|---:|
| `is_widow` | 1 | 0 | 1 |
| `date_of_birth` | 1, despite two age rules | 0 | 1 |
| `bpl_card_shown` | 1 | 1 | 2 |

BPL wins. If BPL is skipped, widow status wins the remaining tie because
its rule appears first.

The two real pilot packages do not both require date of birth. Do not use
them to claim a measured cross-scheme DOB-sharing benefit. The algorithm
supports sharing identical fields; the focused synthetic-package test
demonstrates the counting behavior.

Only identical **meaning and scope** may share a field. Similar wording
does not make personal income and family income the same fact. This picker
matches field names; it does not understand or reconcile policy semantics.

### 4.3 Apply this to Kamla

With the tax fact `True`, the local engine already says PM-KISAN is
`not_eligible`. Its land and other exclusion questions contribute no votes.
The widow package remains undecided, so intake asks widow status, birth date
and BPL, in that order. After every accepted answer it runs the picker again.

The engine gives failed exclusion/eligibility rules precedence over unknown
facts. That is why unknown farmer facts do not stop the tax exclusion from
deciding the mock result.

| Answer state | Picker treatment |
|---|---|
| `None`, not skipped | May ask |
| `False` (“no”) | Known answer; do not ask again |
| “I don't know” | Leave value unknown; add field to `skipped_facts` |
| All remaining blanks skipped | Stop asking; final result may need more information |
| BPL card answered “no” | Known `False`; do not repeat it, but the proof rule still needs `government_bpl_card` |
| Scheme already eligible/not eligible | Skip all its questions |

There are 12 stored profile fields (10 booleans and two dates). Intake
normally fills the application date with `today()`, leaving at most 11
initial unanswered fields. Invalid replies can repeat a question; “ask
once” means reuse accepted facts and do not loop on skipped unknowns, not
that every raw message must advance the interview.

---

## 5. Turn answers into state, then hand work back to the supervisor

### 5.1 Intake prepares the shared profile

Inside `intake_agent` in `journey.py`:

- `evaluate` needs a supplied profile; missing data returns
  `need_information` and required fact names.
- `interview` can start empty and defaults a missing application date.
- Both validate `HouseholdProfile`: reject undeclared fields and impossible
  date combinations, such as birth after application or age above 125.
- A multi-scheme interview builds `packages` in candidate order, including
  only IDs present in `rule_packages`.

The accepted value is merged into a **new validated profile**, rather than
mutating one unchecked field:

```python
profile = HouseholdProfile.model_validate(
    {
        **profile.model_dump(mode="json"),
        pending_fact: parsed.value,
    }
)
```

This is the direct-answer branch. Dates are serialized as ISO strings when
the profile is saved to graph state. The model-assisted branch has extra
validation and confirmation, described in section 8.

### 5.2 Pause is not completion

If a next fact exists, intake returns `status="awaiting_answer"`,
`pending_fact`, `question`, the updated profile and skip/attempt lists.
`route_after_intake` routes to `ask_user`, not to the supervisor.

In `ask_user`:

```python
reply = interrupt(
    {"question": state["question"], "fact": state["pending_fact"]}
)
```

The checkpointer preserves this pause. `resume_journey` first checks
`snapshot.interrupts`, then uses `Command(resume=message)` to continue.
The reply becomes `pending_answer` and a user conversation turn.
Intake reads it and either asks again or picks the next fact.

When nothing useful remains, intake reports
`ready_for_eligibility` through `_report_to_supervisor`. An unknown fact
does not block this forever: the final engine result can honestly be
`need_more_information`.

### 5.3 The plan and typed handoffs

`build_initial_plan` in `supervisor.py` creates:

```text
intake                             in_progress
eligibility:IGNWPS-MH              pending
eligibility:PM-KISAN-IN            pending
```

This is an explanatory rendering of the plan, not Python.
Distinct `step_id` values matter: both later steps have specialist
`eligibility`, but they are different pieces of work.

`Handoff` in `state.py` only allows supervisor-to-specialist or
specialist-to-supervisor messages. Specialists do not call each other.
On the next assignment, the graph supervisor puts the step's `scheme_id`
in state before invoking `eligibility_agent`.

`advance_plan` deep-copies the plan, finds the in-progress step for the
reporting specialist, marks its outcome, then starts the next pending step.
For eligibility, even `not_eligible`, `need_more_information` and
`information_only` mean the **check finished**, so its step is `done`.
`done` does not mean approved or eligible.

### 5.4 Record why a candidate check moved the plan on

After each multi-scheme eligibility report, the graph supervisor reads
that candidate's saved summary and chooses a reason in Python:

- `eligible`: meets the current mock rules;
- `not_eligible`: ruled out, with actual deciding rule IDs;
- `need_more_information`: still needs the listed information;
- `information_only`: no reviewed rule package, so no decision;
- `tool_error`: could not check after two attempts, so no decision.

It creates a plan at `previous_plan.version + 1` and appends a `PlanChange`
containing `from_version`, `to_version`, `scheme_id`, `result`,
`deciding_rule_ids` and `reason`. `PlanChange` rejects anything other than
one version increment. `Plan` requires a reason on versions above 1.

For Kamla the farmer note contains `PMKISAN-INCOME-TAX-01`; it is copied from
the engine result, not guessed by a model. Versions 1 → 2 → 3 record the
two completed checks. The final candidate also gets a change entry even
though the fixed reason text says “continuing with the next candidate”.

**Timing matters:** the picker stops a ruled-out scheme's questions during
intake. The visible candidate `PlanChange` is recorded **later**, after its
final eligibility step, not immediately on every answer. This is orderly
sequential plan advancement, not dynamic search or an LLM rebuilding the
work list.

At the end, multi-scheme status is `completed`, the legacy result is
`None`, and `missing_fields` combines the summaries' missing labels.
`completed` means processing finished; inspect each summary for the outcome.
There may still be missing information, unsupported schemes or tool errors.

---

## 6. Retry tools, but never turn an error into a verdict

Both `scheme_search_tool` and `eligibility_agent` use two attempts:

```python
for attempt in (1, 2):
    try:
        result = await eligibility_tool(client, scheme_id, profile)
        break
    except MCPToolError:
```

This is the opening of the actual eligibility retry block; the exception
body records the events below. There is no unbounded retry loop or backoff.
The MCP adapters wrap call failures, error responses and invalid structured
output in `MCPToolError`.

| Event | Saved note / result | What happens next |
|---|---|---|
| First MCP attempt fails | `JourneyHistoryEvent(event_type="tool_retry", attempt=1)` | Retry once |
| Retry succeeds | Keep retry note and full result | Normal supervisor advancement |
| Eligibility retry fails | `tool_failed`, attempt 2; summary `tool_error`; no full result | Mark step `failed`; continue independent candidates |
| Search retry fails | `tool_failed`, attempt 2; no passages/candidates; status `tool_error` | Stop search with an unavailable message |

`JourneyHistoryEvent` also carries the relevant `scheme_id` where
applicable and a code-written reason. Raw tool error details are not copied
into these public history reasons.

The continuation exception lives in `advance_plan`: an eligibility
`tool_error` starts the next pending candidate. Other unsuccessful
specialist reports stop the dependent plan and mark pending steps skipped.

A final multi-scheme response can therefore be `completed` while one
candidate has `tool_error`. Its message warns that some tools failed; the
UI must not present the error summary as a full eligibility result.
With 20 supported candidates, one checking pass makes at most 40 eligibility
tool attempts. Corrections can start further passes.

**Do not generalize this retry policy to every failure.** Search-query
rewriting happens before the search tool; an `IntakeAgentError` there is
handled as HTTP 502 by the start route, not retried by this tool loop.
Free-text reader failure instead falls back to a direct question. Arbitrary
programming errors are not promised to receive the MCP retry behavior.

---

## 7. Correct a known answer and remove stale current results

### 7.1 Entry and validation

`correct_journey_answer` in `journey.py` loads the saved thread.
It requires a nonempty multi-scheme state, but does not require the graph
to be paused. A completed multi-scheme run can be corrected; the legacy
single-scheme flow cannot use this endpoint.

`JourneyCorrection` accepts a known `FactName` and an answer string of
1–500 characters. The function additionally requires:

1. The chosen profile field is already non-`None`.
2. `parse_answer` returns a concrete value, not unknown/invalid.
3. The whole updated `HouseholdProfile` is valid.

Corrections use the direct parser only: no LLM proposal or confirmation.
You cannot use this operation to change a never-answered/skipped unknown,
or replace a known answer with “I don't know”. `known_fact_names` comes
from non-`None` profile fields, including the defaulted application date;
it is not restricted to values confirmed through the LLM.

### 7.2 What gets restarted?

The function merges the correction into the saved profile and starts a
new `interview` plan on the same thread with:

- the **same candidates** and corrected profile;
- empty `candidate_verdicts`, `eligibility_results` and legacy result;
- cleared pending question/confirmation state;
- existing skipped fields, except the corrected field;
- starting version equal to the old plan version + 1;
- an appended `answer_corrected` event with fact name, version and reason.

It rechecks **every candidate**, not just a computed dependency subset.
This is simple and avoids keeping stale results, but can repeat unaffected
MCP work. The old plan-change/history entries remain as historical notes,
not current verdicts. The correction event does not store the old/new
answer values; that is a property of this event, not of all stored state.

### 7.3 Continue Kamla's story

After the original plan ends at version 3, send:

```json
{"fact_name": "income_tax_paid_last_assessment_year", "answer": "no"}
```

The new plan starts at version 4. Widow facts are unchanged and already
sufficient. PM-KISAN is no longer excluded by tax, so intake now asks about
land and the still-unknown other exclusions in package order. If Kamla
answers land “yes” and the remaining exclusions “no”, its mock result can
become `eligible`. If she skips a fact, it can remain
`need_more_information`; “no tax” alone is not enough.

After intake, the widow check produces plan 4 → 5 and the farmer check
plan 5 → 6. The correction restart 3 → 4 is explained by
`JourneyHistoryEvent`, not a candidate `PlanChange`.

### 7.4 Limits the implementation still has

- Correcting farmland does **not** search for, append or remove schemes.
  The plan requirement “a new fact opens a scheme → add a step” is not
  implemented automatically. Start a deliberate new search/request to
  discover a different candidate set.
- The correction initializer contains `llm_attempted_facts` twice: first a
  copy of the saved list, then `[]`. Python uses the later value, so
  correction resets the list. `run_journey` also resets it on a new request.
  Therefore the intended “one LLM interpretation per fact per conversation”
  guarantee does not hold across these restarts. This guide documents the
  discrepancy; it does not change runtime code.
- Existing skipped unknowns remain skipped after correction. The graph can
  reopen newly useful **unskipped** questions, but does not force skipped
  facts to be asked again.
- The API accepts corrections during a multi-scheme interview, but the
  current UI returns early while `awaiting_answer`, so its correction
  controls appear only after that waiting state ends.

---

## 8. Read free text without letting the model decide facts silently

There are two different model jobs in `src\workflow\intake.py`:

| Function | Input | Output | Used when |
|---|---|---|---|
| `rewrite_scheme_query` | Search query | A concise search query | Search intake, before retrieval |
| `interpret_free_text_answer` | Current fact, fixed question, raw reply | `AnswerInterpretation` | Interview direct parsing fails and this fact has no recorded model attempt |

The answer reader does not receive the whole profile or rule results.
That limits its context; it does not mean the service stores no answers.

### 8.1 First try plain code

`parse_answer` in `questions.py` normalizes spacing, case, trailing
punctuation and curly apostrophes. It recognizes yes/no words, explicit
unknowns such as `idk`/`skip`, and listed date formats.

```text
is_widow + "YES."          -> value True
date_of_birth + 30/10/1976 -> date value
is_widow + "not sure"      -> unknown, not False
is_widow + "maybe"         -> invalid
```

This is explanatory input/output notation. No model is needed for the
first three examples. A parsed but impossible date fails **profile**
validation and gets a direct correction hint; the reader is not called
merely because a syntactically valid answer conflicts with the profile.

### 8.2 Structured output is only the first check

`AnswerInterpretation` permits:

```python
kind: Literal["value", "unknown", "uncertain"]
value: StrictBool | StrictStr | None = None
confidence: float = Field(ge=0, le=1)
```

It rejects extra fields and requires a non-`None` value if and only if
`kind=="value"`. The external request asks for a strict JSON schema. The
local model validates the returned content again.

The prompt tells the model to treat the reply as data, ignore instructions
inside it and not infer unstated facts. This is an instruction and layered
validation, **not proof of prompt-injection immunity or correct meaning**.

`_read_free_text_answer` requires `OPENROUTER_API_KEY`, uses
`OPENROUTER_CHAT_MODEL` (default `openai/gpt-4o-mini`), temperature 0 and
a 30-second HTTP timeout. The async wrapper runs it with
`asyncio.to_thread`. Missing configuration, HTTP/transport failure or invalid
model output becomes `IntakeAgentError`.

### 8.3 Follow the proposal through the graph

When direct parsing is invalid, intake records the fact in
`llm_attempted_facts` **before** invoking the reader. A failed attempt still
counts. The graph then applies these gates:

1. Require `confidence >= 0.85` for a usable value or explicit unknown.
   Confidence is model-reported, not a measured probability of correctness.
2. For a value, call `parse_interpreted_answer` to check the fact's type.
   A boolean fact needs a real boolean; `"yes"` as a string is rejected.
   A date fact needs a string accepted by the direct date parser.
3. Validate a hypothetical merged `HouseholdProfile`. A well-typed but
   impossible birth date is still invalid.
4. Save the proposal in `pending_interpreted_value`, set
   `pending_confirmation=True` and ask:
   `I understood your answer as "yes". Is that correct? Please answer yes or no.`
   The actual profile is **not** updated yet.
5. On explicit confirmation, parse the proposal and validate the merged
   profile again, then save it and pick the next question.

This explains Kamla's two-message widow answer: her sentence proposes a
value; her “yes” authorizes saving that value.

| Reader / confirmation outcome | State behavior |
|---|---|
| High-confidence, valid value | Pause for confirmation; not a saved fact yet |
| Confirmation “yes” | Revalidate and save proposed value |
| Confirmation “no” | Discard proposal; ask original question with direct-answer hint |
| Other confirmation, including unknown | Keep proposal; ask for explicit yes/no; no second model call |
| High-confidence `unknown` | Leave fact `None`, mark skipped, move on without a value-confirmation prompt |
| `uncertain`, low confidence or wrong fact type | No proposed fact saved; repeat fixed question with hint |
| Invalid structured response or `IntakeAgentError` | Same direct-question fallback |
| Another unsupported reply for an attempted fact | Direct-question fallback, not another model call |

The fixed questions are still from `QUESTIONS`; the model does not rewrite
them. No LLM writes the final eligibility result, plan or plan-change reason.

### 8.4 What is actually bounded?

Within an uninterrupted interview's attempt-list lifetime, each of the 12
profile facts can trigger at most one reader call. Direct answers, unknowns
recognized by code, confirmations and declined proposals do not trigger
additional reader calls. With the application date already filled, a fresh
empty interview normally has at most 11 facts needing answers.

The external reader itself has no retry loop. User messages/clarifications
are not globally capped, and the correction/restart reset in section 7
allows more reader calls later on the same conversation ID. Do not describe
12 as a lifetime conversation-wide call cap. Query rewriting and retrieval
model calls are separate from this answer-reader bound.

---

## 9. Trace the HTTP request into the screen and back

### 9.1 API routes and stored state

`src\api\app.py` loads rule packages at startup, opens
`AsyncSqliteSaver`, and builds the graph with the MCP client. The default
checkpoint database is `data\runtime\journey.sqlite3`; override it with
`SCHEME_SAATHI_CHECKPOINT_DB`.

| Route | Request / function | Important behavior |
|---|---|---|
| `POST /api/v1/journey` | `JourneyRequest` → `run_journey` | Start search, evaluate or interview; malformed request gets 422 |
| `POST /api/v1/journey/{conversation_id}/messages` | `JourneyMessage` → `resume_journey` | 1–500 characters; 409 if no saved interrupt is waiting |
| `POST /api/v1/journey/{conversation_id}/corrections` | `JourneyCorrection` → `correct_journey_answer` | 409 if no multi-scheme state; 422 for invalid/unknown-valued correction |
| `GET /api/v1/journey/{conversation_id}` | `get_journey` | Read current saved response; unknown thread is 404 |
| `DELETE /api/v1/journey/{conversation_id}` | Checkpointer `adelete_thread` | Delete that thread's saved checkpoints; success is 204 |

Here is Kamla's **example request body**, sent to the start route. Fixing
the application date keeps the example independent of today; she supplies
her birth date later in the chat:

```json
{
  "action": "interview",
  "candidate_scheme_ids": ["IGNWPS-MH", "PM-KISAN-IN"],
  "profile": {
    "application_date": "2026-10-30",
    "income_tax_paid_last_assessment_year": true
  }
}
```

Use the returned `conversation_id` in later message/correction paths.
A message body is `{"message":"yes"}`; it answers the **currently pending**
question, which may be a confirmation rather than the original fact.

The final response includes these relationships (**illustrative shortened
JSON shape**, not a complete response or complete full-result objects):

```json
{
  "status": "completed",
  "eligibility_result": null,
  "candidate_scheme_ids": ["IGNWPS-MH", "PM-KISAN-IN"],
  "candidate_verdicts": {
    "IGNWPS-MH": {"scheme_id": "IGNWPS-MH", "result": "eligible"},
    "PM-KISAN-IN": {
      "scheme_id": "PM-KISAN-IN",
      "result": "not_eligible",
      "deciding_rule_ids": ["PMKISAN-INCOME-TAX-01"]
    }
  },
  "eligibility_results": {
    "IGNWPS-MH": {"result": "eligible"},
    "PM-KISAN-IN": {"result": "not_eligible"}
  }
}
```

Real full results also contain reasons, evidence and other required fields.
`_to_response` supplies `question`/`pending_fact` only while awaiting an
answer, plus typed history and `known_fact_names` for correction choices.

### 9.2 The screen does not run the graph

In `src\ui\api_client.py`, each helper makes one HTTP request and validates
the reply as `JourneyResponse`. Start, message and correction requests have
60-second client timeouts; GET uses 10 seconds. HTTP/transport/response-shape
errors become `JourneyApiError`; the UI is not guaranteed an end-to-end
latency below these limits.

Follow these functions in `src\ui\app.py`:

1. **Search-screen block:** sends `JourneyRequest(action="search", ...)`.
   It groups passage IDs into `scheme_names` by first occurrence, still
   showing the selected scheme's individual passages and source links.
2. **`start_candidate_interview`:** “Check all found schemes” sends those
   distinct IDs in one interview request. It reuses the current conversation
   ID when present. It does not prefill a profile from the search text.
3. **`save_journey`:** copies the response into `st.session_state`: plan,
   messages, question, status, both result maps, both histories and known
   fact names. Streamlit reruns the script after interactions, so ordinary
   local variables would not be enough.
4. **`render_candidate_interview`:** draws the plan, “Why the plan changed”,
   retry/failure/correction notes and conversation. While awaiting an
   answer it offers `st.chat_input`; send → save response → `st.rerun()`.
5. **Result panels:** each summary gets an expander. A full result goes to
   `render_verdict`, which shows the reason, missing fields, policy notices,
   unresolved checks and deciding-rule source links. A `tool_error` without
   a full result gets an error; an information-only summary gets an
   information notice.
6. **Corrections:** after waiting ends, nonempty `known_fact_names` enables
   a fact selector and answer input. Save calls the correction API, replaces
   screen state with its response, and reruns. If more facts are needed,
   the screen goes back to the shared chat.

The old single-scheme “Continue to the synthetic eligibility demo” entry
remains. It is not the same as checking all search candidates.

### 9.3 Refresh reads; it does not repeat the interview

`remember_in_url` writes `conversation=<uuid>` plus either `scheme=<id>` or
comma-separated `schemes=<ids>`. It does not put answer values in the URL.

On a fresh page session, the restoration block checks the UUID and candidate
count/single-scheme choice, then calls `get_journey_state` once. If a saved
response exists, `save_journey` restores the pending question, history and
results. Invalid or unavailable restoration clears the URL. The client
turns a GET 404 into `None`; other API failures raise an error that this
restoration block also handles by not restoring.

This is API-backed restoration, not proof of manual browser testing.
Checkpoints contain the profile, raw conversation turns, pending proposals
and histories. Avoiding answer values in URLs or correction events does
**not** mean answers are never stored, never sent to the configured model,
or protected by a demonstrated access-control/privacy system.

---

## 10. Tests: what to read and what each establishes

Tests replace external calls where possible. Graph tests use `MemorySaver`,
fixed dates and fake readers/tools; some fake eligibility tools call the
real local engine. API tests start the API and local MCP server. UI tests
use Streamlit `AppTest` with mocked API helpers, not a manually driven
browser.

| File / useful test | Evidence to look for |
|---|---|
| `tests\test_question_picker.py` → `test_shared_picker_counts_each_fact_once_per_scheme` | Synthetic BPL sharing wins; duplicate age rules do not double-count; skipped fact and stable tie behavior |
| `tests\test_journey_graph.py` → `test_candidate_schemes_are_unique_and_new_search_clears_old_results` | Three passages become two candidates; evidence remains; old result maps clear; reload preserves new IDs |
| Same → `test_shared_interview_continues_after_one_scheme_is_ruled_out` | Tax-prefilled scenario like Kamla; only three widow questions; distinct results, information-only extra candidate, version changes and reload |
| Same → `test_shared_interview_unknown_answers_terminate_and_keep_each_missing_list` | Unknowns do not loop; both schemes retain honest missing-information results |
| Same → `test_tool_retry_and_final_failure_are_recorded_without_fake_verdict`, `test_search_retry_and_failure_are_recorded` | Two attempts, explicit errors, continued candidate checking and safe public failure reasons |
| Same → `test_correcting_answer_rechecks_schemes_and_records_no_answer_value` | Current results recomputed, version increases, correction note/reload; does not prove a lifetime LLM cap |
| Same → `test_free_text_interpretation_requires_confirmation_before_saving`, `test_declined_interpretation_reasks_for_a_direct_answer` | Proposed fact absent until confirmed; unclear confirmation/decline handling |
| Same → `test_answer_reader_failure_uses_plain_code_question`, `test_clear_free_text_unknown_skips_the_fact_without_inventing_a_value` | Reader failure and model-reported unknown paths |
| `tests\test_questions.py` → `test_interpreted_answers_must_match_the_fact_type` | Wrong-type proposals are rejected by the parser |
| `tests\test_intake_agent.py` | Structured request and response validation, including bad confidence, extra fields and inconsistent unknown/value |
| `tests\test_supervisor.py`, `tests\test_workflow_state.py` | Plan advancement/copy behavior, required replan reason, valid supervisor handoffs |
| `tests\test_api_eligibility.py` → multi-candidate and correction tests | HTTP contract, full results through local MCP, validation failures |
| `tests\test_ui_app.py` → `test_check_all_found_schemes_starts_one_shared_chat` | Shared start body, candidate URL, visible history and correction submission with mocked API |
| Same → refresh tests | GET restoration and forgotten-thread URL cleanup in AppTest |

The tests are useful evidence for these individual behaviors, not proof that
all policy semantics, every catalogue scheme, every failure mode or every
browser interaction is validated.

### Focused commands (Windows, repository root)

The repository has `.venv`; do not use the older `..\venv` path from prior
notes. These are **developer validation commands**, not claims that they
were rerun for this documentation-only edit.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_question_picker.py tests\test_questions.py tests\test_intake_agent.py tests\test_supervisor.py tests\test_workflow_state.py tests\test_journey_graph.py
```

For the API/UI boundary:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_api_eligibility.py tests\test_ui_app.py
```

The supplied verified baseline before this rewrite is **177 passing tests**.
A full suite, when needed for a code change, is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

There is no dedicated documentation test command in the current project
configuration/CI. For this documentation-only change, check source/test
references, excerpts, local links and:

```powershell
git diff --check
```

---

## 11. Keep implementation, smoke tests and retrieval quality separate

These are different kinds of evidence:

| Evidence available before this rewrite | What it establishes | What it does not establish |
|---|---|---|
| 177 passing automated tests | Tested code behavior at the recorded baseline | Production readiness, policy correctness or browser-manual validation |
| A successful live-chat smoke with synthetic two-scheme facts | Configured reader could propose/confirm an answer and the flow returned separate deterministic results | Reliability for all natural-language replies, live hybrid retrieval quality or real government decisions |
| BM25-only diagnostic: 43 development queries, 13 reviewed passages, two schemes | Local lexical-retrieval behavior on that tiny development set | Configured live hybrid/vector/reranked performance or catalogue-wide candidate coverage |

The supplied BM25-only diagnostic measured:

- Passage recall@5: **0.7558**.
- Scheme-hit rate@5: **0.7907**.
- Recall@5 by query language: English **0.9545**, Hindi **0.2**, Marathi **0**.

The set includes three cross-scheme queries. In
`scripts\evaluate_scheme_retrieval.py`, scheme hit means **at least one**
relevant scheme appears, not that every relevant scheme was found.
Recall is the mean fraction of labelled relevant passages retrieved per
query. Neither metric is eligibility accuracy.

The free embedding key was not configured for the current diagnostic;
no live hybrid retrieval evaluation was performed for this Phase 3 check.
Do not silently substitute the different, older fused-retrieval numbers in
[the retrieval backlog](RETRIEVAL_IMPROVEMENT_BACKLOG.md) for these BM25-only
numbers. That backlog also records provisional multilingual/cross-scheme
labels needing bilingual/domain review.

Be careful reproducing experiments: the evaluator's `--skip-reranker`
option disables reranking, **not vectors**. It is not a BM25-only switch.
This walkthrough does not ask you to run any external/paid model call.

### What Phase 3 does not claim

- Not every suitable scheme is retrieved; only the supplied/discovered,
  bounded candidate list is processed.
- The journey search wrapper supplies the query and passage limit; it does
  not expose the separate search adapter's jurisdiction/language filters
  through `JourneyRequest`.
- A newly learned fact does not automatically search/add schemes.
- Correction rechecks all candidates, not a minimal affected subset.
- LLM call limits are not conversation-wide across correction/restart.
- History reducers do not erase old events when updated with `[]`.
- `completed` does not mean all candidates are eligible or successfully
  evaluated; check each candidate's summary and full result/error.
- There is no LLM planner, generated search-answer summary, document
  authenticity check or application submission in this shared interview.
- There is no new browser-manual validation or blanket privacy guarantee
  behind this documentation update.

To improve retrieval claims, first expand the reviewed corpus and validate
query labels, then evaluate the exact configured retrieval path. To improve
the two runtime gaps identified here, change and test the implementation in
a separate code task; do not fix them by writing stronger documentation.
