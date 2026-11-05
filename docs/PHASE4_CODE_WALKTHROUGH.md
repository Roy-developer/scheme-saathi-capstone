# Phase 4 code walkthrough: documents, an exact draft and a human decision

This guide explains the **current local Phase 4 code** in plain English. It
starts after eligibility, follows a synthetic document checklist into a saved
draft, and shows why approving one exact draft must never approve a different
one. Read it next to the source. The goal is to understand both **what each
function does** and **why the flow is split this way**.

Read [Phase 1](PHASE1_CODE_WALKTHROUGH.md) for the deterministic rule engine,
[Phase 2](PHASE2_CODE_WALKTHROUGH.md) for the supervisor and graph pauses, and
[Phase 3](PHASE3_CODE_WALKTHROUGH.md) for shared interviews, per-scheme results
and corrections. The tool list lives in [MCP tool inventory](MCP_TOOL_INVENTORY.md)
and the HTTP contract in [Frontend contract](FRONTEND_CONTRACT.md). The plan is
in the [Phase-wise implementation plan](PHASE_WISE_IMPLEMENTATION_PLAN.md).

> **Status of this document (revised for data-driven Phase 4).** It describes
> the current Phase 4 code in the working tree. Sections 6A to 6D are new: they
> explain how a **bundle** now supplies the allowed facts, how **mock form
> mappings** and **checklist conditions** are plain data, and how the form and
> checklist reach the existing approval, expiry and receipt flow. The older
> sections (approval pause, versions, expiry, restart) are kept and reconciled.
>
> **Evidence the code reports (quoted, not rerun by this guide's author):**
>
> | Step | Result reported |
> |---|---|
> | Original independent review | **145 passed**, but it found that facts from *another* scheme's bundle were accepted because the global registry knew them |
> | Bundle-scope repair | Related offline selection **139 passed**; single full serial run **411 passed**; **9** new independent regression cases |
> | Derived-fact (age) omission repair | Related offline selection **143 passed**; single full serial run **415 passed** |
> | Independent re-check of the checklist selection | **31 passed**, with **4** targeted derived-fact cases passing |
> | Static checks | `compileall -q src` and `git diff --check` passed |
> | Later library simplification (commit `34cafd5`: `filelock` publication lock, shared `check_and_bind_documents`, `src/llm_client.py`) | Full local run **419 passed**, as reported in the commit message |
>
> The author of this guide ran **no tests**; only link, code-fence and diff
> checks apply to this documentation edit. None of these is a native Python
> 3.12/CI result. The full failure history is deliberately left out; the
> project log has it.
>
> **Still open:** a native Python 3.12/CI run, manual browser and language
> checks (Hindi and Marathi wording), independent source/privacy review,
> multi-worker and process-kill testing, and a **full-bundle atomic publish**
> (section 6D explains what exists today). Team ratification of the
> 15-minute approval window also remains open. **Phase 5 is paused.**
> Independent review of this revised guide: **PASS WITH GAPS**. The bounded
> proof gaps and the gates that remain open are recorded in section 17; this
> review does not claim that those gaps are bugs.
>
> **Synthetic demonstration only.** A positive eligibility result means the
> supplied facts satisfy the dated mock rule package. Document checks compare
> **text a person typed** (a name and a date). There are **no uploads, no OCR, no
> authenticity checks and no identity validation**. The two pilot checklists
> (`IGNWPS-MH`, `PM-KISAN-IN`) are still **demo-only** with no linked evidence:
> they are not verified official requirements. The two pilot rule-package
> pins in `src/rules/bundle_registry.json` are unchanged, and the fact
> definitions, questions and privacy text are still **pending human review**.
> No novel scheme is approved or activated for normal use. A mock receipt is
> not a government submission, benefit approval or payment.

---

## 1. The problem Phase 4 solves

An eligibility result answers one question:

> Do these reported facts meet this scheme's current mock rules?

It does not answer:

> Which draft did the person review, and did they approve **that exact** draft?

Imagine a person approves a draft with district "Synthetic district". Someone
then changes the district to "Nashik". A simple `approved = True` flag would be
dangerous if it survived that edit, because it would make an old decision look
like it covers something the person never reviewed.

Phase 4 keeps three ideas separate:

| Question | Who answers it? | What it does **not** prove |
|---|---|---|
| Does the profile meet the mock eligibility rules? | The deterministic rule engine, called through MCP | That the facts are true, or that a benefit is officially approved |
| Do the typed document fields match the profile, and is every applicable checklist group satisfied? | Read-only `check_documents` tool (plain Python, no model) | That a real document exists, is genuine, or meets official requirements |
| Did the caller approve this exact saved draft revision? | A click on the approval route, a paused approval graph, and the portal's own checks | That an authenticated government applicant submitted an official application |

The model never makes any of these decisions. For a backend-selected task, it
may choose only the allowed action or handoff (sections 6.2 and 7.1); code
validates every choice and owns every result.

---

## 2. Plain jargon, defined once

| Word | Meaning here |
|---|---|
| **Specialist** | A small worker with one job and a short list of allowed actions: `documents` or `application` in this phase. |
| **Supervisor** | The graph node that writes the plan and routes each step to one specialist. Specialists never call each other. |
| **MCP server** | A separate program that offers named tools over a pipe (stdio). The API starts four of them. |
| **Tool** | One named operation on an MCP server, such as `check_documents`. |
| **Actor** | The identity the **backend** attaches to a call (for example `human_approval`). The model cannot set it; this is a capability label, not proof of a citizen's identity. |
| **Portal** | A separate, local FastAPI program that stores drafts. It is a mock, not a government site. |
| **Draft** | The saved, reviewable application form (synthetic). Each edit creates a new **revision**. |
| **Revision** | A counter, 1, 2, 3 ... Any edit bumps it. |
| **Fingerprint** | A SHA-256 hash of the draft's canonical JSON. Same content gives the same fingerprint; any change gives a different one. |
| **Approval** | The recorded decision on one exact revision plus fingerprint. |
| **Approval token** | A secret one-use value created at approval time. Only trusted backend code sees it; public API responses strip it. |
| **Receipt** | The mock "submitted" ID. It is not a government receipt. |
| **Stale** | A draft whose inputs (profile, documents or rules) changed after it was made. It can never be approved or submitted again. |
| **Dependency version** | A counter that goes up whenever the profile, the document report, or the rule package changes. |
| **Fact** | One named, typed answer such as `date_of_birth` or `exam_marks`. Its type, bounds, choices and questions are defined in `src/rules/fact_registry.json`. |
| **Typed fact store** | `TypedFactStore` in `src/rules/facts.py`: the confirmed facts as real Python values (dates, exact decimals, integers). `value(fact_id, registry)` is the one place that reads a fact. |
| **Derived fact** | A fact computed by code from other facts. Today the only one is `age`, worked out from `date_of_birth` and `application_date` (`derivation: age_on_application_date`). A person can never type it. |
| **Bundle** | `SchemeBundle` in `src/rules/bundles.py`: the pinned package of one scheme (rule package hash, registry hash, allowed `fact_ids`). Its fact list is the **allowlist** for that scheme's documents and form. |
| **Mock form mapping** | A data file in `data/schemes/mock_forms/<SCHEME_ID>.json` that says which facts fill which fields of the synthetic form. It is not an official form. |
| **Interrupt / pause** | A LangGraph feature that stops a graph and saves its state until someone resumes it. |
| **Checkpoint** | The saved graph state in SQLite. |
| **Idempotent** | Doing it twice has the same result as doing it once (same receipt, no second submission). |
| **ReAct loop** | A bounded loop: the model picks one allowed action, code runs it, the model sees a typed result, then picks the next action. |
| **Budget** | Per-conversation ceilings on model calls, tokens and actions. |
| **Trace** | Metadata about each step (action name, status, tokens). Never prompts, private reasoning or applicant values. |

---

## 3. The big picture: processes and who may talk to whom

There are **several moving parts**, not one. The old single combined MCP entry point
no longer exists; each MCP server has one purpose.

```text
Streamlit UI (src/ui)
     |  HTTP, only through src/ui/api_client.py
     v
FastAPI API (src/api/app.py)  --- LangGraph journey + SQLite checkpoints
     |
     |  one MCP client per service (stdio)         ServiceClientRouter
     +--> rule-engine   (src/mcp_servers/rule_engine_server.py)
     +--> schemes-kb    (src/mcp_servers/schemes_kb_server.py)
     +--> doc-check     (src/mcp_servers/doc_check_server.py)
     +--> mock-portal   (src/mcp_servers/mock_portal_server.py)
                              |
                              |  HTTP to 127.0.0.1 (internal only)
                              v
                 Independent portal API (src/portal/app.py)
                              |
                              v
                 Portal SQLite database (drafts + dependency tables)
```

Two rules make this safe to reason about:

1. The `mock-portal` MCP server is only an **adapter**. It forwards each call
   over HTTP to the independent portal, which owns the database.
2. The API's `ServiceClientRouter` decides **who may call what** before a
   request leaves the API process (section 4).

The API starts everything in its `lifespan` function: it starts the portal child
process, starts the four MCP servers, and **refuses to start** if a server's
discovered tool list differs from the expected list:

```python
if discovered_names != SERVICE_TOOLS[service_name]:
    ...
    raise RuntimeError(
        f"MCP service {service_name} tool inventory mismatch; ..."
    )
```

The portal only answers health checks from the process that launched it, using a
random startup token (`src/api/portal_service.py`, `src/portal/app.py`). Only the
`schemes-kb` child receives an embedding credential; the document and portal
servers get no API keys.

### The four MCP servers

| Server | Tools | Purpose |
|---|---|---|
| `rule-engine` | `evaluate_eligibility`, `required_facts` | Deterministic eligibility |
| `schemes-kb` | `search_schemes`, `get_scheme`, `get_documents` | Scheme search and passages |
| `doc-check` | `check_documents` | Metadata-only checklist comparison (read-only) |
| `mock-portal` | `create_draft`, `get_draft`, `get_status`, `submit_draft`, `mock_portal` | Adapter to the portal |

Each server file is tiny. For example `doc_check_server.py`:

```python
mcp = MCPServer("doc-check")
register_tools(mcp)
```

`tests/test_mcp_services.py::test_each_mcp_process_discovers_only_its_registered_tools`
checks that each process exposes only its own tools.

---

## 4. Who is allowed to do what (actors)

`src/mcp_servers/service_routing.py` holds two tables. `ACTOR_TOOLS` says which
**tools** an actor may call. `PORTAL_ACTIONS` says which **portal actions** an
actor may use inside the broad `mock_portal` tool.

| Actor | Portal actions it may use |
|---|---|
| `api_read` | `list_drafts`, `get_draft`, `get_status` |
| `application` | list/get/status, `create_draft`, `edit_draft`, `submit` |
| `human_approval` | `get_draft`, `approve`, `reject` |
| `session_cleanup` | `delete_journey` |
| `dependency_control` | `begin_profile_change`, `reconcile_profile`, `bind_documents`, `bind_rules`, `dependency_status` |

Notice that **`application` cannot approve or reject**, and `human_approval`
cannot submit. Approval and submission are different powers held by different
actors. The documents actor can only use `get_documents` and `check_documents`.

The identity is attached in trusted Python code:

```python
def for_actor(self, actor, journey_id=None) -> "ServiceClientRouter":
    """Bind identity in trusted Python code, never from tool arguments."""
```

and `call_tool` refuses any argument named `actor`, `caller` or `trusted_actor`.
A portal call must also carry the **bound journey ID**, so one conversation
cannot touch another conversation's drafts.

`tests/test_mcp_permissions.py::test_denied_calls_never_execute` runs about
twenty bad calls (an application actor trying `approve`, a documents actor
trying `create_draft`, a spoofed `actor` argument, a wrong journey ID, and so on)
and asserts the downstream service was **never called**, not merely that an error
was raised. `test_trusted_actors_execute_only_their_allowed_portal_actions`
proves the allowed actions actually work.

---

## 5. The journey graph and the supervisor plan

A Phase 4 request (check documents, create a draft, approve, submit...) is an
**application task**. The API route calls `run_application_task` in
`src/workflow/journey.py`, which validates the task shape (`ApplicationTask` in
`src/workflow/state.py`; callers cannot name arbitrary MCP tools) and runs the
same supervisor graph.

`build_application_plan` in `src/workflow/supervisor.py` writes the plan:

| Operation | Plan steps |
|---|---|
| `check_documents` | documents |
| `create_draft`, `approve`, `submit` | documents, then application |
| `edit_draft`, `reject`, `delete_journey` | application only |

```text
START -> supervisor
           |
           +-> document_agent ----> supervisor   (read-only check)
           +-> application_agent -> supervisor   (portal action)
           |
           +-> END when the plan finishes or stops
```

If the document step does not report `checklist_complete` for
`create_draft`, `approve` or `submit`, the supervisor stops the plan and the
API returns 409 ("Complete every synthetic demo document item..."). The
application step never runs, so nothing is written.

`run_application_task` is wrapped by `_serialize_journey`, which takes a
**per-conversation lock in this Python process** so two requests for the same
conversation do not race on the checkpoint or the budget counters. This lock is
not shared between processes; this guide makes no multi-process claim.

---

## 6. The document specialist: compare typed fields, never read files

### 6.1 The checker (plain Python)

`src/mcp_servers/tools/documents.py` holds the comparison. The list of
required documents no longer lives in this file: it comes from a shared
checklist file loaded by `src/documents/checklists.py` (section 6.4). This
section covers only the comparison types. Each checklist item can have an
optional **name** and **date of birth** (`SyntheticDocumentMetadata`).
`assess_document_metadata` compares them with the confirmed profile:

```python
def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(c for c in normalized if c.isalnum())
```

So "Synthetic  Example" and "synthetic-example" match (spacing, case and
punctuation are ignored), but "Different Synthetic Example" does not. The
function `_assessed_item` applies four rules per item:

| Situation | Item status | Extra output |
|---|---|---|
| Typed name differs from profile name | `mismatch` | discrepancy code `name_mismatch` |
| Typed date differs from profile date of birth | `mismatch` | discrepancy code `date_of_birth_mismatch` |
| A name/date was typed but the profile has none to compare with | `unknown` | none |
| No typed fields | the status the person chose (default `unknown`) | none |

The overall status is computed by code from **groups** (section 6.4), not from
single items. Each applicable group is `available`, `missing`, `unknown` or
`mismatch`; groups whose condition says "does not apply" are skipped. If all
applicable groups are `available`, the result is `checklist_complete`;
otherwise any `mismatch` gives `mismatch`; then `missing_items`, then
`unknown_items`. If the checklist cannot be trusted or loaded, the result is
`requirements_unverified`. A discrepancy contains only the document ID and the
code, **never the typed values**. The message always says that no file was
uploaded, read or authenticated.

`tests/test_document_and_application_agents.py::test_document_checker_compares_synthetic_name_and_date_without_echoing_values`
covers the matching case, a name mismatch, a date mismatch, and a missing profile
name, and asserts the name never appears in the message.

### 6.2 The bounded specialist wrapper

`run_document_specialist` in `src/workflow/document_agent.py` offers a model only
**two actions**: `inspect_document_metadata` and `handoff_documents`. The
handoff choices are `ready`, `correction`, `clarification` and `referral`, and
code translates the report into the one correct answer:

```python
def _expected_document_outcome(status: str) -> tuple[str, str]:
    return {
        "checklist_complete": ("ready", "documents_ready"),
        "mismatch": ("correction", "resolve_mismatch"),
        "missing_items": ("clarification", "complete_demo_checklist"),
        ...
    }.get(status, ("referral", "requirements_unverified"))
```

The model sees only the **status and discrepancy codes**, not typed names or
dates (`InspectDocumentsObservation`). If it picks a handoff that does not match
the report, the action is rejected. Two tests cover this:
`test_document_specialist_selects_allowed_handoff_from_observation` (all five
statuses) and `test_document_specialist_rejects_mismatched_handoff_and_tool_error`.

> **Read this before relying on the fallback label.** When **no model is
> configured**, the wrapper runs the deterministic check directly. When a
> configured model is unavailable or the durable model-call budget is exhausted,
> code may perform the one backend-authorized deterministic operation (if the
> remaining durable tool budget permits it). A denied or malformed model choice,
> including a mismatched handoff, does **not** trigger recovery and the graph
> fails closed. The label `deterministic_fallback` therefore describes a
> code-owned recovery, not a second model attempt.

### 6.3 What `document_agent` records

`document_agent` in `journey.py` calls `check_and_bind_documents`
(`src/api/applications.py`), which calls `check_documents` through the
`documents` actor, then uses the `dependency_control` actor to call
`bind_documents`. The API's saved-report recheck
(`_mark_changed_document_reports`) calls the same function, so both produce
identical fingerprints. Binding
stores a hash of the report in the portal. If the report **differs** from the
last one for that conversation and scheme, the portal bumps the document version
and marks existing unsubmitted drafts for that scheme stale (section 9).

It also computes an **input fingerprint** (`document_input_fingerprint` in
`src/api/applications.py`) over the scheme, statuses, typed fields, profile
name and date, the profile facts used by conditions, the typed facts, the bundle
fingerprint and the three checklist digests (section 6.4). The graph saves it with the assessment. The API refuses to create a draft
unless the draft request reproduces that same fingerprint and the saved
assessment is `checklist_complete` for the **current profile version**.
`test_synthetic_application_requires_exact_approval` proves a changed profile name
gets 409.

### 6.4 The shared file-backed checklist

**Where it lives.** One JSON file per scheme in `data/schemes/document_checklists/`
(`<SCHEME_ID>.json`) and one shared evidence file,
`data/schemes/document_evidence.json`. Both Dockerfiles copy them into the
images. `load_checklist_snapshot(scheme_id)` in `src/documents/checklists.py`
reads them directly **by scheme ID**. There is no search and no ranking.

**Both tools use that one loader.** `get_documents` (in
`src/mcp_servers/tools/scheme_search.py`) returns the checklist, and
`check_documents` (in `documents.py`) compares typed statuses with it. The
portal re-reads it too (section 9). So they cannot disagree about which list
is active. There is no retrieval ranking or model call that chooses required
documents. Today the graph calls `check_documents`; `get_documents` is
available to the documents actor but has no graph caller yet.

**Source quote versus structured checklist.** These are two different things
and they live in two different files.

The evidence file keeps the **original words** of a source, plus where they
came from (shortened here; the real schema also has `language`,
`collected_on` and `publication_date`):

```json
{
  "passage_id": "SYNTH-IDENTITY",
  "scheme_id": "SYNTH-SCHEME",
  "section": "documents",
  "exact_quote": "Invented example: bring any one of a photo card or a ration book, and always bring a bank passbook.",
  "source_url": "https://example.test/synthetic",
  "source_locator": "Invented page, heading 1",
  "review_status": "reviewed"
}
```

The checklist file is the team's **reading** of that quote, as data (the
`labels` in three languages are left out here):

