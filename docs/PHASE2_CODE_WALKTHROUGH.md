# Phase 2 code walkthrough: a supervisor and a chat that asks questions

This guide explains what Phase 2 built, in plain English. It is written for a
new developer who has not seen this code before, and who might want to build
Phase 2 again from scratch. It follows one conversation from the chat box to
the rule engine and back. It also lists every edge case Phase 2 handles.

Read [PHASE1_CODE_WALKTHROUGH.md](PHASE1_CODE_WALKTHROUGH.md) first. Phase 2
builds directly on the profile, rule packages and engine from Phase 1.

Phase 2 plan: [PHASE_WISE_IMPLEMENTATION_PLAN.md](PHASE_WISE_IMPLEMENTATION_PLAN.md).

---

## The problem Phase 2 solves

After Phase 1, every scheme used one path, but the **user still filled in a
form** (PM-KISAN) or **picked a made-up person** (widow pension). Real people
do not know which facts a scheme needs. A helper at a government counter does
not hand you a form with every question; they ask **only what matters**, one
question at a time, and stop as soon as they know the answer.

| | Before Phase 2 | After Phase 2 |
|---|---|---|
| How facts are collected | A form with all 8 PM-KISAN questions, or a preset person | A chat: one question at a time |
| Which questions | All of them, always | Only the ones the rules still need |
| When it stops | When you press Submit | As soon as the verdict is decided (e.g. after one "No") |
| "I don't know" | A drop-down option | Typed in the chat; never asked again |
| Who decides the order of work | A fixed line of nodes | A **supervisor** that writes a visible plan |
| What the user sees of the plan | One line of text | A checklist with ✅ ⏳ ⬜ icons |
| Page refresh | Everything lost | The chat continues from the same question |

**What did not change:** the rule engine still decides every verdict. The
new interview uses **no language model (LLM)**: questions are fixed text and
answers are read by plain code. This keeps the interview free and the
behaviour the same every time. (Scheme search, from earlier work, still uses
an LLM to reword the search query; that is not part of the interview.)

---

## The big picture

Think of an office counter with a manager and helpers:

```
                ┌──────────────────────┐
                │  SUPERVISOR (manager)│  writes the plan, hands out work,
                │                      │  reads each helper's report
                └──────────┬───────────┘
          ┌────────────────┼──────────────────┐
          ↓                ↓                  ↓
       INTAKE          ELIGIBILITY          SEARCH
   asks questions,    asks the rule       finds schemes
   checks answers     engine (via MCP)    (Phase 0 work)
```

Helpers never talk to each other. Each one **reports back to the
supervisor**, and the supervisor decides what happens next.

How one answer travels through the code:

```
 You type "yes" in the chat
          │
          ▼
 ┌──────────────────────────────┐   Step 6
 │ UI  src/ui/app.py            │   st.chat_input → send_journey_message
 │     src/ui/api_client.py     │
 └─────────┬────────────────────┘
           │ POST /api/v1/journey/{id}/messages
           ▼
 ┌──────────────────────────────┐   Step 5
 │ API  src/api/app.py          │   409 if nothing is waiting
 └─────────┬────────────────────┘
           │ resume_journey(...)
           ▼
 ┌──────────────────────────────────────────────┐   Step 4
 │ Journey graph  src/workflow/journey.py       │
 │   ask_user (was paused) → intake_agent       │
 │   intake reads the answer   (Step 2)         │
 │   intake picks next fact    (Step 1)         │
 │   → another question? pause again            │
 │   → done? report to supervisor (Step 3)      │
 │        → eligibility_agent → MCP → engine    │
 └──────────────────────────────────────────────┘
```

We build it **from the inside out**, in the order you would write it:

| Step | File | What it does | Needs |
|---|---|---|---|
| 1 | `src/workflow/question_picker.py` | Chooses the next fact to ask | Phase 1 engine |
| 2 | `src/workflow/questions.py` | Question text; turns a reply into a value | Nothing |
| 3 | `src/workflow/supervisor.py` | Writes the plan and moves it forward | Phase 1 contracts |
| 4 | `src/workflow/journey.py` | The graph: supervisor, intake, pause and resume | Steps 1–3 |
| 5 | `src/api/app.py` | Two new web routes | Step 4 |
| 6 | `src/ui/api_client.py`, `src/ui/app.py` | The chat and plan checklist | Step 5 |

Steps 1–3 are **pure functions**: no web, no database, no graph. You can
write and test each one alone, in a few minutes, before touching LangGraph.

### Words you will meet

| Word | Meaning in this project |
|---|---|
| **Fact** | One field of `HouseholdProfile`, e.g. `is_widow` or `date_of_birth` |
| **Node** | One step in the graph; an `async` function that gets the state and returns changes |
| **Edge** | An arrow between nodes. A *conditional* edge picks the next node by reading the state |
| **State** | The shared dictionary every node reads (`JourneyState`) |
| **Checkpointer** | Saves the state after every node, in SQLite, keyed by conversation ID |
| **Thread** | One saved conversation. Our `conversation_id` is the thread ID |
| **Interrupt** | Pausing the graph in the middle, waiting for the user |
| **Resume** | Continuing a paused graph with the user's reply |
| **Handoff** | A typed message: supervisor → helper ("do this") or helper → supervisor ("done") |
| **Plan** | The visible checklist of steps, each with a status |

### Meet our test people

The application date is always **30 October 2026** (the tests fix "today").
All of these were run through the real graph and engine; the results below
are the real output.

