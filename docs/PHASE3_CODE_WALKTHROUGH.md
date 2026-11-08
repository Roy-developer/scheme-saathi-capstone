# Phase 3 code walkthrough: one conversation, several schemes, safe re-checks

This guide follows the **current** Phase 3 code. It starts with a search
result, then follows one family through bounded re-searching, a shared
interview, a rule-engine check for each scheme, a corrected answer, the
stale-draft screen and the saved budget. Since the data-driven registry work,
the interview can also be driven by **versioned data files** instead of
fixed Python fields (new section 4B). Read it beside the code. Symbols were
checked against the working tree on 2026-11-04; `journey.py` has moved a lot,
so references to it use function names only. Search for the name.

Start with [Phase 1](PHASE1_CODE_WALKTHROUGH.md) for profiles, the fact
registry, rule packages and the deterministic engine, then
[Phase 2](PHASE2_CODE_WALKTHROUGH.md) for the supervisor, typed questions and
checkpoint. Plan:
[Phase-wise implementation plan](PHASE_WISE_IMPLEMENTATION_PLAN.md), section
**Phase 3 — Multi-scheme and replan**.

> **Scope and safety.** This is a synthetic pilot, not a government
> eligibility or approval service. `eligible` means the supplied facts meet
> the current *mock* rule package; it does not verify documents or authorise
> a benefit. Search finds candidates, never eligibility. A model may propose
> a fact or choose among typed actions; **only the deterministic rule engine
> produces a verdict**, and a person approves each exact draft. Every example
> below is synthetic.

> **Verification status (separate records; read each for what it covers).**
> 1. *Earlier fixed-field Phase 3 (historical).* An independent review of the
>    original fixed-profile work and a 301-test full run (170.91 s) are in
>    [CONTRIBUTIONS](CONTRIBUTIONS.md). They predate the registry revision.
> 2. *Registry revision, builder record.* The "Revised Phase 3
>    implementation" row reports shared registry intake, typed corrections,
>    explicit legacy bridges and the persistent review latch. It reports the
>    run reached 350 passed / 1 failed on an unmocked UI request, which was
>    then mocked; a single final green run was **not** claimed there.
> 3. *Registry revision, review follow-up.* A separate independent review
>    reported three medium bugs (a novel bundle with a legacy mapping took the
>    fixed path; an invalid combined date consumed the only interview pause;
>    registry intake skipped discovery). The follow-up row reports all three
>    fixed with independent reproductions closed, **37 registry tests
>    passing**, a **130-test** targeted selection, a single serial full run of
>    **401 passed in 219.49 s**, passing `compileall` and `git diff --check`,
>    and unchanged pilot rule-package hashes. Streamlit/Pydantic serialisation
>    warnings (740 observed) were seen; they are not hidden, and are not a
>    failure.
>
> All of this is automated and offline. **Still open:** independent review of
> *this* guide; a manual browser session; native-speaker Hindi/Marathi review;
> native Python 3.12 CI; source and privacy approval of the registry
> metadata (still pending, not approved); a live-model run; and a real
> process-kill or multi-worker test. Phase 3 made no paid call and no model
> extracts registry facts.

---

## 1. What changed since the previous version of this guide

The earlier text said new facts never discover schemes and that model-attempt
limits reset on correction. Both statements are now wrong.

| Earlier claim | Current behaviour |
|---|---|
| New facts do not search for more schemes | A *confirmed* widow/landholding fact or a changed age triggers a bounded re-search (section 6) |
| The "LLM attempt" list resets on correction or restart | Search attempts, model calls and per-fact interpretation attempts are saved **before** they are used and survive correction and restart (section 12) |
| Corrections recheck schemes only | A correction also makes every unsubmitted draft stale and un-approved, forever (section 11) |
| The model only reads free text | A model may also pick *typed actions* in the eligibility step; it still cannot write a verdict (section 9) |
| The UI shows results | The UI also shows coverage notices, overflow IDs, budget counters and stale-draft warnings (section 13) |
| Questions come from fixed Python fields (`HouseholdProfile`) | Questions for non-pilot bundles come from a versioned **fact registry** whose review metadata is pending; the two pilots keep their fixed fields through an explicit bridge (section 4B) |
| Stale only after a person correction, rule or document change | Also after any change to a fact definition, bundle or rule content: a persistent **review latch** (section 4B.6) |

## 2. Plain words first

- **Candidate:** a scheme worth checking. Not a yes.
- **Confirmed fact:** a profile answer the person gave or confirmed. A model's
  guess is only a *proposal* until the person says yes.
- **Hint:** a short search phrase built from confirmed facts, such as
  "widow pension". It helps retrieval; it is never a rule.
- **Rediscovery:** running one more search because confirmed facts changed.
- **Information only:** the scheme has no loaded rule package, so the engine
  has nothing to run. The person gets information, not a decision.
- **Observation:** a small, safe summary of a rule-engine result (scheme ID,
  result word, missing-fact names, deciding rule IDs). No applicant values.
- **Specialist loop:** a model picks one of a few typed buttons; code checks
  each button press before running anything.
- **Reservation:** writing "this call is used" to disk *before* making the
  call, so a crash cannot give the call back.
- **Stale draft:** a saved application draft whose answers, rules or
  documents have since changed. It can never be approved or submitted again.
- **Monotonic:** only goes up. Version numbers never roll back, and a stale
  mark is never cleared.
- **Fact registry:** a versioned data file (`src\rules\fact_registry.json`)
  whose fact and question review metadata is currently pending. It defines
  each fact once: its ID, meaning, who it is about (person or family), type,
  unit, time period, limits and questions in three languages.
- **Bundle:** a manifest (`src\rules\bundle_registry.json`) that pins one
  scheme's rule package and the registry by version and SHA-256 hash.