```json
{
  "requirement_id": "identity_group",
  "alternatives": [{"document_id": "photo_card"}, {"document_id": "ration_book"}],
  "condition": {"kind": "unconditional"},
  "evidence_passage_ids": ["SYNTH-IDENTITY"]
}
```

(Both are **invented** for teaching. They are not an official list, and no
real scheme text is in this guide. The shortened checklist snippet omits the
separate bank-passbook group used in the explanation below.)

**How "any one" and "must have" work.** A `requirement` is a **group**. The
group is satisfied when **any one** of its `alternatives` is `available`
(`_group_status` in `documents.py`). **Every** applicable group must be
satisfied. In the example above, a photo card **or** a ration book satisfies
the identity group, and a separate bank-passbook group must also be satisfied.
One available photo card does not cover the passbook group. A group is
`unknown` (not skipped) if a condition cannot be decided yet.

**Conditions.** A group may apply only in some cases. Three typed condition
kinds exist (all defined in `src/documents/checklists.py`):

| `kind` | Shape | Use |
|---|---|---|
| `unconditional` | `{"kind": "unconditional"}` | Always required (every pilot group today) |
| `profile_boolean` | `{"field": "is_widow" \| "bpl_card_shown", "equals": true \| false}` | **Legacy bridge** for the two pilots only; it must map to a fact in the scheme bundle's `legacy_profile_mapping` |
| `registered_fact` | `{"fact_id": ..., "operator": "eq" \| "gte" \| "lte", "value": ...}` | Any **registered** fact allowed by the scheme's bundle |

