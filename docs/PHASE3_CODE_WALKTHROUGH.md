# Phase 3 code walkthrough

This guide grows with the implementation. It describes what is actually
built, not everything planned.

**Current progress: candidate storage, shared interviewing, plan history,
tool retries/failure history, answer correction, and safe free-text answer
reading are implemented in the API and screen.** The live-model multi-scheme
smoke test and the available 43-query retrieval evaluation are complete.
Retrieval has only been evaluated on the current two-scheme pilot corpus.

Plan: [PHASE_WISE_IMPLEMENTATION_PLAN.md](PHASE_WISE_IMPLEMENTATION_PLAN.md).

## Step 1: give each scheme its own place

### The problem

Before this step, the journey stored one `eligibility_result`.
If we checked widow pension and then PM-KISAN, that single place would not
be enough to keep both results.

This storage lets the journey keep the second check separate and preserve
both results safely.

### Example: three passages, two schemes

Search returns these passages:

1. Widow pension benefit.
2. PM-KISAN benefit.
3. Widow pension age requirement.

There are three passages, but only two candidate schemes:

```python
candidate_scheme_ids = ["IGNWPS-MH", "PM-KISAN-IN"]
```

In `src/workflow/journey.py`, the search node groups scheme IDs:

```python
"candidate_scheme_ids": list(
    dict.fromkeys(passage.scheme_id for passage in passages)
),
```

`dict.fromkeys` keeps the first occurrence of each ID. We preserve search
order. We do not delete repeated scheme passages: their text and citations
may still be useful.

Being a candidate means "search found information about this scheme".
It does not mean eligible. Search can miss schemes too.

### Three new storage fields

| Field | What it holds |
|---|---|
| `candidate_scheme_ids` | Distinct scheme IDs for this request |
| `candidate_verdicts` | Short results, indexed by scheme ID |
| `eligibility_results` | Full rule-engine results, including reasons and evidence, indexed by scheme ID |

The existing `eligibility_result` stays unchanged so Phase 2 clients still
work. `JourneyResponse` exposes the new fields through the existing API.
`JourneyState` stores JSON versions so the checkpointer can save them.

### What happens when one scheme is checked?

The existing eligibility node still calls the MCP rule engine for just the
selected scheme. Suppose the widow answer is "no".

The node stores:

```python
candidate_verdicts["IGNWPS-MH"] = CandidateVerdict(
    scheme_id="IGNWPS-MH",
    result="not_eligible",
    deciding_rule_ids=["IGNWPS-MH-WIDOW-01"],
)
```

This is an example of the typed summary. Graph state stores its JSON form.
The full result goes into `eligibility_results["IGNWPS-MH"]`, preserving
the reason and evidence. The old `eligibility_result` also gets that result.

When storing an entry, the node keeps any other entries:

```python
"eligibility_results": {
    **state.get("eligibility_results", {}),
    result.scheme_id: result.model_dump(mode="json"),
},
```

Read this as: "copy the saved results, then save this scheme's result".
Checking the same scheme again replaces its entry rather than adding a
duplicate.

### What if a scheme has no rule package?

Intake records an `information_only` summary. It does not call the
eligibility tool or create a full eligibility result. Missing rules do not
mean "not eligible".

### What if the user starts a new request?

`run_journey` clears all three new fields, the old result, and old passages.
Otherwise an earlier verdict could appear under a new search.

Refreshing the current conversation is different: `get_journey` reads the
saved fields without clearing them. Older checkpoints lacking these new
fields load with empty defaults.

### Checks for this step

In `tests/test_journey_graph.py`:

- A normal one-scheme check fills both the old result and new indexed result.
- A search returning widow, farmer, widow yields two candidate IDs and
  preserves all three passages.
- A new search in the same conversation clears the earlier verdict.
- Loading that saved conversation preserves its candidate IDs.
- An information-only scheme never gets an invented rule-engine result.

Run from the repository folder:

```powershell
..\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_journey_graph.py tests\test_api_eligibility.py tests\test_ui_app.py
```