- **Legacy bridge:** an explicit list in a bundle saying "registry fact X is
  the old profile field Y". Only listed facts cross over.
- **Review latch:** a saved flag that, once set, refuses old answers and
  results until a person starts a new, reconfirmed conversation.

## 3. The whole path

```text
Streamlit screen                  src\ui\app.py  (api_client.py is the only HTTP caller)
  -> FastAPI route                src\api\app.py   (loads registry + bundles once, in lifespan)
  -> journey graph                src\workflow\journey.py
       supervisor -> intake -> (ask_user pause) -> intake
                      |  which questions?  (section 4B)
                      |    registered bundle  -> registered_intake_result  (typed facts, registry questions)
                      |    legacy pilot only  -> fixed HouseholdProfile questions
                      |  confirmed facts changed? -> bounded search (discovery.py, shared by both)
                      v
       supervisor -> eligibility(candidate A) -> supervisor -> ... -> END
                          |
                          +-> optional typed-action loop (eligibility_agent.py; legacy path only)
                          +-> MCP rule-engine tool -> deterministic engine (typed fact store)
  portal approvals          src\portal\repository.py (separate SQLite database)
  saved budget              src\workflow\conversation_budget.py (LangGraph Store, namespace ("budget",))
  review latch              _check_registry_dependencies (journey.py) -> portal stale marks
```

Checks run one candidate after another, not in parallel. Budget reservations
and the approval/stale marks live outside the question path, so both question
paths use the same ones.

### Read order