| Person | Scheme | What they type | Questions asked | Result |
|---|---|---|---|---|
| **Sunita** | widow pension | yes · 30 October 1976 · yes | 3 | eligible |
| **Meera** | widow pension | yes · 31/10/1986 | 2 (stops early) | not eligible, `IGNWPS-MH-AGE-MIN-01` |
| **Lata** | widow pension | yes · 30 Oct 1976 · no | 3 | need more information, `government_bpl_card` |
| **Usha** | widow pension | no | 1 (stops at once) | not eligible, `IGNWPS-MH-WIDOW-01` |
| **Asha** | widow pension | idk · not sure · skip | 3 | need more information, 3 facts missing |
| **Gopal** | PM-KISAN | yes, then "no" ×7 | 8 | eligible (mock only) |
| **Ramesh** | PM-KISAN | yes · no · no · no · no · **yes** (income tax) | 6 (stops early) | not eligible, `PMKISAN-INCOME-TAX-01` |
| **Kamla** | PM-KISAN | "don't know" ×8 | 8 | need more information, 8 facts missing |
| **Bina** | PM-KISAN | no (no land) | 1 | not eligible, `PMKISAN-LAND-FAMILY-01` |

Notice: **Ramesh is never asked the last two questions**, and **Meera is
never asked about her BPL card**. Once one rule fails, more answers cannot
change the result. This is the main idea of Phase 2.

---

## Step 1: The question picker (`src/workflow/question_picker.py`)

### What it is

A "picker" is a function that **picks** the next question. It answers one
question: *"Given what we know so far, what should we ask next, if anything?"*

```python
def pick_next_fact(profile, package, skipped_facts=frozenset()) -> str | None:
```

- **In:** the profile so far (unknown facts are `None`), the scheme's rule
  package, and the facts the person already said "I don't know" to.
- **Out:** a field name like `"date_of_birth"`, or `None` meaning "stop
  asking".

### How it works (3 steps)

```python
# 1. Ask the engine where we stand.
verdict = evaluate_mock_eligibility(profile, package)
if verdict.result != "need_more_information":
    return None                     # already eligible or not eligible: stop

# 2. Walk the rules in file order; ask the first blank fact.
for rule in package.rules:
    for fact in rule.input_facts:
        if getattr(profile, fact) is None and fact not in skipped_facts:
            return fact

# 3. Nothing left that we may ask.
return None
```

**Why ask the engine first?** We reuse the Phase 1 engine instead of writing
new logic. If the engine has already decided, no answer can change it, so
asking more would waste the person's time. That is why Ramesh stops after
the income-tax question.

**Why walk the rules in order?** The rule file is written in a sensible order
("Are you a widow?" before age). Walking it in order gives a stable, natural
question order, and the same profile always gives the same next question.

### What is `input_facts`?

Some rules check a **derived** fact, one that is calculated, not stored. The
age rule checks `age`, but the profile stores `date_of_birth` and
`application_date` (Phase 1: "calculate, don't store"). We cannot ask "what
is your age on the application date?", so each rule lists the **real profile
fields** it needs:

```
rule IGNWPS-MH-AGE-MIN-01   field = "age"
                             input_facts = ("date_of_birth", "application_date")
```

This mapping lives in `DERIVED_FACT_INPUTS` in `src/rules/models.py`. A rule
on a normal fact (like `is_widow`) has `input_facts = ("is_widow",)`.

### Walk-through: Sunita

| Profile so far | Engine says | First blank fact in rule order | Picker returns |
|---|---|---|---|
| only `application_date` | need more information | `is_widow` (rule WIDOW-01) | `is_widow` |
| + `is_widow=True` | need more information | `date_of_birth` (rule AGE-MIN-01) | `date_of_birth` |
| + `date_of_birth=1976-10-30` | need more information | `bpl_card_shown` (rule BPL-01) | `bpl_card_shown` |
| + `bpl_card_shown=True` | **eligible** | — | `None` (stop) |

### Why "No" to the BPL card is not asked again

Lata answers "no" to "Can you show a BPL card?". The engine returns *need
more information* (the BPL rule is a "show proof" rule, from Phase 1). The
picker walks the rules, but `bpl_card_shown` is now `False`, **not `None`**,
so it is not blank and is not asked again. The picker returns `None`, and the
verdict tells Lata to show a card. Asking the same question again would be
an endless loop.

### Edge cases for Step 1

| Case | Picker returns | Why |
|---|---|---|
| Verdict already `eligible` | `None` | Nothing can change it |
| Verdict already `not_eligible` (e.g. Ramesh) | `None` | A failure wins (Phase 1 lesson) |
| A fact answered "I don't know" | Skips it | It is in `skipped_facts`, so no loop |
| Every blank fact was skipped (Asha, Kamla) | `None` | Nothing left that we may ask |
| A proof fact answered "No" (Lata) | `None` | `False` is known, not blank |
| A fact needed by two rules (`date_of_birth` for AGE-MIN and AGE-MAX) | Asked once | After it is answered it is no longer blank |
| `application_date` is already filled | Never asked | Intake fills it with today's date (Step 4) |

---

## Step 2: Questions and answers (`src/workflow/questions.py`)

### What it is

Two jobs:

1. **Question text.** `QUESTIONS` maps each of the 12 profile fields to a
   plain English question. `question_for("is_widow")` → `"Are you a widow?"`.
2. **Answer reading.** `parse_answer(fact, reply)` turns what the person
   typed into a value for that fact.

### The result of reading an answer

```python
@dataclass(frozen=True)
class ParsedAnswer:
    kind: Literal["value", "unknown", "invalid"]
    value: bool | date | None = None
    error: str | None = None
```

| `kind` | Meaning | What intake does next |
|---|---|---|
| `value` | We understood it; `value` holds `True`, `False` or a date | Saves it in the profile |
| `unknown` | The person does not know | Adds the fact to `skipped_facts` |
| `invalid` | We did not understand; `error` says how to answer | Asks the same question again with the hint |

Three kinds, not two. "I don't know" is a **real answer** and must not be
mixed up with "I typed nonsense".

### How a reply is read