## Step 2: ask shared questions once

### Example: two schemes, one person

The API can now start an interview with both scheme IDs:

```json
{
  "action": "interview",
  "candidate_scheme_ids": ["IGNWPS-MH", "PM-KISAN-IN"]
}
```

The list is deduplicated and limited to 20 IDs. This is a technical safety
limit; requests with more than 20 candidates are rejected rather than
silently truncated. Journey search asks for up to 20 passages, groups them
by scheme, and displays a notice that search may miss relevant schemes. This
is not a promise that search found every suitable scheme.

The new function `pick_shared_fact` in
`src/workflow/question_picker.py` counts how many **undecided** schemes need
each missing fact. It picks the most commonly needed fact. For a tie, it
keeps the existing package and rule order.

It counts a fact once per scheme, even if that scheme has two rules using
the same fact. It only shares identical profile fields: personal income and
family income must remain separate fields if their meanings differ.

### What the graph does

1. Intake uses the shared profile and all candidate rule packages to pick
   the next question.
2. The answer is saved once in that profile.
3. The picker checks the profile against every candidate again. A scheme
   whose verdict is already decided no longer contributes questions.
4. Once there are no useful questions left, the supervisor checks each
   candidate in turn using the existing MCP rule engine.
5. Each result is saved under its scheme ID. Schemes without a rule package
   get `information_only`; they never get a fake verdict.
6. The API returns `completed`, a verdict map, and full evidence-bearing
   results for schemes with packages. The old single-result field is empty
   for multi-scheme requests to avoid implying one scheme is the answer.

Example response shape (shortened):

```json
{
  "status": "completed",
  "candidate_verdicts": {
    "IGNWPS-MH": {"result": "eligible"},
    "PM-KISAN-IN": {"result": "not_eligible"},
    "UNREVIEWED": {"result": "information_only"}
  },
  "eligibility_results": {
    "IGNWPS-MH": {"result": "eligible", "evidence": ["..."]},
    "PM-KISAN-IN": {"result": "not_eligible", "evidence": ["..."]}
  }
}
```

The above is a shape example, not a promise that every candidate will have
a final eligible/not-eligible answer. If the user does not know facts, the
result can remain `need_more_information`.

### How to start this flow

After a search, choose **Check all found schemes**. The app starts the shared
interview, asks one combined question at a time, and then shows a result box
for each scheme. The URL stores only the candidate IDs and random
conversation ID, not answers.

The existing **Continue to the synthetic eligibility demo** button is still
there for the single-scheme flow.

The search passages are grouped by scheme ID, so two passages from the same
scheme produce only one interview candidate. The selected passages and their
citations remain visible in search results.

### Direct API example

```python
from src.workflow.journey import JourneyRequest, run_journey

result = await run_journey(
    graph,
    JourneyRequest(
        action="interview",
        candidate_scheme_ids=["IGNWPS-MH", "PM-KISAN-IN"],
    ),
)
print(result.status, result.question, result.pending_fact)
```

The usual message endpoint resumes the same conversation. Clear yes/no/date
answers still use the plain-code parser. Unsupported free text can use the
bounded reader described below.

### Checks for shared interviewing

- Shared picker tests verify cross-scheme counts, ties and per-scheme
  deduplication.
- Journey tests verify three candidate IDs with one duplicate, shared
  questions, separate scheme verdicts, an information-only scheme, skipped
  unknown answers and checkpoint restore.
- API tests verify the response keeps a separate result for each candidate.
- UI test verifies the search results start one shared chat and preserve its
  candidate IDs in the refresh URL.

## Step 3: show why the plan moved on

### The simple idea

After each candidate is checked, save a short note:

> Plan 1 → Plan 2: PM-KISAN was ruled out by the mock rules
> (PMKISAN-INCOME-TAX-01). Its result is saved; continuing with the next
> candidate.

The next candidate still gets checked. The history does not remove the
ruled-out result; it explains why the supervisor moved on.