| Read | File | Why |
|---|---|---|
| 1 | `src\rules\models.py`, `src\api\eligibility.py` | Profile (`None` means unknown) and verdict words |
| 1b | `src\rules\facts.py`, `bundles.py`, `data_provider.py` | Fact definitions, typed store, bundle pins, load-time checks |
| 2 | `src\workflow\state.py` | Plan, handoff, `CandidateVerdict`, history events |
| 3 | `src\workflow\discovery.py` | Hints, limits, de-duplication, status messages in three languages |
| 4 | `src\workflow\question_picker.py` | Which missing fact helps most schemes (`pick_shared_fact`, `pick_shared_registered_fact`) |
| 4b | `src\workflow\questions.py` | `registry_question_for`, `registered_question_details`, `parse_registered_answer` |
| 5 | `src\workflow\agent_config.py`, `agent_runtime.py`, `agent_middleware.py` | Limits, and `run_agent` (LangChain `create_agent` + Saathi's budget and trace middleware) |
| 6 | `src\workflow\eligibility_agent.py` | The eligibility specialist (`run_eligibility_specialist`, line 58) |
| 7 | `src\workflow\conversation_budget.py` | Saved reservations |
| 8 | `src\workflow\journey.py` | Nodes, correction, serialisation, portal approval storage |
| 9 | `src\mcp_servers\service_routing.py` | Which caller may use which tool |
| 10 | `src\portal\repository.py` | Approval, stale marks, receipts |
| 11 | `src\api\app.py`, `src\ui\app.py` | Routes, notices and stale-draft screen |

---

## 4. One synthetic family to follow

**Meera** (synthetic) was born 1 January 1986; the application date is fixed
at 1 January 2026, so her age is 40. Her household facts are supplied as
confirmed answers: she is a widow, can show a BPL card, and the family is
*not* on state landholding records; every exclusion question is "no". This
mirrors the `PROFILE` used by `tests\test_phase3_agents.py` (line 31).

The conversation starts with one candidate from an earlier search:
`IGNWPS-MH` (widow pension). Two other IDs appear later:
`INFORMATION-ONLY` (a made-up scheme with no rule package) and `PM-KISAN-IN`
(farmer support).

| Step | What happens | Result |
|---|---|---|
| 1 | Confirmed widow fact + age 40 give hint "widow pension age 40"; one search runs | Search returns `IGNWPS-MH` twice and `INFORMATION-ONLY` |
| 2 | De-duplicate and merge | Candidates: `IGNWPS-MH`, `INFORMATION-ONLY` |
| 3 | Nothing left to ask; check each candidate | `IGNWPS-MH` eligible; `INFORMATION-ONLY` information only |
| 4 | Meera corrects "family on landholding records" to **yes** | Hint now also says "farmer family landholding"; second search finds `PM-KISAN-IN` |
| 5 | Re-check everything | `PM-KISAN-IN` eligible; two full results, three summaries |
| 6 | Any approved draft from before step 4 | Stale and un-approved |

Steps 1–5 are the scenario of `test_confirmed_correction_discovers_deduplicated_new_and_information_only_candidates`
(tests\test_phase3_agents.py, line 196). The age-40 hint comes from
`test_discovery_uses_supported_inputs_without_inferred_state_or_gender`
(line 174).

---

## 4B. Data-driven questions: the fact registry and bundles

Until now, every question came from a fixed Python model. Now a scheme can
bring its own facts as **data**, and the same journey, API and screen handle
it without a new code branch per fact. This section is the reconciliation
between the two worlds. Everything here describes code that exists; it is not
a promise of future form generation.

### 4B.1 What is data and what is still code

| Data (versioned files; review still pending) | Code (tested, unchanged by scheme) |
|---|---|
| Fact meaning, scope (person/family), type, unit, period, limits | The parser that reads an answer by type |
| Questions and choice labels in English, Hindi, Marathi | The rule engine and operators |
| Which facts and rule package a scheme bundle uses, with hashes | The supervisor, budgets, approval and stale marks |
| Rules (`<scheme>.vN.json`) | Typed store validation (`TypedFactStore.validate_against`) |

The golden rule is unchanged: a model never decides eligibility. At load
time `RulePackageProvider` checks each rule against its fact (operator, type,
unit, choices) and each bundle against its package and registry hash
(`_validate_rule`, `_validate_bundle` in `data_provider.py`). A mismatch stops
start-up.

### 4B.2 Which path a scheme takes

`uses_registered_questions(scheme_id)` (inside the graph builder in
`journey.py`) answers: does this scheme have a loaded bundle whose
`activation_state` is **not** `legacy_compatibility`? Only the two compatibility
pilots (`IGNWPS-MH`, `PM-KISAN-IN`) are `legacy_compatibility`, and the loader
accepts that label only when every pin (file, version, hash, fact IDs,
mapping, source clauses) matches a built-in table
(`_LEGACY_PILOT_BINDINGS`). A new bundle cannot claim it
(`test_novel_pending_bundle_cannot_masquerade_as_legacy_compatibility`).

Earlier code asked a different question: "does this bundle have a legacy
mapping?" That was a bug: a novel bundle with a mapping fell back to the
fixed path and never asked its novel fact. The independent review found it;
now the choice depends on activation state, never on the mapping
(`test_development_bundle_with_legacy_bridge_still_asks_and_corrects_novel_fact`).

In a **mixed** conversation (one pilot plus one registered bundle) the whole
candidate list uses the registered path, because `any(...)` of the candidates
is registered. The pilot still works: its answers cross the explicit bridge
(4B.4). Development-only bundles load only when a test explicitly asks for it
(`allow_development`); a production start-up refuses them.

### 4B.3 Sharing one question: when two schemes may share a fact

`pick_shared_registered_fact` (`question_picker.py`) runs the engine for each
candidate, keeps those still `need_more_information`, counts each missing
fact **ID** once per scheme, and returns the ID needed by most. Ties follow
candidate, rule and derived-input order. Declined ("I don't know") facts are
skipped so the chat cannot loop.

Sharing is by **identical ID in one pinned registry**, never by similar
labels. An ID fixes meaning, scope, unit and period together. So two schemes
that both need `exam_marks` (a person, percent) ask once. A scheme needing a
*family current-period* income and one needing a *personal prior-period*
income use different IDs and ask separately even if the English labels match
(proved with the synthetic bundles in
`test_data_only_multischeme_discovery_sharing_and_typed_correction_through_http`,
`tests\test_fact_registry.py:1044`). Different compatibility means different
ID; there is no fuzzy matching.

### 4B.4 Explicit legacy bridges

A pilot's old fields (for example `is_widow`) map to registry IDs through
`legacy_profile_mapping` in its bundle. In `registered_intake_result` the
bridge works in both directions, and only for listed facts:

- Incoming legacy profile fields are copied into the typed store if the
  fact is not there yet. If a typed value already exists and differs, the
  code raises "Use a correction to replace a saved answer". A field with no
  mapping is rejected ("Legacy fields require explicit bundle mappings").
- A legacy field the person skipped becomes a *declined* typed fact.
- Known typed facts that have mappings are copied back into a
  `HouseholdProfile`. This bridged profile feeds discovery hints and the
  pilot rules. Novel facts stay only in the typed store.

Cross-field checks (such as a date of birth that makes an impossible age)
also run on the mapped fields (`validate_registered_store`).

### 4B.5 One answer, parsed before the graph moves

`resume_journey` parses a registered reply **before** touching the graph,
using `parse_registered_answer` (`questions.py`): yes/no, integers, exact
decimals, dates, choice codes or labels, short text, or an unknown phrase. It
then builds the whole proposed store and checks every constraint
(`_replace_registered_fact` + `validate_registered_store`). Only a validated
value goes into the checkpoint, as a typed payload; decimals are written as
`{"$decimal": "text"}` and restored with `Decimal`, so precision from Phase 2
survives restarts (`test_decimal_answer_keeps_precision_through_journey_interrupt_and_checkpoint`).
The raw reply is only stored in a masked form (`mask_sensitive_text`).

**Fix from the review.** A combined date check used to run after the pause was
consumed, so one impossible birth date left the person with no question to
answer. Now a failing check (a "complete validation") turns the reply into an
`invalid` answer, which re-asks the same question with a localised hint and
no saved change. It is retryable (`test_combined_date_answer_reasks_safely_and_invalid_correction_never_writes`,
`tests\test_fact_registry.py:1476`).

### 4B.6 Pinning, and the review latch

Three pins stop an old answer from quietly meaning something new:

1. **Definition pin.** Every stored fact records its `definition_version`.
   `TypedFactStore.from_wire(...)` and `validate_against` fail if the loaded
   definition differs, instead of reading the old value in new terms.
2. **Scope/bundle pin.** `registry_dependencies()` hashes the *content* of the
   registry, every bundle and every rule package (not just version numbers).
   Review status, scope, unit, period, rule text and bundle content are all
   in the hash.
3. **Portal pin.** `bind_rules` sends the hash of the package and the registry
   dependency to the portal, so an unsubmitted draft depends on it too.

`_check_registry_dependencies` runs at the start of every journey entry
(`resume_journey`, `correct_journey_answer`, `run_application_task`, new
requests). If the saved hash differs, or typed facts exist from before pins
were stored, it **sets the latch**: it persists `dependency_review_required`
*first*, then revokes unsubmitted approvals, clears visible results and
returns a safe message in the person's language ("human review and
reconfirmation in a new conversation are required"). Saved *answers* are kept,
but never silently reused. Changing the files back (A to B to A) does **not**
clear the latch
(`test_dependency_changes_require_review_without_erasing_answers_or_restoring_a_to_b_to_a`,
line 1168). The review itself is a human step; the code only refuses.

### 4B.7 Correction in the registry world

`correct_journey_answer` accepts a typed fact that is already known or
declined. It parses with `parse_registered_answer`, builds a proposed store,
checks the whole store, and **only then** calls `_begin_profile_change`. So an
invalid correction (for example a date that makes the age impossible) returns
422 and changes nothing: facts, dependency version and budget counters stay as
they were (`test_combined_date_answer_reasks_safely_and_invalid_correction_never_writes`).
After a valid correction the typed store is the truth and intake rebuilds the
bridge. A correction **always** revokes unsubmitted approvals, even when the
verdict is still `eligible` and even for A to B to A, because the approval was
for the exact form built from the old answers (section 11). The real-portal
case is `test_typed_corrections_and_changed_definitions_revoke_real_pilot_approval_after_restart`
(line 1268).

### 4B.8 Discovery is shared, and filters are not invented

`discover_candidates` is one function used by the legacy interview *and*
`registered_intake_result`. It keeps its signatures, the counters, the
four-attempt limit (`MAX_DISCOVERY_CALLS`) and durable restart behaviour. The
review's third bug was that the registry path returned early and never
searched. Now, in registry mode:

- Hints come only from the bridged profile, so only the supported hint
  facts (widow, landholding, age) can cause a search.
- A registry fact with no supported hint does not search at all.
- A new rule-package scheme is "found" only if retrieval returns its ID. A
  package existing in the loader does not prove a person will find or
  qualify for it.
- A candidate with no loaded package stays information only.

`test_registry_and_legacy_intake_share_bounded_confirmed_fact_discovery`
(`tests\test_fact_registry.py:1564`) checks this for the legacy, initial
registry and newly discovered registry cases: supported hints only, no
invented filters, an unrelated correction does not search again, a restart
keeps the count, and search exhaustion is durable.

### 4B.9 What a model can and cannot see

The registry path does not call a model. Registry intake skips free-text
interpretation, and `eligibility_agent` sets the specialist model to `None`
when the scheme is registered (a code comment says registry review metadata
is not permission to disclose applicant-derived verdicts or missing-fact
names to a model). The test
`test_registry_questions_drive_typed_journey_and_resume`
(line 738) uses a spy planner model and checks that a synthetic answer typed
in the conversation never appears in what the model was shown. That is one
tested instance of the rule, not a proof for every path. The privacy metadata
in the registry is still **pending**, not approved. Legacy-only conversations
keep the Phase 2/3 bounded models described in sections 8 and 9.

### 4B.10 Screen and API

The API returns a `question_definition` (type, unit, bounds, choices with
localised labels, help text) built by `registered_question_details`. The UI
picks a widget from it in `src\ui\app.py` (the registered answer renderer):
radio for yes/no, number input for integers, exact **text** for decimals (no
float), date, choice and text widgets, and an "I don't know" control. Strings
and labels exist in English, Hindi and Marathi. Generic corrections show
registry labels (from `fact_questions`). `api_client.py` is still the only
caller; no raw server error is shown
(`test_registry_question_metadata_flows_through_journey_http_api`, line 905).

### 4B.11 A synthetic mixed example

The tests create a made-up scholarship bundle (`exam_marks`, a percent
score of a person, and a `course_type` choice) through data files only, with
no new Python branch. Search results are **injected** by the test (labelled
"injected-..." passages), because real corpus retrieval for this fake
scheme does not exist. The flow: injected search finds the scheme; the
person is asked `exam_marks` once, even though a pilot is also a candidate;
verdicts come from the MCP evaluator core; a decimal correction and a
restart still work. This proves the plumbing, **not** that a real new scheme
can be added in a day. The synthetic bundles are development-only and need
explicit test injection.

### 4B.12 What is not built

- The generic Phase 4 form/document flow for a registry-only scheme. The
  journey asks questions and gets a verdict; it does not build a generic
  form.
- A browser check that a data-only scheme works end to end in the UI (the
  receipt proof for a data-only scheme belongs to Phase 4).
- Approved registry review metadata. Fact, question and privacy review
  status in the files is `pending`.
- Production activation of any new bundle. Loading is refused.

The honest summary: Phase 3 needs **no new code branch per new fact** for
intake, sharing, correction, discovery and invalidation. The *entire* data-only
path through the UI, with a receipt, is still unproven and belongs to Phase 4.

---

## 5. Search gives candidates, not decisions

Two places turn passages into candidate IDs.

1. **A plain search request** (`scheme_search_tool`, `journey.py`) retries
   once, groups passages by scheme ID in retrieval order, and caps the list at
   20 (`merge_candidates`, discovery.py:138). Extra IDs are not dropped
   quietly: they go to `unprocessed_candidate_ids` with a `candidate_limit`
   notice.
2. **Rediscovery inside an interview** (section 6) merges new IDs into the
   candidate list that already exists.

`JourneyRequest` (`journey.py`) accepts at most 20 candidate IDs and rejects
blank ones. A scheme ID with no loaded rule package is not an error: the
eligibility step marks it `information_only` without calling the engine
(`eligibility_agent` in `journey.py`).

## 6. Confirmed hints trigger bounded rediscovery

Only three kinds of fact shape a search, and only in code you can read:

- `is_widow` being **true** adds "widow pension".
- `landholding_family_in_state_records` being **true** adds "farmer family
  landholding" (`RELEVANT_FACT_TERMS`, discovery.py:14).
- A known age appends "age N" when at least one of the above is present.

A fact that is false or unknown adds nothing (`discovery_query`,
discovery.py:120). The search gets only a query string, the **selected UI
language** and a limit of 20 (`discovery_input`, discovery.py:107). The
profile has no state or gender, and retrieval has no age filter, so none is
invented from widow status. The reference test checks that an empty profile
gives an empty query.

### When does it fire?

Inside the interview step (`discover_candidates`, `journey.py`, called by both
the legacy interview and `registered_intake_result`):

1. Build a **signature** of the three inputs (`discovery_signature`,
   discovery.py:129). It includes false/unknown states, so a correction *to*
   no or *to* unknown also changes it, but it carries no personal values
   beyond these hint facts and age.
2. Search only if the signature differs from the saved one **and** the query
   is not empty.
3. Search happens *before* the next question is picked, so a newly found
   scheme can influence that question.

A model reading a free-text description may propose the two discovery facts,
but nothing is searched until the person confirms them
(`test_new_discovery_fact_from_description_is_not_searched_until_confirmed`,
line 378).

Meera's age is derived from her date of birth, so a conversation that learns
"widow" first and the date of birth later searches **twice**: once for
"widow pension", then for "widow pension age 40". This is deliberate: each
change is a new signature. The hard limit below stops it from running away.

### The trace after a search

Every search produces one `DiscoveryEvent` (discovery.py:29): a code, the
number of search calls used, the IDs that were **added**, and IDs left
**unprocessed**. Codes: `candidates_added`, `search_completed`, `tool_retry`,
`tool_error`, `budget_exhausted`, `candidate_limit`, `correction_invalidated`.
Events carry IDs and counts only, never answers.

When new IDs appear, the plan is rebuilt with a version one higher and the
reason "Confirmed facts added retrieved candidates." (`discover_candidates`).
A later fix covers one more entry path: a profile that arrives already
confirmed, together with a free-text description that proposes no new facts,
used to skip this step. Now the first look at that profile has no saved
signature, so it searches once, and the regression test checks the exact
query "widow pension age 40" and an information-only result with no verdict
(`test_complete_confirmed_profile_still_discovers_when_description_adds_no_facts`,
test_phase3_agents.py:335).

## 7. De-duplicate, add, information only, limit

Using the family above and the test-based cases:

- **De-duplicate.** Two passages of `IGNWPS-MH` become one ID; both passages
  stay as evidence. `merge_candidates` keeps first-seen order.
- **Additions.** In step 4, only `PM-KISAN-IN` is "added"; the event's
  `candidate_ids` is exactly that.
- **Information only.** `INFORMATION-ONLY` is a candidate with a summary of
  `information_only` but **no** entry in the full-result map. The test checks
  `eligibility_results` has just the two rule-backed schemes.
- **Limit.** At most 20 candidates are checked. When 25 are retrieved, the
  extra five are listed as unprocessed and warned about. A later relevant
  correction keeps earlier overflow IDs and adds new ones; none of them ever
  gets a verdict
  (`test_rediscovery_overflow_remains_explicit_across_later_relevant_corrections`,
  line 305).
- **No new facts, no new search.** An unrelated correction (same hint
  signature) leaves the search count at two (same test as step 4).
- **Failure.** If the search fails twice, the existing candidate is still
  checked and still gets its rule-engine verdict; the person sees a referral
  message ("ask a CSC operator"), and no scheme is invented
  (`test_discovery_failure_keeps_existing_candidate_and_refers_without_fake_verdict`,
  line 283).

### The hard search limit

`MAX_DISCOVERY_CALLS` is 4 per conversation (discovery.py:8) and counts every
attempt, including retries. The fifth request answers `tool_error` with a
`budget_exhausted` notice without calling search
(`test_discovery_limits_are_explicit_and_search_budget_survives_same_id_restart`,
line 255). Section 12 explains why a crash cannot reset this.

---

## 8. Shared facts: one question for many schemes

`pick_shared_fact` (question_picker.py) is the fixed-profile picker; registered
conversations use `pick_shared_registered_fact` instead (section 4B.3). Both
ask the rule engine which
candidates are still undecided, count each missing fact once per scheme, and
return the fact helping the most schemes; ties keep candidate and rule
order. A fact the person answered "I don't know" is skipped, so the chat
cannot loop. A scheme already decided (eligible or not eligible) no longer
asks questions.

The model's role in the **legacy** intake is unchanged from Phase 2 and stays
small. If the
plain parser cannot read a reply, a model may propose a value; the person
must confirm it before it is saved. Each fact gets **one** such model attempt
for the whole conversation: it is recorded before the call and survives a
restart (`test_interpretation_attempt_reserved_before_crash_is_not_repeated`,
line 430). Replies are masked for identifiers before any model sees them
(`mask_sensitive_text`, agent_runtime.py:223). The Phase 2 safeguards carry
over to registered facts unchanged: decimals stay exact (`Decimal`, never
float), and replies are masked before being stored. Registered conversations
make no model attempt at all.

## 9. The eligibility specialist: a model chooses, code and the engine decide

`eligibility_agent` (`journey.py`) does the following for each candidate:

1. Record which rule version the draft depends on (`bind_rules`). A changed
   rule package **or registry dependency** makes drafts for that scheme stale.
2. Skip the engine for schemes with no package (`information_only`).
3. Call `run_eligibility_specialist` (eligibility_agent.py:58) with a wrapped
   rule check that **retries the tool once** and records `tool_retry` /
   `tool_failed` history notes (`checked_verdict`, `journey.py`).

For a **registered** scheme the model is not used: `eligibility_agent` passes
no model provider, so the specialist runs the same wrapped rule check
directly (section 4B.9). The button table below describes the legacy-only
path.

Inside the specialist, with a model configured, the model receives only the
assigned `scheme_id` as applicant-specific context and can press four typed
buttons:

| Button | Allowed when | What it does |
|---|---|---|
| `check_candidate` | the scheme ID is the one assigned, and not yet checked | Runs the rule check once; returns an observation |
| `handoff_verdict` | an observation exists | Ends the loop; the engine's result is returned |
| `request_clarification` | the observation lists missing facts | Ends the loop; the missing facts are returned |
| `refer_for_help` | the check was attempted and failed | Ends the loop with **no** verdict |

The observation holds the scheme ID, a result word, missing-fact names and
deciding rule IDs. The test confirms no date of birth appears in it
(test_phase3_agents.py:60). The run is limited to three model calls
(`max_steps=3`). A wrong scheme ID, a tool name the agent wasn't given, extra
fields such as a `verdict`, an early handoff, or a malformed tool result never
run the rule tool
(`test_eligibility_denied_or_malformed_choices_never_call_rule_tool`, line 100).
An unknown tool or bad arguments are answered with an error and the model may
try again within its three calls; a refused task check ends the run. A model
can never write or edit a result. The full guard list is in
[HOOKS_WALKTHROUGH.md](HOOKS_WALKTHROUGH.md).

Two honest limits:

- If the model **could not be asked** (conversation budget used up, or the
  model request failed), the specialist runs the plain rule check once without
  the model (`recover_authorized_action`, counted against the tool budget) and
  reports `deterministic_fallback`. The verdict still comes only from the rule
  engine.
- If the model **was asked but didn't finish** (it used its three calls, or a
  task check refused its choice), the specialist returns *no* result and the
  journey records `tool_error` for that candidate. No verdict is invented.