```python
text = _normalise(reply)        # " Yes. " → "yes";  "don’t know" → "don't know"
if text in DONT_KNOW_WORDS:     # works for every question
    return ParsedAnswer(kind="unknown")
if fact in BOOL_FACTS:          # yes/no questions
    yes → True,  no → False,  anything else → invalid + YES_NO_HINT
else:                           # the only other kind of fact is a date
    try each format in DATE_FORMATS → date,  none match → invalid + DATE_HINT
```

`_normalise` does four small things:

- lower-case: `"YES"` → `"yes"`;
- trim spaces and trailing `. ! ?`: `"  Yes!  "` → `"yes"`;
- squeeze repeated spaces: `"12   March 1981"` → `"12 march 1981"`;
- turn the curly apostrophe from phone keyboards (`’`) into `'`, so
  "don’t know" matches "don't know".

### Accepted answers

| Kind | Accepted words |
|---|---|
| Yes | yes, y, yeah, yep, true, correct |
| No | no, n, nope, false |
| Don't know | i don't know, i dont know, don't know, dont know, not sure, unknown, idk, skip |

Accepted dates (**day first**, the Indian order):

| Typed | Read as |
|---|---|
| `1981-03-12` | 12 March 1981 |
| `12/03/1981`, `12-03-1981`, `12.03.1981` | 12 March 1981 (never 3 December) |
| `12 March 1981`, `12 Mar 1981` | 12 March 1981 |
| `March 12 1981`, `March 12, 1981` | 12 March 1981 (commas are ignored) |

### Edge cases for Step 2

All of these were run against the real function:

| Fact | Reply | Result |
|---|---|---|
| `is_widow` | `Y` | value `True` |
| `is_widow` | `  YES!  ` | value `True` |
| `is_widow` | `maybe` | invalid: `Please answer "yes", "no" or "I don't know".` |
| `bpl_card_shown` | `I don’t know` (curly apostrophe) | unknown |
| `date_of_birth` | `March 12, 1981` | value 1981-03-12 |
| `date_of_birth` | `31/02/1990` (no 31 February) | invalid: date hint |
| `date_of_birth` | `12/03/81` (2-digit year) | invalid: date hint (we refuse to guess the century) |
| `date_of_birth` | `1981/03/12` | invalid: date hint (not a listed format) |
| `date_of_birth` | `31/12/2030` | **value** here; rejected later by the profile check (Step 4) |

The last row matters: `parse_answer` only checks that the text **is a
date**. Whether the date **makes sense** (not after the application date) is
checked by `HouseholdProfile`, the same check as Phase 1. One rule, one
place.

**Why plain code and not an LLM?** It is free, instant, and gives the same
result every time, so it is easy to test. Later an LLM can read free text
like "my husband passed away last year", but this code stays as the safety
net.

---

## Step 3: The supervisor's plan (`src/workflow/supervisor.py`)

### What it is

Three small pure functions that manage the **plan**, the checklist shown on
screen. They use the Phase 1 contracts `Plan` and `PlanStep` from
`src/workflow/state.py`.

Each step has a status:

| Status | Icon on screen | Meaning |
|---|---|---|
| `pending` | ⬜ | Not started |
| `in_progress` | ⏳ | Running now (or waiting for your answer) |
| `done` | ✅ | Finished |
| `failed` | ❌ | Could not finish |
| `skipped` | ➖ | Not run because an earlier step failed |

### `build_initial_plan(action, scheme_id)`

Writes the first plan and starts step 1:

| `action` | Steps |
|---|---|
| `interview` | ⏳ Learn about you → ⬜ Check the rules for IGNWPS-MH |
| `evaluate` | ⏳ Check your answers → ⬜ Check the rules for IGNWPS-MH |
| `search` | ⏳ Understand your request → ⬜ Find source-cited schemes |

### `advance_plan(plan, specialist, status)`

Called when a helper reports back. Returns `(new plan, next step or None)`.

```
Was the reported status a success for that helper?   (SUCCESS_STATUSES)
├── yes → mark this step done; start the next pending step (or None if none left)
└── no  → mark this step failed; mark every pending step skipped; return None
```

`SUCCESS_STATUSES` says what "success" means for each helper:

| Helper | Success statuses |
|---|---|
| intake | `ready_for_eligibility`, `searching` |
| search | `search_results` |
| eligibility | `eligible`, `not_eligible`, `need_more_information` |

**Why is `not_eligible` a success?** The eligibility helper's job is to
*give a verdict*, and it did. "Not eligible" is a correct answer, not a
broken step. A failure means the step **could not do its job**, e.g. intake
got an information-only scheme.

`advance_plan` works on a **copy** (`model_copy(deep=True)`), so the plan you
pass in is never changed by accident. A test proves this.

### `plan_summary(plan)`

The one-line text `"Plan: Learn about you -> Check the rules for IGNWPS-MH"`.
It is kept so older screens and tests still work.

### Edge cases for Step 3

| Case | Plan after |
|---|---|
| Sunita finishes intake | ✅ Learn about you, ⏳ Check the rules |
| Rules checked (any verdict) | ✅ ✅, next step `None` → the run ends |
| Information-only scheme (PMAY-G-IN) | ❌ Learn about you, ➖ Check the rules |
| No scheme chosen | ❌ Learn about you, ➖ Check the rules for the chosen scheme |

---

## Step 4: The graph, with pause and resume (`src/workflow/journey.py`)

This is the biggest step. Read it slowly.

### The new shape

Phase 1 was a straight line: `orchestrator → intake → eligibility`. Phase 2
is a **star**: the supervisor sits in the middle and every helper returns to
it.

```
START → supervisor ──(next_agent?)──┬─► intake_agent ──(question?)──► ask_user
            ▲                       │        │                          │
            │                       │        └──(done)──► supervisor    └──► intake_agent
            │                       ├─► eligibility_agent ──► supervisor
            │                       ├─► scheme_search_tool ──► supervisor
            │                       └─► END
            └─────────── every helper reports back here
```