`DocumentChecklist.validate_registry` checks every `registered_fact`
condition against the registry: the type must fit (booleans and choices allow
only `eq`; dates, integers and decimals allow `eq`, `gte`, `lte`; `text`
facts can never control a requirement), the value must be inside the fact's
bounds or choices, and decimals and dates must be exact strings.
`condition_applies` returns true, false or `None`. `None` means "the fact is
not known yet", and that group is reported `unknown`, never silently dropped.
Free-text or executable conditions are not allowed: the strict schema rejects
them. Details of the allowlist and derived facts are in section 6A.

**Reading the trust state.** `load_checklist_snapshot` returns a
`ChecklistSnapshot` with one `trust_status`:

| `trust_status` | Meaning |
|---|---|
| `demo_only_unverified` | Pilot demo checklist; no evidence linked |
| `approved_source_backed` | Human-approved, every linked passage `reviewed`, digests match |
| `requirements_unverified` | Anything else: pending review, invalid, missing, wrong scheme |
| `conflict`, `superseded` | The checklist or a linked passage says so |

Only the first two are `usable`. Otherwise the report is
`requirements_unverified` with **no** groups.

**"Source linked" is not "reviewed".** Adding `evidence_passage_ids` to a
checklist only links words to a group. It does **not** say the team read the
list correctly. The checklist approval and the source-passage review are
separate checks. For `approved_source_backed`, all of these must hold: the
approval status is `approved`; every group has linked evidence; every linked
passage is `reviewed`; the approval records a reviewer role, a reference and
a date; and two content digests in the approval match the files.
The checklist digest covers the checklist content without its `approval`
block; the evidence digest covers the **whole** evidence file. Citations are
returned only in this state.

**Bad data never means "no documents needed".** A missing file, bad JSON, a
schema error, duplicate IDs, a wrong `scheme_id`, a missing or other-scheme
evidence link, or a `demo_only` checklist with evidence all produce
`requirements_unverified` (`_failure_snapshot`). The UI then tells the person
to ask a human caseworker. An empty or broken list is never treated as "nothing
required".

**The pilot demo is unchanged.** `IGNWPS-MH` and `PM-KISAN-IN` keep the same
document IDs as before (for example `identity_proof`, `land_record`), now one
single-alternative, unconditional group each, status `demo_only`,
`checklist_version` `v1`, no evidence. The evidence file has an empty
`passages` list. **No official data has been added.** Preparing real source
passages and checklist content is a human task that runs in parallel; it is
not part of this code and an agent does not approve it.

**Versions and fingerprints.** The snapshot carries `checklist_version`
(shown in the UI), two file digests and one combined fingerprint:
`checklist_fingerprint` (exact checklist file bytes),
`evidence_fingerprint` (exact evidence file bytes) and
`active_fingerprint` (both digests, the scheme and the trust status together).
Changing **either** file, even with the same version label, changes
`active_fingerprint`. This is a content check, not a trust in the label.

**What a change does.**

* The API compares the saved report with a fresh snapshot
  (`_mark_changed_document_reports` in `src/api/app.py`). A different
  `active_fingerprint` marks the report stale, and the UI asks for a recheck.
* `bind_documents` sends the three digests to the portal. The portal rejects
  digests that do not match its own fresh read
  (`_snapshot_matches_request`), and `_refresh_document_dependency` raises the
  document version when the active fingerprint changes. That makes each
  **unsubmitted** draft for the scheme stale and clears its approval.
* Portal transactions and the supported file-update helper share a lock that
  works across processes (a `filelock.FileLock` on
  `.document_checklists.lock`, built by `_publication_lock` with
  `is_singleton=True` so a nested use in the same thread does not wait for
  itself). An update waits until submission has been saved.
  Submission waits if an update is already running. A failed lock stops the
  operation; it does not skip the check.
* The portal also checks the files again before saving
  (`_assert_snapshot_unchanged`).
* An already **submitted receipt is not changed**. It records what happened.

**A, then B, then A.** Use `publish_checklist_file` in
`src/documents/publication.py` to update reviewed evidence first, then each
affected reviewed checklist (and `publish_mock_form_file` for a form, section
6D). The helper validates the files; it does not
approve their meaning. Each update raises a saved revision number. Returning
to the earlier content does not lower that number or restore old approval.

**Important limit:** editing the files directly skips this shared lock and
revision number. Direct edits are not a supported way to update active lists.
The tests prove protection for updates made through the helper, not arbitrary
external file changes.

**UI labels.** `_render_document_groups` in `src/ui/app.py` shows the active
groups with a source label: "Demo-only list · not verified" for
`demo_only_unverified`, an approved-source label for `approved_source_backed`,
and a warning to ask a human caseworker otherwise. It also shows the checklist
version and a citation expander when citations exist. The saved-draft view in
`render_application_flow` shows the same version and an approved or demo label.
All three languages have these labels.

---

## 6A. Which facts a scheme's documents and form may use

Before this revision, "is this fact valid?" meant "does the global registry
know it?". An independent review showed that was too loose: a fact that
belongs to **another** scheme (for example `excluded_government_employee_member`,
a PM-KISAN fact) was accepted in an `IGNWPS-MH` checklist condition because the
global registry contained it. The fix is the **bundle allowlist**.

`document_fact_allowlist(scheme_id, registry, bundle)` in
`src/rules/bundles.py` returns only the `fact_ids` listed in that scheme's
`SchemeBundle`. It refuses when:

* the bundle is for a different scheme or registry version;
* a listed fact is missing from the registry, or (for the active provider) its
  definition differs from the one the rule engine loaded (so a caller cannot
  supply its own registry copy);
* a derived fact depends on a fact the bundle does not list.