- With **no** model configured (including in tests), the specialist skips the
  loop and calls the same rule check directly, labelled `deterministic`.
  This is the default path.

## 10. The deterministic engine decides, and the plan explains

The result goes into three places: a short summary per scheme, a full result
per rule-backed scheme, and a one-line plan note written by code (for
example "ruled out by the mock rules (rule IDs)") in the supervisor
(`journey.py`). A tool that fails twice is recorded as `tool_error` for that
candidate; the others still run, and the final message says some candidates
could not be checked. `completed` therefore does not mean "everyone is
eligible" — read each scheme's own result.

## 11. A corrected answer revokes approval, monotonically

Say Meera had an approved draft for `IGNWPS-MH`, then corrects an answer.
`correct_journey_answer` (`journey.py`) does this in a fixed order:

1. Accept only a fact that was answered or explicitly skipped; parse the new
   value or "don't know". Registered conversations parse with the fact's
   registry definition and check the **whole** proposed store first (section
   4B.7). Bad input is a 422 from the API, and nothing has been written yet.
2. `_begin_profile_change` (`journey.py`) writes a new profile version
   and a "blocked" flag to the graph's saved state **and**, in a `finally`
   block, to the portal. In the portal (`_portal_action_transaction`,
   repository.py:396, run by `_portal_action` under the checklist publication
   lock) one transaction increments the version, sets blocked,
   and marks every **unsubmitted** draft of this conversation stale with its
   approval cleared (`_revoke_unsubmitted_approvals`, repository.py:356).