The wiring, near the end of `build_journey_graph`:

```python
graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", lambda state: state["next_agent"], {
    "intake": "intake_agent",
    "eligibility": "eligibility_agent",
    "search": "scheme_search_tool",
    END: END,
})
graph.add_conditional_edges("intake_agent", route_after_intake,
                            {"ask_user": "ask_user", "supervisor": "supervisor"})
graph.add_edge("ask_user", "intake_agent")
graph.add_edge("eligibility_agent", "supervisor")
graph.add_edge("scheme_search_tool", "supervisor")
```

### New state keys

| Key | Meaning |
|---|---|
| `plan_detail` | The full `Plan` as JSON (the checklist) |
| `next_agent` | Who the supervisor chose next: `"intake"`, `"eligibility"`, `"search"` or END |
| `handoffs` | Every message between the supervisor and helpers. It **grows** (see below) |
| `pending_fact` | The field the current question is about, e.g. `"date_of_birth"` |
| `question` | The question text shown to the user |
| `pending_answer` | The user's raw reply, put here by `ask_user` |
| `skipped_facts` | Facts answered "I don't know" |

`handoffs` and `conversation` are written as
`Annotated[list[...], add]`. That tells LangGraph: *when a node returns this
key, **add** the new items to the end instead of replacing the list.* So
each node returns only its new message, and the history builds up.

### Node 1: `supervisor`

It runs in two situations:

**First visit (no plan yet):** write the plan, send a handoff to the first
helper, and set `next_agent`.

```python
plan = build_initial_plan(state["action"], state.get("scheme_id"))
return {"plan_detail": ..., "next_agent": "intake",
        "handoffs": [Handoff(sender="supervisor", recipient="intake", ...)]}
```

**Later visits (a helper just reported):** read the **last** handoff, which
is the helper's report, and move the plan forward.

```python
report = state["handoffs"][-1]          # e.g. sender="intake", payload={"status": "ready_for_eligibility"}
plan, next_step = advance_plan(plan, report["sender"], report["payload"]["status"])
next_agent = next_step.specialist if next_step else END
```

Helpers report with a small helper function:

```python
"handoffs": _report_to_supervisor("intake", "ready_for_eligibility")
```

The `Handoff` contract from Phase 1 makes sure a helper can only send to the
supervisor, never to another helper.

### Node 2: `intake_agent` (the interview part)

Intake first runs the same four gatekeeper checks as Phase 1 (scheme chosen?
rules exist? profile sent? profile valid?). Two changes for `interview`:

- A missing profile is **allowed**; we will ask for the facts.
- If `application_date` is empty, it is set to **today**. People apply
  today, and asking "what date are you applying?" would be odd. (`today` is
  passed into `build_journey_graph` so tests can fix the date.)

Then the interview logic:

```
Is there a pending question AND a reply?
├── yes → parsed = parse_answer(pending_fact, reply)
│         ├── unknown → add the fact to skipped
│         ├── invalid → ask the SAME question again, with the hint        ─► pause
│         └── value   → put it in the profile and re-check the whole profile
│                       └── check fails → "That answer does not fit: …"  ─► pause
└── no  → (first visit: nothing to read yet)

next_fact = pick_next_fact(profile, package, skipped)
├── a fact → status "awaiting_answer", question = question_for(fact)      ─► pause
└── None   → status "ready_for_eligibility", report to the supervisor
```

**Why re-check the whole profile after each answer?** Some checks involve
two fields. "Date of birth cannot be after the application date" can only be
checked with both. We rebuild `HouseholdProfile` with the new value, so the
same Phase 1 checks run. If they fail, the error is turned into friendly
words:

```
"Value error, date_of_birth cannot be after application_date"
→ "That answer does not fit: date of birth cannot be after application date."
```

`route_after_intake` then reads the status: `awaiting_answer` → `ask_user`,
anything else → `supervisor`.

### Node 3: `ask_user`, the pause

```python
async def ask_user(state):
    reply = interrupt({"question": state["question"], "fact": state["pending_fact"]})
    return {"pending_answer": reply,
            "conversation": [{"role": "user", "content": reply}]}
```

This tiny node is the heart of Phase 2. `interrupt()` behaves differently on
two visits:

| Visit | What `interrupt()` does |
|---|---|
| First | **Stops the whole run.** The checkpointer has already saved the state. `ainvoke` returns, and the API sends the question to the screen. |
| Second (after the user replies) | The node **runs again from its first line**, and this time `interrupt()` **returns the reply** instead of stopping. |

Because the node runs again from the top, **never put code with side effects
before `interrupt()`** (like saving to a database), or it would happen twice.
Our node has nothing before it.

After `ask_user`, the edge goes back to `intake_agent`, which reads the
reply. This is the question loop: `intake → ask_user → intake → ask_user …`
until the picker returns `None`.

### Node 4: `eligibility_agent`

Unchanged from Phase 1 except for one line: it now reports back to the
supervisor (`_report_to_supervisor("eligibility", result.result)`) instead of
going straight to END.

### The three entry functions

These are what the API calls.

**`run_journey(graph, request)`: start a new request.**

```python
initial_state = {
    "action": ..., "scheme_id": ..., "profile": request.profile,
    "plan_detail": None, "status": "", "eligibility_result": None,
    "pending_fact": None, "question": None, "pending_answer": None,
    "skipped_facts": [], "conversation": [], ...
}
result = await graph.ainvoke(initial_state, config=_thread_config(conversation_id))
```

**Why reset every key?** The checkpointer remembers the last state of this
conversation. If we only sent `action` and `scheme_id`, the old plan,
profile and skipped facts from an earlier request would **leak in**. For
example, the supervisor would see an old `plan_detail` and skip writing a new
plan. Resetting each per-request key gives every request a clean start, while
`conversation` and `handoffs` keep growing as history (adding `[]` adds
nothing).