`document_fact_values(scheme_id, registry, store, bundle)` then builds the
value map. It validates the `TypedFactStore`, then calls
`store.value(fact_id, registry)` for **each allowed fact only**. Because
`value` understands derivations, `age` arrives as a computed number, not a raw
copy of stored states. Stored-but-out-of-bundle facts are simply absent from
the map.

```python
return {fact_id: store.value(fact_id, registry) for fact_id in allowed}
```

The same allowlist is applied in every place that touches document data:
`DocumentChecklist.validate_registry`, `MockFormMapping.validate_registry`,
the loaders, startup readiness in `get_active_rule_data`
(`src/mcp_servers/rule_data.py`), the two publication helpers, the
`check_documents` tool and the portal's `create_draft` revalidation.

**Derived age example.** The age rule is data, not a branch in code:
`age` has `derivation: "age_on_application_date"` and is computed by
`TypedFactStore.value` using `calculate_age_on`. With date of birth
1970-11-05, an application date of 2026-11-04 gives 55, and 2026-11-05 gives
56. If either date is missing the value is `None`; a checklist condition
`{"kind": "registered_fact", "fact_id": "age", "operator": "gte", "value": 56}`
is then `unknown` and a form field mapped to `age` is reported **missing**.
Nobody can type an age directly: a typed store that contains `age` fails
`validate_against` ("cannot be supplied"), and `assess_document_metadata`
rejects a derived fact in `profile_facts` ("cannot be supplied directly").
`tests/test_document_checklists.py::test_derived_age_condition_and_form_use_confirmed_date_inputs`
covers all of this, and
`test_derived_document_fact_requires_authorized_dependency_closure` proves the
age value is returned while an out-of-bundle fact is excluded, and that
removing `application_date` from the bundle makes the call fail.

**Where typed values reach the checks.** The graph's `document_agent` passes
the saved `typed_facts` (a wire dictionary from `TypedFactStore.to_wire`) to
`check_documents`. The tool restores it with `TypedFactStore.from_wire`,
which turns tagged decimals (`{"$decimal": "12.50"}`) back into `Decimal` and
ISO dates back into `date` without float rounding. The API form preview and the
portal use the same restore step.

---

## 6B. Data-defined mock forms

A scheme's synthetic form is a strict JSON file,
`data/schemes/mock_forms/<SCHEME_ID>.json`, loaded by `src/documents/forms.py`.
It is a **mapping**, not code: no expressions, no URLs.

```json
{
  "field_id": "exam_marks",
  "value_type": "integer",
  "required": true,
  "fact_id": "exam_marks",
  "minimum": 0,
  "maximum": 100
}
```

(`labels` in English, Hindi and Marathi are left out.) `MockFormField` allows six
types: `boolean`, `date`, `integer`, `decimal`, `choice` and `text`. Its
validator enforces:

* exactly one source: a registered `fact_id`, **or** `extra_input: true` for
  something the person must type on the form;
* a `choice` field lists unique `choices`; a `text` field needs `max_length`;
  only numeric fields may have bounds;
* when mapped to a fact, `MockFormMapping.validate_registry` requires the fact
  to be in the bundle allowlist, the type to match, choices to match exactly,
  and field bounds not to be wider than the fact's own bounds.

`load_mock_form_snapshot` reads the file under the shared publication lock. Any
problem (missing file, duplicate JSON keys, wrong scheme, bad mapping) returns a
snapshot with `mapping=None`, and the API answers "form unavailable" (HTTP 409);
the person is never shown a guessed form.

`build_form_fields(snapshot, registry, facts, extra_values, bundle=..., typed_store=...)`
fills the form. It returns `(values, missing)`:

* with a `typed_store` it resolves values through `document_fact_values`
  (section 6A), so derived facts work; without one, a mapped derived fact is
  rejected;
* `extra_values` may only name `extra_input` fields;
* `_validate_form_value` does **no coercion**: a boolean must be a real boolean,
  an integer may be an integer or digit-only text, a date must be an ISO date,
  a choice must be listed, text must fit `max_length`;
* a decimal goes through `Decimal(str(value))`, must be finite, and is stored
  as exact text (for example `"12.50"`), so the draft fingerprint never
  depends on binary-float rounding; dates are stored as ISO text;
* a required field with no value goes into `missing`; the API answers 422 and
  the UI shows a warning.

**Pilot forms.** `IGNWPS-MH.json` maps `date_of_birth` and `is_widow`;
`PM-KISAN-IN.json` maps `landholding_family_in_state_records`. They use the
**legacy bridge**: when a conversation has no typed store,
`_confirmed_form_values` in `src/api/app.py` and the portal read each mapped
value from the old profile through the bundle's `legacy_profile_mapping`.
The portal draft still carries two fixed fields, `applicant_reference` and
`district`; only those two can be edited (section 7.2). They are not
data-defined.

`publish_mock_form_file` is the supported way to change a form (section 6D).

---

## 6C. What is tied to an approval now

Because forms and bundles are data, the draft records every version and hash it
was built from. In `src/portal/repository.py`, `create_draft` writes these into
the draft payload, and the draft fingerprint is a SHA-256 of that whole
payload:

| Payload field | What it pins |
|---|---|
| `bundle_version`, `bundle_fingerprint` | The scheme bundle manifest (`bundle_fingerprint(bundle)`) |
| `registry_version`, `registry_sha256`, `rule_package_sha256` | Exact fact registry and rule package hashes |
| `checklist_version`, `checklist_fingerprint`, `evidence_fingerprint`, `active_checklist_fingerprint` | The checklist, evidence and trust state (section 6.4) |
| `form_version`, `form_mapping_fingerprint`, `form_status` | The form mapping file |
| `form_fields`, `form_field_types` | The exact values (decimals and dates as text) and their types |
| `fact_definition_versions` | The definition version of every fact used |
| `profile_version`, `document_version`, `rules_version` | The dependency counters from section 9 |

On the API side, `document_input_fingerprint` now also covers the saved
`typed_facts` and `_bundle_fingerprint`, so a changed fact value or bundle
invalidates the saved document report. Before an edit, approval or first
submission, `edit_application_draft` and `update_application_approval` compare
the draft's `bundle_fingerprint` and `form_mapping_fingerprint` with the
current ones; a difference gives 409 ("create and review a new draft"). Rule
package, profile and revision/fingerprint checks stay as before.

Approval itself is unchanged: **a human only**, through the `human_approval`
actor, for the exact revision and fingerprint, **provisional for 15 minutes**,
one-use token, and the same receipt on an exact retry (sections 8 to 10). The
UUID in the URL is still a demo capability, not authenticated citizen
identity. Changing a form, bundle, checklist, fact definition or answer means
a new draft, a fresh review and a fresh approval; a change that goes A to B to
A never restores an old approval.

---

## 6D. How data changes are published today (read this before editing data)

Inspecting the code shows **two** supported single-file helpers, not an atomic
bundle publisher:

| Helper | Changes | What it does |
|---|---|---|
| `publish_checklist_file` (`src/documents/publication.py`) | one checklist or the evidence file | validate, take the shared lock, add 1 to the persistent revision, atomically replace the file |
| `publish_mock_form_file` (`src/documents/forms.py`) | one form mapping | validate against the active registry and bundle, take **the same lock**, add 1 to **the same revision**, atomically replace the file |

Because the revision is part of the checklist `active_fingerprint`, a supported
form or checklist update makes existing unsubmitted drafts for the scheme stale
the next time the portal looks, even if the content later returns to what it
was. There is **no** helper that publishes the rule package, fact registry,
bundle manifest, checklist, evidence and form together. Those are separate
files and separate calls, so a reader between two calls can see a new form with
an old checklist. Rule packages, the registry and the bundle manifest are loaded
once at startup (`get_active_rule_data` is cached), so changing them needs a
restart and a new `bundle_fingerprint`. A crash after the revision advances but
before the file is replaced can only invalidate approvals conservatively; retry
the update. Editing files directly bypasses the lock and the revision; the API
routes still notice a changed form or bundle hash at edit, approval and
submission, but that is a safety net, not a supported update path.

---

## 7. The application specialist and the portal

### 7.1 The specialist

`run_application_specialist` offers one operation action
(`prepare_draft`, `edit_draft`, `submit_draft` or `read_application_status`) and
one `handoff_application`. These two tools are the model's whole allow-list
(`run_agent(..., [portal_action, handoff_application], ...)`). Approval and
rejection are **not** among them, so a model that asks for `approve` is denied
by LangChain before anything runs
(`test_application_specialist_denies_spoofed_approval_and_never_reports_tool_failure_as_success`).

The observation returned to the model (`ApplicationActionObservation`) contains
the operation, a short status, the revision and a boolean `receipt_recorded`.
It does **not** contain the approval token, the draft contents or any name.