3. Re-run the interview with the new profile; this may search again (section
   6) and always rechecks all candidates, restoring only matched facts.
4. `reconcile_profile` unblocks writes if the version matches.

While blocked, portal writes fail with "Profile reconciliation is required
before writes", and the journey refuses application tasks the same way
(`run_application_task`, `journey.py`). A stale draft can never be approved, edited, rejected
or submitted again; the portal says "Dependencies changed. Create and
approve a fresh draft" (repository.py:807), and nothing in `src` ever sets
`stale` back to zero.

The key test is `test_approved_draft_correction_always_revokes_saved_approval`
(tests\test_application_tools.py:940). For one-scheme and many-scheme
conversations it checks four cases:

| Case | After the correction | Approval of the old draft |
|---|---|---|
| Same value again ("still eligible"), or a changed date of birth | `eligible` | Revoked; version 1 |
| `is_widow` -> no | `not_eligible` | Revoked |
| "I don't know" | `need_more_information` | Revoked |
| **A-B-A**: restore the original answer | `eligible`, version 2 | Old draft stays stale; only a new draft can be approved |

So a correction never has a "no-op" shortcut, and restoring an answer does not
restore approval. **Why:** an approval belongs to one exact form built from
the answers at that moment. Even if the verdict is still `eligible`, the
person has changed what the form was built from, so they must look at and
approve the new form. And A to B to A returns to the old *answer*, not to the
old *approval*: nothing in `src` sets a stale draft back to current. The same
holds for registered facts, and, through the review latch, for a changed fact
definition or bundle (section 4B.6). This differs from starting a **new request** with an
unchanged profile: `run_journey` revokes only when the profile actually
differs (`profile_changed` in `run_journey`).