**`resume_journey(graph, conversation_id, message)`: answer a question.**

```python
snapshot = await graph.aget_state(config)
if not snapshot.interrupts:                 # nothing is waiting
    raise JourneyNotWaitingError(...)
result = await graph.ainvoke(Command(resume=message), config=config)
```

`Command(resume=message)` is LangGraph's way to say *"continue the paused
run, and give `interrupt()` this value"*. We check `snapshot.interrupts`
first because resuming a conversation that is not paused would do the wrong
thing quietly. Raising an error is safer.

**`get_journey(graph, conversation_id)`: reload after a refresh.**

Reads the saved state with `aget_state`. Returns `None` if there is nothing
saved (unknown ID, or the saved values have no status).

**`_to_response`** turns the raw state into the typed `JourneyResponse`. It
only fills `question` and `pending_fact` while the status is
`awaiting_answer`, so a finished conversation never shows an old question.

### One full conversation, step by step (Sunita)

| # | Who calls | Nodes that run | Status returned | Plan |
|---|---|---|---|---|
| 1 | `run_journey(interview, IGNWPS-MH)` | supervisor (writes plan) → intake (picks `is_widow`) → ask_user **pauses** | `awaiting_answer`: "Are you a widow?" | ⏳ ⬜ |
| 2 | `resume_journey("yes")` | ask_user (gets "yes") → intake (saves `True`, picks `date_of_birth`) → ask_user **pauses** | `awaiting_answer`: "What is your date of birth?" | ⏳ ⬜ |
| 3 | `resume_journey("30 October 1976")` | ask_user → intake (saves date, picks `bpl_card_shown`) → ask_user **pauses** | `awaiting_answer`: "Can you show a BPL card?" | ⏳ ⬜ |
| 4 | `resume_journey("yes")` | ask_user → intake (picker says stop) → supervisor (intake done) → eligibility → MCP → engine → supervisor (all done) → END | `eligible` | ✅ ✅ |

Each call ends either at a pause or at END. Between calls, **nothing is
running**; the conversation only exists as saved state in SQLite.

### Edge cases for Step 4

| Case | What happens |
|---|---|
| "maybe" to a yes/no question | Same question again: `Please answer "yes", "no" or "I don't know". Are you a widow?` |
| Date of birth `31/12/2030` | `That answer does not fit: date of birth cannot be after application date.` + the same question |
| "I don't know" | Not asked again; the verdict lists it as missing |
| Every answer "I don't know" (Kamla) | 8 questions, then `need_more_information` listing all 8; no endless loop |
| A deciding "No"/"Yes" early (Usha, Bina, Ramesh, Meera) | Questions stop at once; verdict with the failing rule ID |
| Interview with a pre-filled profile `{"is_widow": true}` | The first question is `date_of_birth`; known facts are not asked |
| Pre-filled profile `{"is_widow": "maybe"}` | `invalid_input`, missing `is_widow`; no questions |
| Information-only scheme | `information_only`; plan ❌ ➖; no questions, engine not called |
| No scheme | `need_information`, missing `scheme_id`; plan ❌ ➖ |
| Reply sent when nothing is waiting (finished, never started, unknown ID) | `JourneyNotWaitingError` |
| A new request while a question is waiting | The new request starts fresh from START; the old question is dropped |
| `application_date` not given | Set to today; never asked |

---

## Step 5: The API (`src/api/app.py`)

Phase 1 had `POST /api/v1/journey` and `DELETE /api/v1/journey/{id}`.
Phase 2 adds `action="interview"` to the first, and two new routes:

| Method and path | Calls | Success | Errors |
|---|---|---|---|
| `POST /api/v1/journey` with `{"action": "interview", "scheme_id": "..."}` | `run_journey` | 200, first question | 502 if MCP fails |
| `POST /api/v1/journey/{id}/messages` with `{"message": "yes"}` | `resume_journey` | 200, next question or verdict | **409** not waiting · **422** empty / over 500 characters / ID not a UUID · 502 MCP |
| `GET /api/v1/journey/{id}` | `get_journey` | 200, saved state | **404** "Conversation not found." · 422 bad ID |

```python
@app.post("/api/v1/journey/{conversation_id}/messages")
async def journey_message(conversation_id: UUID, journey_message: JourneyMessage, request):
    try:
        return await resume_journey(request.app.state.journey_graph,
                                    conversation_id, journey_message.message)
    except JourneyNotWaitingError as error:
        raise HTTPException(status_code=409,
                            detail="This conversation is not waiting for an answer.") from error
```

Things FastAPI does for us:

- `conversation_id: UUID` → anything that is not a UUID gets **422**
  automatically, before our code runs.
- `JourneyMessage` has `message: str = Field(min_length=1, max_length=500)`
  and `extra="forbid"` → an empty message, a very long one, or an unknown
  field gets **422**. The 500 limit stops someone sending a huge text.

**Why 409?** 409 means "Conflict: your request does not fit the current
state". The conversation exists, but it is not waiting. This happens when
the page is open in two tabs and one already answered.

### Try it with PowerShell (API running on port 8000)

```powershell
$b = 'http://127.0.0.1:8000/api/v1/journey'
$r = Invoke-RestMethod -Method Post -Uri $b -ContentType 'application/json' `
     -Body '{"action":"interview","scheme_id":"PM-KISAN-IN"}'
$r.question          # Does the farmer family have cultivable land in State/UT records?
$id = $r.conversation_id
$r = Invoke-RestMethod -Method Post -Uri "$b/$id/messages" -ContentType 'application/json' `
     -Body '{"message":"yes"}'
$r.question          # Is the land held by an institution?
Invoke-RestMethod "$b/$id"   # reload the same state
```

---

## Step 6: The screen (`src/ui/app.py`, `src/ui/api_client.py`)

### The API client