`execute()` inside `application_agent` is where all the trusted checks live. Before
any write it rechecks: the draft exists and belongs to this conversation, it is
not stale, the revision and fingerprint match what the person saw, the profile
and rule package version still match the saved draft, and the current verdict is
still `eligible` (asked again through the rule engine). Each failure becomes a
short 409 message.

> **Committed-write boundary.** With a model configured, `execute()` runs in the
> first step and the handoff is the second. If the handoff fails after the
> portal write, the specialist preserves the committed draft or receipt and
> reports `action_completed_handoff_incomplete`; it does not pretend that the
> write failed. A later exact `create_draft` retry is deduplicated to the
> current record for that conversation and scheme, even if the record was edited
> after creation. Submission retries remain one-receipt idempotent (section 10).

### 7.2 The portal

`src/portal/repository.py` is the only code that touches the portal database. One
function, `_portal_action`, handles every action inside a SQLite
`BEGIN IMMEDIATE` transaction, so reads and writes are serialized by the database.

Tables:

| Table | Key | Holds |
|---|---|---|
| `application_drafts` | `draft_id` | payload, `revision`, current `fingerprint`, original `creation_fingerprint`, approval fields, `stale`, `submitted_receipt` |
| `journey_dependencies` | `journey_id` | `profile_version`, `blocked` |
| `document_dependencies` | `(journey_id, scheme_id)` | document `version` and report hash |
| `rule_dependencies` | `(journey_id, scheme_id)` | rule `version` and fingerprint |

Every lookup uses **both** `draft_id` and `journey_id`. Asking for a real draft
from the wrong conversation returns `{"not_found": True}`
(`test_edit_invalidates_approval_and_old_fingerprint` checks this).

The draft payload includes the dependency versions, so they are part of the
fingerprint:

```python
"profile_version": dependency["profile_version"],
"document_version": ...,
"rules_version": ...,
```

`create_draft` refuses unless the active checklist is trusted and complete
(`checklist_complete`, re-assessed in the portal from the saved typed facts),
the report fingerprint matches the one the graph saved, and the data-defined
form has no missing required field (section 6B). It fingerprints the full original
payload, including every version and hash in section 6C. An exact retry is
scoped to the same conversation and scheme and returns the existing current
record instead of creating a duplicate; this remains true after an edit because
the original `creation_fingerprint` is retained. A changed payload, scheme or
conversation creates a different draft. An `edit_draft` only allows two fields
(`applicant_reference`, `district`), creates a **new revision**, recomputes the
current fingerprint and **clears any approval**. The mapped form values cannot
be edited on a saved draft: change the answer and create a new draft instead.

---

## 8. Approval: a paused graph plus a human actor

Approval is a real pause, not a flag. `src/workflow/application_gate.py` builds a
tiny second graph with one node that calls LangGraph's `interrupt`:

```python
async def approval_gate(state):
    decision = interrupt({
        "draft": state["draft"],
        "message": "Review and decide on this exact synthetic draft.",
    })
    return {"decision": decision}
```

Its thread key is a stable hash of conversation ID, draft ID **and revision**
(`application_gate_thread_id`). A new revision therefore gets its own pause; the
old pause cannot be reused for it.

```text
create_draft / edit_draft
   portal saves draft (approved = false)
   pause_for_application_approval  -> graph stops, state checkpointed
                  ... person reads the exact draft ...
approve or reject (API route, human click)
   resume_application_approval     -> checks the decision equals what was paused
   portal "approve" via actor human_approval -> approval + expiry + token
submit (separate request)
   portal "submit" via actor application, using the stored token
```

`resume_application_approval` raises if the returned decision differs from the
one it was given. If the pause is missing (for example after a restart that lost
it), it recreates the pause before resuming, so a retry still works.

**Who is "the human"?** The `human_approval` actor is chosen by trusted code
when the operation is `approve` or `reject`; the model cannot choose it. In this
demo the approver is whoever can call the approval API route (normally through
the Streamlit buttons). There is **no login**: the conversation UUID is a
synthetic capability/locator, not verified citizen authentication, so the
backend cannot tell a person from a script that can reach the API. Treat this
as a boundary of the demo, not as human identity proof.

---

## 9. Dependency versions: why old approvals never come back

An approval depends on three things staying the same: the **profile** (answers),
the **document report**, and the **rule package**.

| What changed | Portal action (actor `dependency_control`) | Effect |
|---|---|---|
| A confirmed answer is corrected | `begin_profile_change`, later `reconcile_profile` | Profile version +1; all unsubmitted drafts for the conversation become stale; writes are **blocked** until reconcile |
| The document report differs, or the checklist or evidence file content changes | `bind_documents` | Document version +1 for that scheme; its unsubmitted drafts become stale (section 6.4) |
| The rule package differs | `bind_rules` (fingerprint of the package) | Rule version +1 for that scheme; its unsubmitted drafts become stale |
| The mock form mapping or bundle changes | Supported form publication raises the shared revision (section 6D); the API also compares `form_mapping_fingerprint` and `bundle_fingerprint` at edit, approval and first submission | Old drafts become stale or are refused with 409; a fresh draft and review are needed |

"Stale" clears the approval, the expiry and the token in one update, and
`_portal_action` refuses to touch a stale, unsubmitted draft except to read it:

```python
if row["stale"] and not row["submitted_receipt"]:
    raise RuntimeError("Dependencies changed. Create and approve a fresh draft.")
```

**Why A -> B -> A does not revive an approval.** Suppose a person has answer A,
approves a draft, changes it to B, then changes back to A. The version counter
only goes up (0, 1, 2) and the stale flag is never cleared. Going back to A does
not make the old draft current. The person must create a **fresh draft** (which
records profile version 2) and approve it again. The same holds for documents
(`available -> missing -> available`) and rules (fingerprint a, b, a). For
checklist files the rule is "the portal must have seen B"; see the A, B, A
note in section 6.4 for the exact boundary.

Tests: `test_approved_draft_correction_always_revokes_saved_approval` (four
answer changes, including "don't know"),
`test_monotonic_rule_and_document_changes_never_revive_approval_and_keep_receipts`
(and it checks an already-submitted receipt stays valid), and
`test_document_report_change_revokes_approval_and_never_revives_it`.

Two more failure tests guard the **gap** between "revoke in the portal" and
"save the new answer in the graph checkpoint":

* `test_correction_persistence_failure_blocks_old_submission` makes the
  checkpoint, the invalidation call, or the recheck fail. Afterwards submit is
  still blocked ("reconciliation").
* `test_concurrent_submission_cannot_slip_between_invalidation_and_checkpoint`
  pauses a correction midway and starts a submit; the submit waits and then fails.

The per-conversation lock mentioned in section 5 is what makes the second test
work. It is an in-process lock; these tests do not prove behavior across several
API processes.

---

## 10. Expiry, one-use authorization, receipts, duplicates and restart

When the portal approves, it stores the approval time, an expiry and a token:

```python
APPROVAL_TTL_SECONDS = 15 * 60
...
expires_at = (datetime.fromisoformat(now) + timedelta(seconds=APPROVAL_TTL_SECONDS)).isoformat()
approval_token = uuid4().hex
```

So an approval is **provisional for 15 minutes**. `_approval_expired` **fails
closed**: missing, malformed, timezone-less, or implausibly long expiry times all
count as expired. `_safe_record` then reports `approved: false` and
`approval_expired: true`.

`test_expired_or_malformed_approval_fails_closed` edits the stored expiry to the
past, to a day in the future, and to garbage, then asserts approval is gone and
submit says "expired". It changes the stored value; it does not wait on a real
clock. Whether 15 minutes is the right product choice is still open.

Submission is **one-use**:

```python
if row["submitted_receipt"]:
    if request.approval_token and row["approval_token"] and hmac.compare_digest(...):
        return _safe_record(row)          # exact retry: same receipt
    raise RuntimeError("This submission authorization was already consumed.")
```

| Request | Result |
|---|---|
| First submit with the right token | Creates the receipt |
| Same submit again (same token, revision, fingerprint) | Returns the **same receipt**; no second submission |
| Submit with a different token | "already consumed" |
| Submit with a different fingerprint or revision | "stale" |
| Submit after expiry (before any receipt) | "expired" |

`test_authorization_is_one_use_and_exact_retry_returns_the_same_receipt` runs two
submits at the same time on two threads and asserts both get the same receipt,
then checks the other rows of the table. `test_submit_requires_approval_and_is_idempotent`
covers the single-thread version. Because drafts, approvals and receipts live in
SQLite on disk, they survive an API restart.
`test_approval_revocation_and_fresh_exact_approval_survive_sqlite_restart` reopens
new SQLite connections and rebuilds the graph objects mid-journey, then repeats
the submit and still gets one receipt. That is a **same-process reopen**, not a
test that kills and relaunches the program.