Related safeguards: a rule-package change or a document-report change also
marks that scheme's unsubmitted drafts stale, and version counters only move
forward (`test_monotonic_rule_and_document_changes_never_revive_approval_and_keep_receipts`,
tests\test_application_tools.py:1079). If the checkpoint, the portal
transition or the recheck fails, writes stay closed
(`test_correction_persistence_failure_blocks_old_submission`, line 989).
A submit that arrives during the correction waits for it, then fails
(`test_concurrent_submission_cannot_slip_between_invalidation_and_checkpoint`,
line 1037). The wait works through a per-conversation lock
(`_serialize_journey`, `journey.py`), which protects one API process; the
tests do not prove behaviour across several worker processes.

## 12. Budgets survive crashes and restarts

Two kinds of limits exist (agent_config.py:7–17):

| Limit | Value |
|---|---|
| Search attempts per conversation | 4 |
| Candidates checked | 20 |
| Model calls / agent steps / tool actions | 8 / 12 / 24 |
| Tokens (estimated input plus reserved output) | 12 000; at most 512 output tokens per call |
| Steps per model run | 3 |

`ConversationBudget` (conversation_budget.py:24) keeps counters in the
LangGraph `Store` (namespace `("budget",)`, key = conversation ID), separate
from the interview's checkpoint, so it cannot disturb a paused question. In
production the store is an `AsyncSqliteStore` in the same SQLite file. `_serialize_journey` loads it at the start of every request. Before
a search, a model call, or a fact-interpretation attempt, the new counter value
is **saved first** (`reserve_counters`, conversation_budget.py:77). If saving
fails, the external call is not made
(`test_budget_checkpoint_failure_prevents_model_dispatch`, line 683).
Afterwards `durable_counters` takes the larger of the graph value and the
saved value (`durable_counters`, conversation_budget.py:62), so:

- a search that crashed after dispatch still counts
  (`test_failed_node_search_reservation_survives_sqlite_process_restart`,
  line 440; it reopens a SQLite file, so it is a restart simulation, not a
  real process kill);
- a model call reserved before a crash is not refunded
  (`test_model_call_reservation_survives_node_crash_and_sqlite_restart`,
  line 636);
- the same conversation ID cannot buy a fresh allowance by restarting or
  correcting (`run_journey` and `correct_journey_answer` both copy these
  counters forward).

The reserved output is conservative: a call is charged 512 output tokens up
front and adjusted afterwards. With a real model, the shared allowance covers
planning, interpretation and every candidate's check run, so a long list of
candidates can run out of model allowance. The remaining candidates are then
checked by the rule engine without the model, as long as the tool budget (24)
lasts; after that they end as `tool_error` rather than guessed results. This conclusion is derived from the
constants above and the loop code, not from a dedicated test.

## 13. The screen: stale drafts and honest coverage

The UI never runs the graph. `save_journey` (ui\app.py:664) copies the API
reply into session state. If the dependency version changed, or a
`correction_invalidated` notice arrived, it **clears the cached drafts** so
the next load asks the portal again (ui\app.py:672–677). A stale draft shows a
translated warning and no approve or submit buttons (ui\app.py:1406). The notice
renderer (`render_discovery_notices`, ui\app.py:853) shows each notice code,
the added IDs from events, and the unprocessed IDs. Text comes from
`discovery_message` in English, Hindi and Marathi. The budget expander
(`render_agent_observability`, ui\app.py:740) shows counters against the
limits, never prompts.

`test_single_scheme_correction_reloads_stale_draft_and_removes_submit_controls`
(tests\test_ui_app.py:781) checks the stale reload using Streamlit's
`AppTest` with mocked API calls and an English assertion;
`test_discovery_coverage_and_referral_notices_are_localized` (line 902)
checks Hindi coverage notices. Neither is a real browser or a native-speaker
review.

## 14. Errors and receipts

- **Search/rule tool failure:** retried once, then recorded; the person gets a
  short translated notice, not a stack trace. API routes answer 502 "A journey
  tool is unavailable" for tool errors, 409 when a conversation is not
  waiting or has no confirmed answers, and 422 for invalid corrections
  (`journey_correction`, src\api\app.py:682; tool errors go through `_tool_failure`).
- **Draft actions:** before approving or submitting, the API compares the
  draft's saved profile and rule version with the current ones and answers
  409 ("Your answers changed...", "Scheme rules changed...")
  (`update_application_approval`, src\api\app.py:965).
  The portal then checks the exact revision and fingerprint, then approval,
  then submits.
- **Receipts:** submitting an approved, current draft stores one receipt ID;
  submitting the same draft again returns the **same** receipt (portal tests:
  `test_approval_revocation_and_fresh_exact_approval_survive_sqlite_restart`,
  test_phase3_agents.py:561). A submitted draft is history, not stale: later corrections do not
  remove its receipt (`test_monotonic_...` above). Meanwhile, the older
  approved-but-unsubmitted draft cannot be revived, and a fresh draft needs a
  fresh approval of its new fingerprint.
- **Forget:** deleting a conversation removes its graph checkpoints and portal
  data, as before, and its budget record in the LangGraph `Store`.

---

## 15. Tests and what each one establishes

Mainly `tests\test_phase3_agents.py` (16 test functions). Everything runs
offline with fake models, fake search, and the local engine.

| Test (line) | Establishes |
|---|---|
| `test_eligibility_specialist_chooses_handoff_from_observation` (60) | A model chose by observation; the engine's result returned; observation hides birth date |
| `test_eligibility_denied_or_malformed_choices_never_call_rule_tool` (100) | Six bad decisions never reach the rule tool |
| `test_eligibility_exhausted_budget_and_wrong_tool_output_do_not_invent_verdict` (122) | No verdict on budget stop or wrong-shaped tool output |
| `test_eligibility_observation_selects_clarification_or_safe_referral` (242) | Missing facts lead to clarification; tool failure leads to referral without a verdict |
| `test_discovery_uses_supported_inputs_...` (274) | Query/language/limit only; no invented state or gender |
| `test_confirmed_correction_discovers_...` (296) | Dedupe, addition, information only, no search on unrelated change |
| `test_complete_confirmed_profile_still_discovers_when_description_adds_no_facts` (335) | A fully confirmed profile sent with a description that adds no facts still searches once ("widow pension age 40"), adds an information-only candidate, and gives it no verdict |
| `test_discovery_limits_are_explicit_...` (355) | Four searches, 20 candidates, overflow shown |
| `test_discovery_failure_keeps_existing_candidate_...` (383) | Failed search does not erase a verdict |
| `test_rediscovery_overflow_remains_explicit_...` (405) | Overflow persists across corrections |
| `test_failed_node_search_reservation_survives_...` (440) | Search count survives crashes |
| `test_new_discovery_fact_from_description_is_not_searched_until_confirmed` (478) | Proposal is not a confirmed fact |
| `test_interpretation_attempt_reserved_before_crash_is_not_repeated` (531) | One interpretation attempt per fact |
| `test_approval_revocation_and_fresh_exact_approval_survive_sqlite_restart` (561) | Approval revoked; fresh exact approval; same receipt twice |
| `test_model_call_reservation_survives_...` (636), `test_budget_checkpoint_failure_prevents_model_dispatch` (683) | Model reservations and the "save first" rule |