`src/ui/api_client.py` now has four small functions, one per route:

| Function | Route | Special handling |
|---|---|---|
| `run_journey(request)` | `POST /journey` | — |
| `send_journey_message(id, message)` | `POST /journey/{id}/messages` | Checks the 1–500 limit first and shows "Please type a shorter answer"; 409 becomes "This conversation is no longer waiting for an answer. Start again." |
| `get_journey_state(id)` | `GET /journey/{id}` | **404 returns `None`** ("nothing saved" is normal, not an error) |
| `forget_journey(id)` | `DELETE /journey/{id}` | — |

All share one `_send` helper. Every failure becomes a `JourneyApiError` with
a short, safe message. Server details are never shown to the user.

### Remember: Streamlit reruns the whole file

Every click or typed message runs `app.py` again **from the top**. Local
variables are lost. Everything the chat needs is kept in
`st.session_state`. `save_journey(journey)` copies one API reply into it:

| `session_state` key | Holds |
|---|---|
| `conversation_id` | The conversation ID (as text) |
| `journey_plan_detail` | The plan, for the checklist |
| `journey_status` | e.g. `awaiting_answer` or `eligible` |
| `journey_conversation` | The list of chat messages |
| `interview_result` | The verdict, once there is one |
| `interview_message` | The last message (shown if there is no verdict) |
| `interview_scheme_id` | Which scheme this chat is for |

### `render_interview(scheme_id, text, can_start=True)`

Draws the chat in three states:

```
interview_scheme_id != scheme_id ?     → show the "Start questions" button
                                          (click → start_interview → rerun)
otherwise:
    render_plan(...)                     the ✅ ⏳ ⬜ checklist
    one st.chat_message per turn         the history
    status == "awaiting_answer" ?        → st.chat_input (the answer box)
                                          (typed → send_journey_message → save → rerun)
    else                                 → render_verdict(...) + "Start again" button
```

- `st.chat_message(role)` draws a speech bubble for `"user"` or
  `"assistant"`.
- `st.chat_input(...)` is the box at the bottom. It returns the typed text
  **once**, on the rerun right after the person presses Enter, and `None`
  otherwise.
- The answer box only exists while the status is `awaiting_answer`. When
  the chat is finished there is nothing to type into, so a late reply cannot
  be sent from the screen.

`render_verdict` shows the verdict (green, red or yellow), the reason, the
notice, missing facts, a disabled "Refer to a human caseworker" button when
facts are missing, and one expandable box per rule with the official source.

### Which screen uses the chat

| Scheme | What you see after "Continue" |
|---|---|
| PM-KISAN | The notice, then the chat. **The old 8-question form is gone.** |
| Widow pension | Consent, then a choice: **Answer questions** (the chat, default) or **Use an example person** (the Phase 1 screen) |

**Why keep "Use an example person"?** The draft, approve and mock-submit
demo needs the example person's details (reference, district). The chat
does not collect those yet. That arrives in Phase 4. Until consent is
ticked, the "Start questions" button is disabled (`can_start=consent`).

### Coming back after a page refresh

A browser refresh empties `st.session_state`. To survive it, the chat writes
two **non-personal** values into the address bar:

```
http://localhost:8501/?conversation=0e8fa6c3-...&scheme=PM-KISAN-IN
```

Only the random conversation ID and the scheme ID are stored there, **never
an answer**. On every page load:

```
URL has ?conversation= AND session is empty AND we have not tried yet ?
├── scheme is one we support AND the ID is a real UUID → get_journey_state(id)
│     ├── found  → save_journey(...), open the chat, show "Your earlier conversation was restored."
│     └── None   → clear the URL (nothing to restore)
└── otherwise    → clear the URL
```

`restore_tried` makes sure we ask the API **once**, not on every rerun.
"Forget my demonstration data" and "Choose another scheme" both clear the URL
too.

### Text in three languages

Every new screen text has English, Hindi and Marathi versions in the `COPY`
dictionary: `plan_title`, `interview_title`, `interview_notice`,
`interview_start`, `interview_restart`, `interview_reply`,
`interview_error`, `widow_mode`, `mode_chat`, `mode_example`, `restored`.
The old PM-KISAN form labels were removed. **Known limit:** the questions
and plan steps come from the backend and are **English only** for now.

### Edge cases for Step 6

| Case | What the user sees |
|---|---|
| API not running when starting | "Could not continue the conversation: Could not reach the journey API…" |
| Answer longer than 500 characters | "Please type a shorter answer (up to 500 characters)." No request is sent |
| Two tabs; the other tab already answered | "This conversation is no longer waiting for an answer. Start again." |
| Refresh in the middle of the chat | The same question comes back with the history and plan |
| Refresh after "Forget" (saved data deleted) | API returns 404 → URL cleared → normal search screen |
| Someone edits the URL to a broken ID | Not a UUID → URL cleared; the API is not even called |
| URL with an unsupported scheme | URL cleared |
| Chat finished | No answer box; "Start again" begins a new interview in the same conversation |
| Widow pension before consent | "Start questions" is disabled |
| Search again | The old chat and result are cleared |

---

## A search fix found by testing with the real LLM

All the tests above use a **fake** LLM and a fake search, so they are free.
After Phase 2 we also ran the whole flow once with the **real** OpenRouter
calls: type a question → search → Continue → interview → verdict. That run
found a problem the fake tests could not.

### How search picks what to show

1. The LLM rewrites the user's words into a clean search query.
2. Search finds candidate passages (pieces of official scheme text).
3. A **reranker** gives each passage a **score from 0 to 1**: "how well does
   this answer the question?" Think of it as marks out of 100.
4. Only passages scoring **0.3 or more** are shown
   (`HOSTED_RERANK_MIN_SCORE`). The value 0.3 was chosen earlier from our 43
   test questions; it removes most wrong passages.

### The problem