The token is an internal credential, so it stays out of public responses:
`_public_application_record` in `src/api/app.py` removes
`approval_token` before JSON leaves the API.

---

## 11. A full example with synthetic data

Use only invented data. Profile name "Synthetic Example", date of birth
1986-01-01, scheme `IGNWPS-MH`.

| Step | What the person does | What the system does |
|---|---|---|
| 1 | Evaluates the scheme; result is `eligible` | Rule engine decides; verdict saved |
| 2 | Types identity proof name "Different Synthetic Example", all items `available` | `check_documents` -> status `mismatch`, code `name_mismatch`. A draft attempt gets **409** |
| 3 | UI shows a correction message (no file was read) | Person fixes the typed name |
| 4 | Rechecks with "Synthetic Example" | Status `checklist_complete`; input fingerprint saved |
| 5 | Changes the profile name slightly and tries a draft | **409**: report no longer matches |
| 6 | Prepares the draft with the checked values | Portal creates **revision 1**; graph pauses for approval |
| 7 | Tries to submit | **409**: not approved |
| 8 | Edits the district to "Nashik" | **Revision 2**, new fingerprint, approval cleared |
| 9 | Tries to approve with revision 1's fingerprint | **409**: the displayed draft is stale |
| 10 | Approves revision 2 | Portal stores approval, expiry (+15 min) and token |
| 11 | Submits | Receipt recorded |
| 12 | Submits again (a retry, such as a double click) | **Same receipt** |
| 13 | Forgets the conversation | Application drafts, portal dependency rows, journey/application-gate threads and the conversation's budget record in the LangGraph `Store` are deleted; listing drafts returns empty. |

This is the sequence in `tests/test_api_applications.py::test_synthetic_application_requires_exact_approval`,
which goes through FastAPI and real MCP child processes. The test setup removes
model keys, so no paid call happens.

If the same person had instead corrected a **profile answer** after step 10 (A to
B and back to A), the draft would be stale and steps 6 to 11 would repeat with a
fresh draft.

### 11B. A scheme that exists only as data (synthetic scholarship)

`tests/test_ui_integration.py::test_development_scholarship_reaches_exact_mock_receipt_through_real_ui`
is the proof that a new scheme needs **no `src/` branch**. The scheme
`TEST-SCHOLARSHIP` lives only under `tests/fixtures/phase4/`: a rule package,
a fact registry (`exam_marks` integer, `exam_ratio` exact decimal, `exam_stream`
choice, `guardian_consent` boolean), a development-only bundle, a checklist and
a form mapping. It is
injected only by `SCHEME_SAATHI_TEST_RULE_PACKAGE_DIR`, which `src/config.py`
accepts **only under pytest** and only for paths inside `tests/fixtures`.
The normal catalogue, the two pilot pins and the pending review gates are
untouched; this is a strict development-test injection, not an activated
scheme. The test clicks the real Streamlit screen through FastAPI, four MCP
child processes and the portal:

| Step | What happens |
|---|---|
| 1 | The generic registry question flow asks each fact: a number box for marks (80), exact text `0.12345678901234567` for the decimal ratio, a choice list for stream, a yes/no radio for consent ("I don't know"). The rule package says `eligible`; the saved decimal uses the exact `$decimal` wire value |
| 2 | The identity alternatives have an exact decimal condition `exam_ratio gte "0.12345678901234567"` (applies at the boundary). The checklist also has `exam_marks gte 70` (applies) and `guardian_consent` (unknown, so the group is `unknown`). Status `unknown_items`; no draft button appears |
| 3 | The person corrects `guardian_consent` to yes through the generic correction control, then rechecks, marks documents available and types the extra form field `student_identifier` |
| 4 | Status `checklist_complete`; the API preview and draft preserve decimal text `0.12345678901234567` without float rounding, alongside marks 80, stream "science" and the typed student identifier. The saved field type is `decimal`; the test checks the canonical draft fingerprint |
| 5 | A human approves that exact revision. Through the real correction control, the person changes the ratio to `0.12345678901234568`, still eligible. The old submit gets **409**; saved and refreshed old drafts are `stale` and unapproved, with no submit button. Rechecking creates a different draft/fingerprint containing the exact corrected decimal, which needs fresh human approval |
| 6 | The test publishes a changed form (`max_length` 23) with `publish_mock_form_file` and a new checklist (`v2`, marks threshold 75) with `publish_checklist_file`. Submission of that second approved draft gets **409**; it becomes `stale` and unapproved |
| 7 | In a refreshed session the person corrects the ratio back to the original exact `0.12345678901234567`. Both earlier drafts remain stale/unapproved and both old submits still get **409**: A→B→A does not revive approval. Rechecking creates a third draft (different ID, checklist `v2`, different `form_mapping_fingerprint`), requiring fresh human approval before submission |
| 8 | The submitted draft and its exact retry preserve original decimal `0.12345678901234567`, the same fingerprint and **same receipt**; the database holds 3 drafts and 1 receipt |

The `finally` block restores both files and deletes the lock and revision
files the test made. The test asserts zero model calls
(`journey_agent_budget`), so no paid call is involved.

### Flowchart

```text
          eligible result
                |
                v
   type names/dates, mark items
                |
                v
        check_documents -----> mismatch? ---yes--> show codes
                |                                      |
                no                                     | correct typed fields
                |                                      v
                |<------------------------------- recheck
                v
        checklist_complete + input fingerprint saved
                |
                v
        create_draft (revision 1) --> PAUSE (approval gate)
                |
     edit? --yes--> new revision, approval cleared, new pause
                |
                v
   person reviews EXACT revision + fingerprint
        |                    |
     reject               approve (human_approval actor)
        |                    |
      stop           expiry +15 min, one-use token
                             |
                             v
                   submit (application actor)
                             |
                  receipt; retry returns same receipt

   Any profile/document/rule change at any point -> draft stale -> create a fresh one
```

---

## 12. Scoped to its own conversation

Everything that can change a draft is keyed by the conversation (journey) ID:

* The router rejects a portal call whose `journey_id` is not the bound one.
* Every portal query uses `draft_id AND journey_id`.
* The approval pause thread ID is derived from conversation, draft and revision.
* The one-use token, expiry, revision and fingerprint belong to a single draft row.
* Dependency versions live under `journey_id` (and scheme).

A request with a valid draft ID from another conversation sees "not found", and
a request with an old revision or fingerprint is refused.

---

## 13. Safe tracing and the model budget

Every agent model call and tool call, valid or not, is recorded by
`ScrubbedTraceMiddleware` (`src/workflow/agent_middleware.py`) as one
`trace_event`. It holds the agent name, action name, status, model name, prompt
version, step number, token counts, duration and a fixed one-line summary. It
has **no prompt, no private reasoning and no applicant values.** The prompts
(`src/workflow/agent_config.py`) also tell the model not to return private
reasoning and to treat outside text as data. `DurableBudgetMiddleware` makes
every model request a single strict tool call (`tool_choice="required"`).
Before text reaches a model, LangChain's `PIIMiddleware` (with Saathi's
`PII_RULES`) replaces emails, Aadhaar-like numbers, phone numbers and account
numbers. These guards are LangChain middleware passed to `create_agent`; see
[HOOKS_WALKTHROUGH.md](HOOKS_WALKTHROUGH.md).

The budget limits (in `agent_config.py`) are **per conversation**: 8 model calls,
24 tool/action calls, 12 agent steps, 12,000 tokens, and 3 steps per turn. The
24-call ceiling includes deterministic document rechecks, lost-response draft
recovery and exact receipt retries; it does **not** buy extra model calls.
`DurableBudgetMiddleware` **reserves** tokens and counters *before* the paid call
and saves them in the LangGraph `Store` through `ConversationBudget`
(`src/workflow/conversation_budget.py`), so a crash
or restart cannot give a conversation a fresh budget. A model-assisted document
or application specialist normally uses two model calls (one action and one
handoff), but those calls consume the same global conversation budget; the
budget is not reserved separately for each specialist. Earlier interview or
specialist work can therefore leave too little budget for a later specialist.
If the model is unavailable or the model-call ceiling is reached, the
code-selected specialist operation may recover once by reserving one remaining
durable tool call. This keeps the total model-call ceiling at 8; it is not a
22-call increase. Denied or malformed model choices do not receive this
recovery.

---

## 14. API, UI and languages

| Route (under `/api/v1/journey/{conversation_id}`) | Does |
|---|---|
| `POST /documents` | Check typed metadata (documents task) |
| `POST /drafts` | Create a draft (needs a matching complete assessment) |
| `GET /drafts`, `GET /drafts/{draft_id}` | Read, scoped to the conversation |
| `PUT /drafts/{draft_id}` | Edit district/reference as a new revision |
| `POST /drafts/{draft_id}/approval` | Body `action` is `approve`, `reject` or `submit`, plus revision and fingerprint |
| `DELETE /` | Forget the conversation |