Other files cover the portal transitions (`tests\test_application_tools.py`,
lines 940, 989, 1037, 1079), the correction API
(`tests\test_api_eligibility.py`, line 77, 112, 132), tool permissions
(`tests\test_mcp_permissions.py`), and the UI (`tests\test_ui_app.py`).

### Registry tests (`tests\test_fact_registry.py`)

The review follow-up reports 37 registry tests passing. This guide did not
rerun them; the table lists the ones that matter for Phase 3.

| Test (line) | Establishes |
|---|---|
| `test_novel_pending_bundle_cannot_masquerade_as_legacy_compatibility` (571) | Only the exact pinned pilots can use the legacy label |
| `test_explicit_development_loader_accepts_pending_synthetic_bundle` (592) | Synthetic bundle loads only on explicit request |
| `test_registry_questions_drive_typed_journey_and_resume` (738) | Typed questions, resume, and a spy model not shown an answer |
| `test_unknown_registry_fact_is_not_reasked_and_saved_definitions_fail_closed` (840) | Unknown stays declined; changed definition cannot reinterpret saved facts |
| `test_registry_question_metadata_flows_through_journey_http_api` (905) | API sends widget metadata; validation errors; refresh |
| `test_data_only_multischeme_discovery_sharing_and_typed_correction_through_http` (1044) | Injected search, shared question once, separate scope/period IDs, typed correction (not real retrieval) |
| `test_dependency_changes_require_review_without_erasing_answers_or_restoring_a_to_b_to_a` (1169) | Content/review change latches; answers kept; A to B to A stays refused |
| `test_typed_corrections_and_changed_definitions_revoke_real_pilot_approval_after_restart` (1269) | Real offline portal and reopened SQLite: approval revoked even when still eligible |
| `test_development_bundle_with_legacy_bridge_still_asks_and_corrects_novel_fact` (1422) | Review bug 1 closed |
| `test_combined_date_answer_reasks_safely_and_invalid_correction_never_writes` (1476) | Review bug 2 closed; invalid correction leaves facts, dependency and budget unchanged |
| `test_registry_and_legacy_intake_share_bounded_confirmed_fact_discovery` (1564) | Review bug 3 closed; shared bounded discovery |

Phase 1–2 parser, choice, decimal and provider tests in the same file (lines
236–737) cover the typed foundation this guide relies on.

### Why the test setup is safe (and what it does not prove)

`tests\conftest.py` runs before any application import (lines 12–28). It sets
`SCHEME_SAATHI_DISABLE_DOTENV=1` so `src\config.py` skips `.env` (config.py:69),
sets `SCHEME_SAATHI_DISABLE_CROSS_ENCODER=1`, removes the four known
credential variables from the process environment, and points the checkpoint
and portal databases at unique project-local files that are deleted when the
session ends (lines 21–28 and 100–107). Tests also supply fake model, search and rule
tools (the `fake_openrouter` fixture answers chat requests in process), and `test_phase3_agents.py` uses its own unique `.phase3-*` SQLite files.

This is meant to keep tests free of saved credentials, `.env` values and
demonstration data. It **does not** install a network block, so the suite
alone does not prove that no network call is possible. The independent
verifier's separate pre-app probe reported network access blocked, but that
probe is not part of the repository's test run.

### Commands (repository root, Windows)

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_phase3_agents.py tests\test_fact_registry.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_application_tools.py tests\test_api_eligibility.py tests\test_ui_app.py
.\.venv\Scripts\python.exe -m compileall -q src
```

A full `pytest -q` is the final check for a code change. Use temporary
databases only; never point a test at `data\runtime`.

## 16. What Phase 3 does not claim

- Not every suitable scheme is found: four searches, 20 candidates, no age or
  gender retrieval filter, and retrieval quality is a separate question. The
  earlier BM25-only diagnostics (43 dev queries, two schemes) are not
  evidence for Phase 3 and were not rerun.
- `eligible` is a mock-rule result, not a government decision.
- Correction rechecks all candidates, not a minimal subset.
- No generated search summary, no document-authenticity check, and no real
  submission; Phase 4 specialists are not part of this guide.
- No live paid model, no manual browser test, no native-language review, and
  no multi-process or real process-kill proof for budgets or approvals.
- Registry questions and privacy metadata are **pending**, not approved by a
  human reviewer. No production activation of a new bundle.
- The data-only scheme is proven only through injected synthetic search and
  the MCP evaluator core, not through real corpus retrieval, a browser or a
  receipt. The generic Phase 4 form for a registry-only scheme is not built.
- Search hints still cover only widow, landholding and age. A new fact does
  not widen retrieval; no filter is invented.
- Pydantic/Streamlit serialisation warnings (740 observed in the full run) are
  visible output, not hidden, and are not shown to be harmless beyond "no
  test failed".

## 17. Remaining factual doubts

1. The status text `deterministic_fallback` covers two cases: the rule check
   ran without the model, or (after an unfinished model run) nothing ran
   (section 9). The trace tells them apart; the label does not.
2. Deleting a conversation (`forget_journey`, src\api\app.py:1045) deletes the
   conversation thread **and** the budget record in the Store
   (`test_api_applications.py` checks the Store item is gone).
3. Multi-candidate budget exhaustion with a real model is derived from
   constants (section 12), not exercised by a test.
4. The registry-revision counts (37 / 130 / 401, 740 warnings) come from the
   builder's follow-up record in CONTRIBUTIONS. This guide was written from
   code reading and has no independent review yet; it did not rerun tests.
5. The review latch needs a human to review and start a new conversation.
   There is no automatic migration, and no UI flow for the reviewer.
6. A mixed conversation with a pilot and a novel bundle puts the whole list on
   the registered path, so legacy model help is off for the pilot too. This
   follows from `any(...)` in the code; I did not find a test that names it.