### How the code saves it

`PlanChange` in `src/workflow/state.py` is one typed history item. It saves:

- old and new plan version;
- which scheme was just checked;
- the rule-engine result and deciding rule IDs;
- a reason written by ordinary Python code.

After an eligibility step, `supervisor` reads the result already saved for
that scheme, creates a reason that matches that result, and increments the
plan version by one. `PlanChange` rejects version jumps or versions that go
backwards. No LLM is used to write this note.

The graph stores history as a list in the checkpoint. Each new event is
appended, so refresh does not erase the earlier notes. `JourneyResponse`
returns the list to the screen.

### What the person sees

The shared-interview screen shows **Why the plan changed**, then the notes
in order. The latest note is also shown in the plan box. Each scheme's
result remains in its own result panel below.

An eligible result, a not-eligible result, missing information and an
information-only scheme each get a different honest explanation. For
example, information-only says no reviewed rule package was available; it
does not say the person failed eligibility.

### Recording tool failures and corrections

`JourneyHistoryEvent` in `src/workflow/state.py` records retries, final tool
failures, and answer corrections. Search and eligibility calls retry once
after an MCP tool error. If both attempts fail, the screen says the result is
unknown because the tool failed; it never creates an eligibility verdict
from an error. For a failed candidate, the supervisor continues to the next
candidate.

The correction endpoint accepts a known fact name and a replacement answer.
It validates the answer and reruns the candidate checks. The history event
stores the fact name, not either answer value. The API returns known fact
names so the screen can offer corrections without including saved answers
in that list.

The UI shows the recorded history and provides the correction control. A
correction can change earlier results, so those results are recomputed
instead of being treated as current.

### Checks for plan history

- The graph test checks one version change per checked candidate, including
  an information-only scheme, and verifies the history survives refresh.
- The UI test checks that the code-written reason appears after the reply.
- A rule ID in a not-eligible note comes from the actual rule-engine result.
- Graph tests check retries, exhausted eligibility/search failures, and
  correction rechecks.
- API and UI tests check correction validation and showing history.

The full suite currently has **177 passing tests**:

```powershell
..\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## Step 4: read free-text answers safely

The code first tries the existing yes/no/date parser. Only when it cannot
read an answer does the intake reader call the configured chat model. The
reader receives the current fact, its question, and the reply as JSON; it is
instructed to ignore instructions inside the reply and return one structured
value, `unknown`, or `uncertain`.

The journey then checks that the proposed type matches the fact and that the
whole profile remains valid. A confident value is shown back to the person
for an explicit yes/no confirmation before it is saved. A clear unknown skips
that question without creating a fact. Uncertain output, invalid output,
model errors, or a declined interpretation return to the plain-code
question. Each fact gets at most one LLM attempt in a conversation, which
bounds retries and call count.

The UI lets people know they can answer in their own words. Tests use a fake
reader for success, uncertainty, bad types, confirmation, decline, unknown,
and reader failure. A live OpenRouter smoke test with synthetic facts also
completed a two-scheme interview: the person confirmed the interpretation,
then each scheme received its own deterministic rule result.

## Retrieval evaluation and current limits

The available development set has 43 queries, including three that require
passages from both schemes. The corpus contains 13 reviewed passages from
only two schemes. A local BM25-only diagnostic (no embedding or reranker API
calls) measured recall@5 of **0.7558** and scheme-hit rate@5 of **0.7907**.
Recall@5 was 0.9545 for English, 0.2 for Hindi, and 0 for Marathi. This
baseline exposes a multilingual retrieval weakness; it does not measure the
configured hybrid/vector search and is not evidence of performance on a
larger catalogue. The free embedding key was not configured, so that paid
external retrieval path was not called.

The test suite covers multiple candidate IDs, duplicate passages,
information-only schemes and the 20-candidate request bound. More extensive
catalogue evaluation requires a larger reviewed corpus and matching
domain-validated query labels; those cannot be safely fabricated from the
two-scheme pilot.