Routes stay thin: they translate HTTP, re-read the saved state, and call
`_dispatch_application_task`; the graph does the work. The UI calls these only
through `src/ui/api_client.py` and draws them in `render_application_flow`
(`src/ui/app.py`). After a stale draft it offers a recheck that, when complete,
creates the fresh draft automatically.

**Generic routing (no scheme names in the UI).** The interview screen asks the
API for the next question. If the response carries a `question_definition`
(registry-backed), `registered_answer_input` draws the widget from the fact's
type: a radio for boolean, a bounded number box for integer, a text box that
is sent as exact text for decimal, a choice list, or a date. Otherwise the
older chat box is used for the legacy pilot path. "Start again" calls
`start_interview`, which begins a new conversation, and a page refresh
restores the saved one from the URL. For documents, `POST /documents` returns
a `form_preview` built by `_confirmed_form_values`. `_render_form_preview` shows
each mapped fact value read-only and draws an input only for fields marked
`extra_input`; `_form_values_from_session` sends back only those values.
Caveat: the wider screen still has pilot-named code. The top-level router in
`src/ui/app.py` special-cases `PM-KISAN-IN` and the widow-pension screen, and
`render_verdict` picks PM-KISAN wording by scheme ID. Any other scheme falls
through to the generic `render_interview` branch, which is the one the
synthetic scholarship test uses. The document and form-preview code itself
names no scheme.

Languages: the UI text tables have English, Hindi and Marathi entries (for
example `mismatch_help`, `resolve_mismatch`, `approval_expired`), the stale-draft
message comes from `discovery_message` in `src/workflow/discovery.py` in all
three languages, and the agent prompts exist per language. The API's own HTTP
error strings are English; the UI shows a generic localized
`application_error` instead of them. The rejected-draft notice, "Edit and
reopen draft" button, "Synthetic applicant reference" label and receipt label
now also come from the three-language text tables. Native-speaker review of
the Hindi and Marathi wording is still open.

---

## 15. File and function map

| Idea | File | Look for |
|---|---|---|
| Four MCP entry points | `src/mcp_servers/*_server.py` | `mcp = MCPServer(...)` |
| Shared MCP error format | `src/mcp_servers/contracts.py` | `tool_error` |
| Actor and action permissions | `src/mcp_servers/service_routing.py` | `ACTOR_TOOLS`, `PORTAL_ACTIONS`, `ServiceClientRouter` |
| Checklist file loader and trust | `src/documents/checklists.py` | `load_checklist_snapshot`, `ChecklistSnapshot`, `condition_applies`, `_failure_snapshot` |
| Checklist data | `data/schemes/document_checklists/`, `data/schemes/document_evidence.json` | one `<SCHEME_ID>.json` per scheme; empty `passages` today |
| Checklist comparison | `src/mcp_servers/tools/documents.py` | `assess_document_metadata`, `_group_status`, `_assessed_item` |
| Direct checklist tool | `src/mcp_servers/tools/scheme_search.py` | `get_documents`, `SchemeDocuments` |
| Portal adapter (MCP to HTTP) | `src/mcp_servers/tools/applications.py` | `_call_portal`, `mock_portal` |
| Portal HTTP service | `src/portal/app.py` | `/internal/actions`, `/health` |
| Portal rules and SQLite | `src/portal/repository.py` | `_portal_action`, `_approval_expired`, `APPROVAL_TTL_SECONDS`, `_snapshot_matches_request`, `_refresh_document_dependency`, `_assert_snapshot_unchanged`, `_revoke_unsubmitted_approvals`, `_recheck_checklist` |
| Start/stop the portal | `src/api/portal_service.py` | `start_portal_service` |
| API routes | `src/api/app.py` | `lifespan`, `create_application_draft`, `update_application_approval`, `_mark_changed_document_reports`, `_tool_failure` |
| Report fingerprint, tool caller | `src/api/applications.py` | `document_input_fingerprint`, `check_and_bind_documents`, `call_application_tool` |
| Bounded document specialist | `src/workflow/document_agent.py` | `run_document_specialist` |
| Bounded application specialist | `src/workflow/application_agent.py` | `run_application_specialist` |
| Agent run, masking | `src/workflow/agent_runtime.py` | `run_agent` (LangChain `create_agent`), `PII_RULES`, `mask_sensitive_text`, `recover_authorized_action` |
| Budget and trace middleware | `src/workflow/agent_middleware.py` | `DurableBudgetMiddleware`, `ScrubbedTraceMiddleware` |
| Limits and prompts | `src/workflow/agent_config.py` | `MAX_CONVERSATION_MODEL_CALLS` |
| Durable budget (LangGraph `Store`) | `src/workflow/conversation_budget.py` | `ConversationBudget`, `BUDGET_NAMESPACE` |
| Approval pause | `src/workflow/application_gate.py` | `pause_for_application_approval`, `resume_application_approval` |
| Graph nodes | `src/workflow/journey.py` | `document_agent`, `application_agent`, `run_application_task` |
| Plan for tasks | `src/workflow/supervisor.py` | `build_application_plan` |
| UI screen | `src/ui/app.py` | `render_application_flow`, `_render_document_groups`, `_render_form_preview`, `_form_values_from_session`, `registered_answer_input` |
| UI client | `src/ui/api_client.py` | `assess_documents`, `decide_application_draft` |
| Typed fact store and derived age | `src/rules/facts.py` | `TypedFactStore`, `value`, `to_wire`, `from_wire`, `calculate_age_on` |
| Bundle allowlist | `src/rules/bundles.py` | `document_fact_allowlist`, `document_fact_values` |
| Fact and bundle data | `src/rules/fact_registry.json`, `src/rules/bundle_registry.json` | one registry; pilot bundles are `legacy_compatibility` |
| Mock form models and loader | `src/documents/forms.py` | `MockFormField`, `load_mock_form_snapshot`, `build_form_fields` |
| Supported publication helpers | `src/documents/publication.py`, `src/documents/forms.py` | `publish_checklist_file`, `checklist_publication_lock`, `_publication_lock` (publication.py); `publish_mock_form_file` (forms.py) |
| Form data | `data/schemes/mock_forms/` | one mapping file per scheme |
| MCP rule data | `src/mcp_servers/rule_data.py` | startup load of rules, registry and bundles |
| Synthetic scholarship fixtures (tests only) | `tests/fixtures/phase4/` | `development_only` bundle, registry 9.0.0, all reviews `pending` |
| Test-only injection | `src/config.py` | `SCHEME_SAATHI_TEST_RULE_PACKAGE_DIR` (pytest and `tests/fixtures` only) |

---

## 16. Tests and why they exist

All of these run offline with no paid calls (the specialist tests use a fake
model; the API test has no model key).