| Question | Best passage | Score | Shown? |
|---|---|---|---|
| "I am a widow aged 50, is there a pension?" | Widow pension | 0.56 | Yes |
| "I am a small farmer with 1 acre land, any money support from government?" | PM-KISAN benefit | **0.239** | **No: "No matching passages were found"** |

The LLM rewrite was good ("government financial support for small farmers
with 1 acre land"). The reranker also put the right passage **first**. But
the question uses everyday words, so the score was lower, and the 0.3 rule
threw away the right answer. The farmer could never reach the interview.

### The fix: a second chance for the top answer

- **Rule 1 (unchanged):** show every passage scoring 0.3 or more.
- **Rule 2 (new):** if **nothing** passed Rule 1, take only the **single
  top passage**, and show it if it scores at least **0.2**
  (`HOSTED_RERANK_FALLBACK_MIN_SCORE`). Otherwise show "no results".

```python
# src/api/scheme_search.py, end of HybridSchemeRetriever.search()
kept = tuple(
    passage
    for _, (score, passage) in reranked
    if min_score is None or float(score) >= min_score
)[:limit]
if not kept and fallback_min_score is not None:
    best_score, best_passage = reranked[0][1]   # list is sorted, best first
    if float(best_score) >= fallback_min_score:
        return (best_passage,)                  # only ONE passage is rescued
return kept
```

The MCP search tool (`src/mcp_servers/tools/scheme_search.py`) passes
`fallback_min_score=0.2` only when the hosted reranker is used, the same as
`min_score=0.3`.

### Why 0.2 (and not 0.15)

We scored some **off-topic** questions with the real reranker. We have no
scheme for these, so the right answer is "no results":

| Question | Top passage | Score |
|---|---|---|
| Small farmer, money support (**should** be shown) | PM-KISAN benefit | **0.239** |
| Housing subsidy (Pradhan Mantri Awas Yojana) | PM-KISAN benefit | **0.145** |
| Business loan for women | Widow pension | 0.042 |
| Scholarship, health card, passport | Widow pension | 0.034–0.037 |
| Cricket score, paneer recipe, "ignore previous instructions" | Widow pension | 0.012–0.019 |

The cutoff must sit **between 0.145 and 0.239**. 0.15 would be only just
above the housing question, so a slightly different housing question could
wrongly show PM-KISAN. **0.2 sits safely in the middle.**

### Edge cases

| Situation | What happens | Why |
|---|---|---|
| Some passages score ≥ 0.3 | Exactly as before; Rule 2 is not used | Rule 2 runs only when Rule 1 found nothing |
| Nothing ≥ 0.3, top is 0.24 | One passage shown | Second chance |
| Nothing ≥ 0.3, two passages at 0.24 and 0.21 | **Only the top one** shown | A weak search should not fill the screen |
| Nothing ≥ 0.3, top is 0.145 (housing) | "No matching passages were found" | Below 0.2 |
| Local reranker instead of the hosted one | No cutoffs at all, as before | The 0.3 and 0.2 values are for Cohere scores only |

**Test:** `test_fallback_keeps_only_the_best_passage_when_none_pass_min_score`
in `tests/test_scheme_search.py` uses fake scores 0.24 and 0.21. With a 0.2
fallback it expects only the 0.24 passage; with 0.25 it expects nothing.

**Limit:** 0.2 is based on about 10 live questions. If we add schemes or
change the reranker, check it again with more off-topic questions.

---

## How Phase 2 is tested

Run the whole suite from the repository folder:

```powershell
cd C:\Users\Admin\OneDrive\Documents\Saathi\scheme-saathi-capstone
..\venv\Scripts\python.exe -m pytest -q
```

Expected: **152 passed** (151 at the end of Phase 2, plus the search
fallback test above).

| Test file | What it proves |
|---|---|
| `tests/test_question_picker.py` | Rule-order questions, stop when decided, skipped facts not asked, PM-KISAN stops after income tax, land asked first |
| `tests/test_questions.py` | Yes/no/don't-know words, punctuation and curly apostrophe, day-first dates, impossible dates, hints |
| `tests/test_supervisor.py` | The interview plan starts with intake; success moves on; failure ❌ and ➖ the rest; the caller's plan is not changed |
| `tests/test_journey_graph.py` | Full interviews through the graph: eligible, plan while waiting, unclear answer, impossible date, "don't know", Ramesh stops early, not-waiting error, reload, a new request replaces a waiting one, default application date |
| `tests/test_api_eligibility.py` | Over HTTP with the **real MCP server**: a whole interview, 409 after it ends, 422 for an empty reply, 404 for an unknown conversation |
| `tests/test_ui_app.py` | PM-KISAN: Continue → Start questions → answer → verdict, URL saved; refresh restores the chat; a forgotten conversation cleans the URL; widow pension still works with "Use an example person" |

The graph tests pass **fakes** for the MCP tool and LLM, and a fixed `today`,
so they are fast and free. The UI tests use Streamlit's `AppTest` and replace
the API client functions with fakes (`unittest.mock.patch`).

### Try it yourself in Python

No server needed. This runs the real graph with the engine called directly:

```python
import asyncio
from datetime import date
from langgraph.checkpoint.memory import InMemorySaver
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.workflow.journey import (
    JourneyRequest, build_journey_graph, resume_journey, run_journey,
)

provider = RulePackageProvider()
packages = {s: provider.get(s) for s in ("IGNWPS-MH", "PM-KISAN-IN")}

async def engine(client, scheme_id, profile):
    return evaluate_mock_eligibility(profile, packages[scheme_id])

graph = build_journey_graph(
    None, packages,
    eligibility_tool=engine,
    checkpointer=InMemorySaver(),          # in memory instead of SQLite
    today=lambda: date(2026, 10, 30),
)

async def main():
    r = await run_journey(graph, JourneyRequest(action="interview", scheme_id="IGNWPS-MH"))
    print(r.question)                      # Are you a widow?
    for answer in ["yes", "31/10/1986"]:   # Meera
        r = await resume_journey(graph, r.conversation_id, answer)
        print(r.status, r.question or r.eligibility_result.deciding_rule_ids)
    # awaiting_answer What is your date of birth? ...
    # not_eligible ['IGNWPS-MH-AGE-MIN-01']

asyncio.run(main())
```

Try other answers: "maybe", "I don't know", "31/12/2030".

### Manual UI test checklist

Start the app with `..\venv\Scripts\python.exe -m src.run_services all` and
open http://127.0.0.1:8501.

- [ ] Search "farmer income support", choose PM-KISAN, Continue, **Start
      questions**. Only one question shows; the plan shows ⏳ Learn about you.
- [ ] Search "I am a small farmer with 1 acre land, any money support from
      government?". One PM-KISAN result shows (the search fallback).
- [ ] Search "housing subsidy". No results.
- [ ] Answer "yes", then "no" ×4, then "yes" for income tax. Questions stop;
      red not-eligible with `PMKISAN-INCOME-TAX-01`; plan ✅ ✅.
- [ ] Start again and answer "maybe". The same question comes back with a
      hint.
- [ ] Answer "don't know" to everything. It ends after 8 questions and lists
      what is missing.
- [ ] Widow pension: tick consent, keep **Answer questions**, start. Answer
      yes · 30 October 1976 · yes → eligible.
- [ ] Type the date `31/12/2030` → "That answer does not fit…".
- [ ] In the middle of a chat, press F5. The chat comes back at the same
      question with "Your earlier conversation was restored."
- [ ] Click "Forget my demonstration data", then refresh. The search screen
      shows; the URL has no `conversation`.
- [ ] Widow pension with **Use an example person**: draft → approve → mock
      submit still works.

---

## Common mistakes when building this yourself

| Mistake | What goes wrong | The fix used here |
|---|---|---|
| Asking a fact again after "No" | Endless loop for proof facts like the BPL card | Ask only facts that are `None` |
| Asking again after "I don't know" | Endless loop | `skipped_facts` |
| Not resetting state in `run_journey` | Old plan, profile or answers leak into a new request | Reset every per-request key |
| Compiling the graph without a checkpointer | `interrupt()` cannot save the pause | Always pass a checkpointer |
| Sending a new request (not `Command(resume=...)`) to answer | The graph restarts from START and asks question 1 again | Answers go through `resume_journey` |
| Resuming without checking `snapshot.interrupts` | A late reply is silently mixed into a finished conversation | Raise `JourneyNotWaitingError` → 409 |
| Code with side effects before `interrupt()` | It runs twice (the node restarts on resume) | Keep `ask_user` tiny |
| Checking dates only in `parse_answer` | Two rules in two places, which drift apart | `parse_answer` reads; `HouseholdProfile` validates |
| Reading month-first dates | 03/04/1981 becomes 4 March for an Indian user | Day-first formats only |
| Keeping chat data in normal variables in Streamlit | Lost on the next rerun | `st.session_state` |
| Putting answers in the URL | Personal data in browser history | Only the random ID and scheme ID |

---

## Files changed in Phase 2

| File | Change |
|---|---|
| `src/workflow/question_picker.py` | **New**: `pick_next_fact` |
| `src/workflow/questions.py` | **New**: `QUESTIONS`, accepted words, date formats, `ParsedAnswer`, `parse_answer` |
| `src/workflow/supervisor.py` | **New**: `build_initial_plan`, `advance_plan`, `plan_summary`, `SUCCESS_STATUSES` |
| `src/workflow/journey.py` | Rewritten: supervisor node, interview intake, `ask_user` with `interrupt()`, `resume_journey`, `get_journey`, new state and response fields |
| `src/api/app.py` | New `POST /journey/{id}/messages` and `GET /journey/{id}` |
| `src/ui/api_client.py` | New `send_journey_message`, `get_journey_state`; shared `_send` |
| `src/ui/app.py` | Chat, plan checklist, widow mode choice, refresh restore, new text in 3 languages; PM-KISAN form removed |
| Tests | New `test_question_picker.py`, `test_questions.py`, `test_supervisor.py`; new cases in the journey, API and UI tests |
| Docs | Phase plan status, README journey section, this guide |
| `src/api/scheme_search.py`, `src/mcp_servers/tools/scheme_search.py` | After Phase 2: the search fallback (`HOSTED_RERANK_FALLBACK_MIN_SCORE = 0.2`) |

---

## Known limits (planned for later phases)

- Questions and plan steps are **English only**.
- Answers must be yes / no / don't know or a date; free text like "my husband
  died last year" is not understood yet (an LLM reader comes later, with
  this code as the safety net).
- One scheme per chat. Checking several schemes and changing the plan when a
  result rules one out is **Phase 3**.
- The widow chat does not prepare a draft; document checks and the approval
  pause are **Phase 4**.
- No guardrails yet (e.g. masking an Aadhaar number typed into the chat):
  **Phase 5**.

---

## Key lessons

1. **Ask only what can change the answer.** Let the engine say when the
   verdict is decided, and stop.
2. **"I don't know" is an answer.** Record it so you never ask again.
3. **Three outcomes, not two.** A reply is a value, "unknown", or "not
   understood"; each needs different handling.
4. **One check, one place.** The parser reads; the profile model validates.
5. **A manager with helpers.** Helpers report to the supervisor; only the
   supervisor decides what is next. This makes the plan visible and easy to
   change in Phase 3.
6. **Pausing is saving.** `interrupt()` works because the checkpointer saved
   the state. Between messages, nothing runs.
7. **Reset what belongs to one request; keep what is history.**
8. **The AI never decides eligibility.** The Phase 2 interview has no AI
   in it at all; only search rewording uses an LLM.