| Test | Why it exists |
|---|---|
| `test_document_checker_compares_synthetic_name_and_date_without_echoing_values` | Proves the comparison is code-owned and values are never echoed |
| `test_approved_shared_checklist_preserves_any_one_and_condition_scope` | Proves any-one groups and conditional groups work on an approved synthetic checklist |
| `test_each_applicable_group_is_required_and_unknown_condition_is_not_skipped` | Proves every applicable group is needed and an undecided condition stays `unknown` |
| `test_checklist_approval_and_evidence_status_fail_closed` | Proves incomplete approval or unreviewed evidence is never `approved_source_backed` |
| `test_broken_or_rejected_evidence_never_becomes_a_verified_list` | Proves bad or rejected evidence gives no verified list |
| `test_invalid_schema_duplicate_ids_and_wrong_scheme_fail_closed` | Proves invalid checklist data fails closed |
| `test_same_version_checklist_or_evidence_mutation_invalidates_approval` | Proves an edit with the same version label still voids approval |
| `test_missing_checklist_is_not_an_empty_verified_requirement_list` | Proves a missing file is not "no documents needed" |
| `test_pilot_demo_files_keep_existing_ids_and_are_not_official` | Proves the two pilot demo checklists keep their IDs and stay demo-only |
| `test_portal_accepts_only_a_fresh_approved_source_report` | Proves the portal accepts only a report bound to the current checklist digests |
| `test_document_specialist_*`, `test_application_specialist_*` | Proves a model can only pick a handoff that matches the observed report, and cannot reach approval |
| `test_denied_calls_never_execute` | Proves denials stop **before** a service is called |
| `test_expired_or_malformed_approval_fails_closed` | Proves bad time data means "not approved" |
| `test_authorization_is_one_use_and_exact_retry_returns_the_same_receipt` | Proves a double submit gives one receipt (two threads, one process) |
| `test_application_specialist_preserves_committed_write_if_handoff_fails` | Proves a committed portal result is returned even when the model's terminal handoff fails |
| `test_repeated_draft_creation_is_idempotent_for_exact_current_dependencies` | Proves an exact create retry returns the current edited record, not a duplicate |
| `test_model_budget_allows_safe_document_recheck_draft_and_submission_after_restart` | Proves the original 8-call ceiling remains bounded while code-owned recovery completes the synthetic flow |
| `test_model_enabled_application_journey_fits_durable_conversation_budget` | Proves a model-enabled journey stays at the original 8-call ceiling and falls back deterministically when the ceiling is reached |
| `test_model_recovery_never_bypasses_the_remaining_tool_budget` | Proves recovery needs a remaining durable tool reservation |
| `test_forgetting_a_journey_removes_its_portal_dependencies_only` | Proves one journey's portal dependencies are deleted without touching another journey |
| `test_document_report_change_revokes_approval_and_never_revives_it` | Proves a document change makes drafts stale |
| `test_approved_draft_correction_always_revokes_saved_approval` | Proves profile changes (including A to B to A) cannot revive approval |
| `test_correction_persistence_failure_blocks_old_submission` | Proves a half-finished correction still blocks submit |
| `test_concurrent_submission_cannot_slip_between_invalidation_and_checkpoint` | Proves a racing submit cannot slip through |
| `test_monotonic_rule_and_document_changes_never_revive_approval_and_keep_receipts` | Proves rule/document counters only go up, and old receipts survive |
| `test_approval_revocation_and_fresh_exact_approval_survive_sqlite_restart` | Proves persisted state after reopening the SQLite files |
| `test_synthetic_application_requires_exact_approval` | The whole example in section 11, through the API |
| `test_mock_form_rejects_facts_outside_actual_scheme_bundle` | A form cannot map a fact outside its scheme's bundle |
| `test_checklist_rejects_global_fact_and_loader_cannot_bypass_scope` | A fact that is only in the global registry is rejected by a checklist |
| `test_additional_fact_mapping_requires_explicit_bundle_membership_and_version` | Extra mapped facts need bundle membership and matching registry version |
| `test_out_of_bundle_form_is_rejected_by_loader_and_publication` | Loader and `publish_mock_form_file` both refuse out-of-bundle forms |
| `test_forged_checklist_cannot_bypass_mcp_portal_or_publication` | A forged out-of-bundle checklist fails at MCP, portal and publication |
| `test_startup_rejects_out_of_bundle_document_data` | Startup refuses bad document data |
| `test_caller_registry_cannot_replace_active_bundle_fact_definitions` | A caller-supplied registry cannot replace the active definitions |
| `test_derived_age_condition_and_form_use_confirmed_date_inputs` | Derived `age` is computed from dates (DOB 1970-11-05: 55 on 2026-11-04, 56 on 2026-11-05) and cannot be injected |
| `test_derived_document_fact_requires_authorized_dependency_closure` | A derived fact is allowed only if its sources are in the bundle |
| `test_supported_publication_is_atomic_and_tracks_restore_revision` | The single-file helpers hold one lock and raise the shared revision (single file only; see section 6D) |
| `test_failed_publication_lock_prevents_portal_action_and_file_change` | A failed lock blocks both the portal action and the file change |
| `test_development_scholarship_reaches_exact_mock_receipt_through_real_ui` (`tests/test_ui_integration.py`) | Section 11B: a data-only scheme through UI, API, 4 MCP children and portal, with form and checklist changes |
| `test_phases_one_to_four_ui_receipt_retry_and_scoped_forget`, `test_approved_ui_correction_refresh_requires_fresh_report_draft_and_review` | Pilot receipt/retry/forget and correction-after-approval through the real UI |

Why "failure" tests matter: a happy-path test shows that the feature works; a
failure test shows that the feature **cannot be tricked**. In an approval flow
the failures are the product.

The checklist and form tests are in `tests/test_document_checklists.py`; the
real-screen tests are in `tests/test_ui_integration.py`; the others are
mostly in `tests/test_document_and_application_agents.py`, `tests/test_api_applications.py` and
`tests/test_application_tools.py`.

**Latest reported evidence (quoted from the reports; not rerun for this
guide).** The original independent review passed 145 tests but found that
facts from another bundle were accepted through the global registry. After the
bundle-scope repair: 139 focused, 411 full serial and 9 independent
regressions passed. After the derived-age omission repair: 143 focused and 415
full passed, and an independent check of the checklist selection passed 31
tests (4 targeted derived-fact cases). Compilation and `git diff --check`
also passed. None of this is a native Python 3.12/CI run, and it does not
replace a restart test across separate processes, a multi-worker test,
real-browser checks, independent language review, source/privacy review or
live-model validation.

**Automated proof follow-up (2026-11-05):** the expanded synthetic scholarship
case passed **1 test in 113.71s**; after final fingerprint/retry assertions,
the UI integration plus checklist selection passed **34 tests in 152.99s**.
The single final serial full suite passed **415 tests in 278.01s**; compileall
and `git diff --check` passed. No runtime implementation changes were needed.
Only development fixture data/pins, the existing integration test and evidence
documentation changed; the reviewed pilot pins remain unchanged. These are
builder-run offline checks, not a new independent review or manual/CI approval.

**Literal receipt-proof clarification (2026-11-05):** the same bounded scenario
now corrects `.68` back to original `.67` after the previous approval is
cancelled, rejects submission of both old drafts after A→B→A, and freshly
approves/submits/retries exact `0.12345678901234567`. The exact integration test
passed **1 test in 91.01s**; compileall and diff checks passed. The three-draft,
one-receipt count is unchanged. No runtime changes or full-suite repeat were
needed/requested; the 415-test full run above predates this test-only adjustment.

---

## 17. Known limits and open items

* **Implemented:** a shared, file-backed, versioned checklist with any-one
  groups, typed `registered_fact` conditions, a legacy `profile_boolean`
  bridge, bundle-scoped facts, data-defined mock forms and source-trust
  validation (sections 6.4 to 6D).
  **Not implemented:** real uploads, OCR, authenticity or identity checks.
  **No official checklist data is included**; the pilot lists are demo-only.
* **Open:** source data preparation and human review for real checklists (a
  parallel human step, not approved by any agent), manual browser run-through,
  Hindi/Marathi wording review, source/privacy and fact/question review,
  native Python 3.12/CI, and ratification of the 15-minute window.
  The two Phase 1 pilot pins are unchanged and no novel scheme is approved or
  activated; `TEST-SCHOLARSHIP` is a pending, development-only test fixture.
  Phase 5 is paused. This guide's independent review result is **PASS WITH
  GAPS**; its two automated proof gaps are addressed by the follow-up below,
  without claiming a new independent review result.
* **Checklist limits:** `profile_boolean` (`is_widow`, `bpl_card_shown`) is
  legacy only. `get_documents` has no graph caller yet. Active
  checklist, evidence and form updates must use the supported helpers; direct
  file edits bypass the tested lock and revision tracking.
* **Publication is not an atomic full bundle.** Rules, registry, bundle,
  checklist, evidence and form are separate files; the helpers publish one file
  at a time, and rules/registry/bundle are loaded once at startup
  (section 6D).
* **Bounded proof gaps addressed by automated follow-up:** the existing
  scholarship AppTest now sends a decimal-mapped field through actual typed
  intake, API preview, portal fingerprint, human approval and receipt retry.
  It corrects that typed decimal after approval in the same real UI/API/MCP/
  portal flow, verifies stale/unapproved old state and rejected old submission,
  then requires fresh draft approval. Section 11B records the exact values and
  the single-receipt assertions. No workflow or portal response is fabricated.
  These checks close the two reported automated proof gaps; they do not
  constitute independent re-review or any manual/source/privacy/CI approval.
  Pilot-named legacy code remains in the portal `create_draft`
  (`is_widow`, `bpl_card_shown` conditions), the API draft fingerprint call and
  the UI router; these are necessary adapters for the still-supported pilot
  bundles, not newly surfaced defects. Naming cleanup belongs after the
  generic data-only gates close.
* **No login:** whoever reaches the approval route acts as the human; the
  conversation UUID is a demo capability, not verified citizen identity.
* **Model-configured fallback:** only model unavailability or model-budget
  exhaustion permits one code-authorized deterministic operation, subject to the
  remaining durable tool budget. Denied or malformed choices still fail closed.
  A handoff failure after a write now preserves the committed result and reports
  an incomplete handoff; exact create retries are deduplicated (sections 6.2
  and 7.1).
* **Forgetting a conversation** deletes its drafts, portal dependency-version
  rows, journey/application-gate checkpoint threads and the conversation's
  budget record in the LangGraph `Store` (namespace `("budget",)`).
* **Multi-process behavior:** a separate-process test covers checklist updates
  competing with submission. This is not a full test of several API workers
  or recovery after killing processes at every stage.
* **UI errors:** application failures show one generic localized message, not the
  specific reason (expired, stale, wrong revision).
