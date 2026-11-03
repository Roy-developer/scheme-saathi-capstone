# Phase 4 code walkthrough: documents, an exact draft and a human decision

This guide explains the current local Phase 4 code in plain English. It
starts after eligibility, follows a synthetic document checklist into a
saved draft, and shows why approving one revision must never approve a
different revision. Read it beside the source: the aim is to understand
both **what each function does** and **why the flow is split this way**.

Read [Phase 1](PHASE1_CODE_WALKTHROUGH.md) for the deterministic rule
engine, [Phase 2](PHASE2_CODE_WALKTHROUGH.md) for the supervisor and graph
pauses, and [Phase 3](PHASE3_CODE_WALKTHROUGH.md) for shared interviews,
per-scheme results and corrections.

Plan: [Phase-wise implementation plan](PHASE_WISE_IMPLEMENTATION_PLAN.md),
section **Phase 4 — Documents and approval**.

> **Implementation is not sign-off.** This describes the intentional,
> uncommitted local Phase 4 implementation on **3 November 2026**. The
> recorded local compilation and full offline suite passed: **196 tests**.
> Manual browser checks and earlier phase sign-offs remain pending.
> GitHub validation was blocked by the dirty worktree; nothing was deployed.
> These documentation edits do not rerun or replace those checks.
>
> **Synthetic demonstration only.** A positive eligibility result means
> the supplied facts satisfy the dated mock rule package. Document checks
> use user-reported **metadata only**. The two demo checklists are **not
> verified official requirements**. There are no uploads, OCR, document
> authenticity checks or identity validation. A mock receipt is not a
> government submission, benefit approval or payment.

---

## 1. The problem Phase 4 solves

An eligibility result answers one question:

> Do these reported facts meet this scheme's current mock rules?

It does not answer:

> Which draft did the person review, and did they approve that exact draft?

Imagine that a person approves a draft with district “Synthetic district”.
Someone then changes the district to “Nashik”. A simple `approved=True`
flag would be dangerous if it survived that edit: it would make the old
decision appear to cover something the person had not reviewed.

Phase 4 therefore keeps three different ideas separate:

| Question | Who answers it? | What it does not prove |
|---|---|---|
| Does the profile meet the mock eligibility rules? | Deterministic engine, called through MCP | That the facts are true or a benefit is officially approved |
| Has every demo checklist item been reported available? | Read-only `check_documents` tool | That an actual document exists, is genuine or meets official requirements |
| Has this exact saved draft revision been approved? | Human decision, checkpointed approval gate and portal checks | That an authenticated government applicant submitted an official application |

The LLM does not make any of these eligibility or approval decisions.
Earlier search/intake model assistance remains separate from this flow.

### The big picture

Think of the supervisor as a counter manager with four specialists and a
search helper:

```text
                          SUPERVISOR
                  writes a plan and reads reports
                              |
          +-----------+-------+--------+-------------+
          |           |                |             |
       intake     eligibility       documents    application
     asks facts   calls MCP rules   reads metadata writes mock portal
                              |
                      search helper also routes
                      through the supervisor
```

The search helper is another route, not a document or application writer.
The actual graph uses these node names:

```text
START -> supervisor
           |
           +-> intake_agent -> ask_user [interview pause]
           |        ^              |
           |        +-- answer ----+
           |        +-> supervisor when intake finishes
           |
           +-> eligibility_agent -----> supervisor
           +-> scheme_search_tool ----> supervisor
           +-> document_agent --------> supervisor
           +-> application_agent -----> supervisor
           |
           +-> END when the request's plan finishes or stops
```

The two new specialists do **not** call each other. The document specialist
reports to the supervisor; the supervisor decides whether to route the
next step to the application specialist.

### Two graphs, not one blocked conversation

There is an important second graph:

```text
Main journey thread                         Approval thread
key: conversation ID                        key: conversation + draft + revision

supervisor -> documents -> supervisor
            -> application ----------------> save draft, then interrupt
            <- awaiting_approval             [waiting for human decision]
            -> supervisor -> END                        |
                                                        |
later approve/reject request ---------------------------+
                                             Command(resume=decision)
                                             -> END
```

The approval graph is built separately and uses a separate checkpoint
thread. Its pause does not leave the main journey thread interrupted.
That lets another eligible scheme's application work proceed while one
draft waits for review. It does **not** establish safe concurrent writes
to the same conversation from multiple requests.

### Words you will meet

| Word | Simple meaning here |
|---|---|
| Metadata | A reported status such as `available`; not a file or its contents |
| Draft payload | The application content saved inside the draft record |
| Revision | A counter starting at 1 and increased by each saved edit |
| Fingerprint | A SHA256 digest of a consistently formatted payload |
| Approval gate | A small saved graph that pauses for a human decision |
| Checkpoint | Saved graph state that can be read or resumed later |
| Idempotent submit | Repeating a valid submit for the same draft returns the existing mock receipt |
| Stale request | A request referring to a revision or fingerprint that is no longer current |

---

## 2. File map and a useful reading order

These are responsibilities, not separate independent features. Each row
connects to the next part of the end-to-end flow.

| Read | File | What to look for |
|---|---|---|
| 1 | `src\mcp_servers\tools\documents.py` | `DEMO_REQUIREMENTS`, `DocumentCheckInput`, `assess_document_metadata`, `register_tools` |
| 2 | `src\mcp_servers\tools\applications.py` | `PortalInput`, `_canonical_fingerprint`, `_portal_action`, `_safe_record`, `register_tools` |
| 3 | `src\mcp_servers\saathi_mcp_server.py` | Both new modules register tools on the same MCP server |
| 4 | `src\api\applications.py` | Four strict HTTP request models and `call_application_tool` |
| 5 | `src\workflow\application_gate.py` | Build, identify, pause and resume the per-revision approval graph |
| 6 | `src\workflow\state.py` | `ApplicationTask`, `ApplicationOperation`, `Handoff`, `Plan`, `PlanStep` |
| 7 | `src\workflow\supervisor.py` | `build_application_plan` and the document-specific stop in `advance_plan` |
| 8 | `src\workflow\journey.py` | `run_application_task`; nested `document_agent` and `application_agent` in `build_journey_graph` |
| 9 | `src\api\app.py` | Startup wiring, route checks, task dispatch and session deletion |
| 10 | `src\ui\api_client.py`, `src\ui\app.py` | HTTP helpers, `render_application_flow`, plan updates and restored state |
| 11 | `tests\test_application_tools.py`, `tests\test_api_applications.py`, `tests\test_ui_app.py` | Evidence for the boundaries above |

If you are building this again, start with the pure metadata assessment
and portal operations, then add the approval gate, graph routing, API and
screen. Starting with buttons alone makes it too easy to confuse “button
disabled” with “backend action forbidden”.

---

## 3. Meet one synthetic applicant

We will follow the same kind of synthetic profile used by the Phase 4
tests. Give the draft a reference such as **Synthetic applicant 2**, never
a real person's name or identifier.

```json
{
  "date_of_birth": "1986-01-01",
  "application_date": "2026-01-01",
  "is_widow": true,
  "bpl_card_shown": true
}
```

The dates are fixed so the example does not change with today's date.
The deterministic engine returns `eligible` for `IGNWPS-MH` with this
synthetic profile under the current mock package. That result is saved in
the conversation before document/application tasks begin.

For the walkthrough, suppose the person first reports:

```json
{
  "identity_proof": "available",
  "age_proof": "available",
  "widow_status_proof": "available",
  "bpl_proof": "missing"
}
```

The eligibility fact `bpl_card_shown` and the checklist item `bpl_proof`
are different fields in different stages. The checklist does not silently
change the profile or rerun an interview. A reported missing item blocks
draft preparation even if the earlier mock eligibility verdict is positive.
Conversely, reporting every item available cannot turn a negative
eligibility verdict into a positive one.

We will return to this person after explaining each building block.

---

## 4. Step 1: a document checker that only reads metadata

**File:** `src\mcp_servers\tools\documents.py`

### 4.1 What the checker receives

`DocumentCheckInput` contains:

| Field | Meaning |
|---|---|
| `scheme_id` | Which scheme's demo checklist to use |
| `documents` | Dictionary from checklist item ID to reported status; defaults to an empty dictionary |

`DocumentStatus` allows exactly `available`, `missing`, `unknown` and
`mismatch`. Extra top-level fields are forbidden. For a configured scheme,
an item ID that is not in its checklist raises an error rather than being
silently treated as a valid requirement.

No field accepts uploaded bytes, extracted text, a scanned image or an
identity verification result.

### 4.2 Which items are configured?

`DEMO_REQUIREMENTS` is an explicit, small demonstration table:

| Scheme | Demo item IDs |
|---|---|
| `IGNWPS-MH` | `identity_proof`, `age_proof`, `widow_status_proof`, `bpl_proof` |
| `PM-KISAN-IN` | `identity_proof`, `land_record`, `bank_account_proof` |

The labels call each item a “synthetic demo item”. Do not copy this table
into public advice as an official application checklist. The code has not
established that these are the real requirements of either scheme.

### 4.3 How `assess_document_metadata` chooses a status

For a supported scheme it walks the configured items in order. A missing
entry in the input dictionary becomes `unknown`, not `available`.

The overall result follows this order:

```text
All configured items available? -> checklist_complete
Otherwise any mismatch?        -> mismatch
Otherwise any missing?         -> missing_items
Otherwise                     -> unknown_items
```

This means a report containing both `missing` and `mismatch` has overall
status `mismatch`; the individual item statuses are still returned so the
screen can show the full picture.

For a scheme with no configured checklist, the function instead returns
`requirements_unverified` with an empty `requirements` list.

| Example input | Overall result | Meaning |
|---|---|---|
| Supported scheme, empty report | `unknown_items` | Nothing has been reported yet |
| Three available, one missing | `missing_items` | A demo item still needs attention |
| Any item mismatch | `mismatch` | A mismatch has been reported, not detected by document inspection |
| Every configured item available | `checklist_complete` | The reported demo checklist is complete |
| Unsupported checklist | `requirements_unverified` | The app has no configured requirements to assess |

The positive name is **`checklist_complete`**, not the earlier
`ready_for_demo` wording. It deliberately says what is complete: the
checklist, not the person's real documents or application readiness.

### 4.4 What comes back

For a configured scheme the assessment contains:

- `scheme_id`;
- `status`;
- `demo_only: true`;
- `requirements`, with each item's `document_id`, `label` and `status`;
- a message explaining that requirements are not verified official
  requirements and that nothing was uploaded or authenticated.

The MCP wrapper `register_tools` exposes this as **`check_documents`**.
Validation errors and invalid item IDs become MCP `ToolError`s.

**Why keep it separate?** This function can answer “what did the user
report?” without creating a draft, changing an approval or writing a mock
receipt. The workflow's `document_agent` calls this tool, not the portal.

For our example, `bpl_proof="missing"` produces `missing_items`. A
document-check request can successfully return that result: a successful
assessment is not the same as permission to proceed.

---

## 5. Step 2: save the mock draft, not just a screen flag

**File:** `src\mcp_servers\tools\applications.py`

### 5.1 One action-based MCP tool

The portal is exposed as **`mock_portal`**, with an `action` selecting one
operation. It is not a collection of model-chosen arbitrary tool names.

| Action | Purpose |
|---|---|
| `list_drafts` | Return the conversation's saved drafts in creation order |
| `get_draft` | Read one draft within the supplied conversation |
| `create_draft` | Save a synthetic payload at revision 1 |
| `edit_draft` | Save allowlisted fields as a new revision and clear approval |
| `approve` | Record approval for the exact revision and fingerprint |
| `reject` | Mark the exact draft rejected and clear approval |
| `submit` | Save or return a mock receipt, only for the approved exact draft |
| `delete_journey` | Delete this conversation's portal draft rows |

`PortalInput` rejects undeclared fields and limits the action to this
literal set. Its fields cover several actions, so `_portal_action` also
does action-specific checks. A field being optional in the shared model
does not mean every action can safely omit it.

### 5.2 Where the records live

`_database_path` chooses `SCHEME_SAATHI_APPLICATION_DB`, with a default of
`data/runtime/applications.sqlite3`. This is a runtime database, not a
fixture or a file to commit.

`_connect` opens SQLite, enables WAL journal mode and ensures the
`application_drafts` table exists. Each `_portal_action` begins
`BEGIN IMMEDIATE`, then commits its successful action or rolls back on an
exception.

The main stored fields are:

| Stored field | Why it exists |
|---|---|
| `draft_id`, `journey_id`, `scheme_id` | Identify the draft and scope reads/actions to its conversation |
| `revision` | Detect actions made from an old view |
| `payload`, `fingerprint` | Save the content and its canonical digest |
| `approved_revision`, `approved_fingerprint` | Remember exactly what was approved |
| `rejected` | Distinguish rejection from a draft awaiting review |
| `submitted_receipt` | Keep one mock submission receipt for repeated submits |
| `created_at`, `updated_at` | Record creation and the most recent stored change |

This is a transaction around **one portal action**. It is not a transaction
covering the HTTP request, journey checkpoints, approval checkpoints and
portal database together.

### 5.3 What creation actually stores

Before creating a draft, `_portal_action` requires:

1. A scheme supported by the demo checklist table.
2. A profile and document report.
3. Nonblank applicant-reference/district values when supplied.
4. A fresh call to `assess_document_metadata` returning
   `checklist_complete`.

It then saves this payload:

| Payload key | Source |
|---|---|
| `scheme_id` | Selected scheme |
| `profile` | Workflow-supplied profile snapshot |
| `rule_package_version` | Workflow-supplied package version |
| `deciding_rule_ids` | Workflow-supplied current eligibility evidence IDs |
| `documents` | Assessed checklist items, including labels and statuses |
| `applicant_reference` | Supplied synthetic reference, or `Synthetic applicant` |
| `district` | Supplied value, or `Synthetic district` |
| `declaration` | Explicit statement that this is a synthetic demonstration, not a government application |

The portal checks checklist completeness, but it does not independently
call the eligibility engine. The workflow's application specialist owns
that rule recheck. Do not treat a low-level tool call as equivalent to the
full checked HTTP/workflow path.

### 5.4 How the fingerprint works

This is the actual fingerprint function:

```python
def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

“Canonical” here means using the same JSON formatting rules each time.
Dictionary keys are sorted; insignificant spacing is removed. Reordering
dictionary keys therefore does not change the digest. Array order still
matters, and changing a payload value changes what is hashed.

The hash covers the payload, including the profile, package version,
checklist, reference, district and declaration. The outer revision number
is **not** part of that payload. This is why the approval check needs
**both the revision and the fingerprint**, not the fingerprint alone.

A saved edit increments the revision even if the two editable values do
not actually change. In that case the digest can stay the same, but the
old revision's approval is still cleared.

The fingerprint is a content digest, not a password, digital signature,
identity proof or guarantee against a malicious database administrator.

### 5.5 What `approved` means on a returned record

`_safe_record` returns the outer record:

```text
draft_id, journey_id, scheme_id, revision
draft                  <- decoded payload
fingerprint
approved
rejected
receipt_id
```

It computes `approved` from the saved exact-match fields:

```python
"approved": (
    row["approved_revision"] == row["revision"]
    and row["approved_fingerprint"] == row["fingerprint"]
),
```

There is no general “this person approved all future versions” setting.
Rejection and edits clear these saved approval fields. Submission keeps
them, so a submitted record can still report `approved=True`; `receipt_id`
is what tells the UI that mock submission has already happened.

### 5.6 Edits, rejection and submission

**Edit:** `edit_draft` requires the current revision, updates only
`applicant_reference` and `district`, strips their surrounding whitespace,
increments the revision, recalculates the fingerprint, clears approval and
sets `rejected=0`. It does not let the user edit the profile, scheme,
document report or rule evidence through this endpoint.

**Approve:** requires the current revision and fingerprint. The portal
refuses approval of a rejected or already submitted record.

**Reject:** also requires the exact pair, refuses an already submitted
draft, marks rejection and clears approval. It does not create a receipt.

**Submit:** first checks the pair. If a receipt already exists, it returns
the same record. Otherwise it requires approval of this revision and
fingerprint, and requires that the record is not rejected, before storing
a generated receipt.

The workflow additionally refuses edits of submitted drafts. That guard
is in `application_agent`; do not infer that every workflow restriction
is independently repeated in every low-level portal branch.

For our example, once every demo item is reported available, creation
produces revision 1, an unapproved record and no receipt. Nothing has been
submitted merely because the row exists.

---

## 6. Step 3: make human review a real saved graph pause

**File:** `src\workflow\application_gate.py`

### 6.1 What this graph does, and what it does not do

`build_application_gate` creates a deliberately small graph:

```text
START -> approval_gate -> END
                |
                +-- interrupt({"draft": ..., "message": ...})
                    wait here until a decision is supplied
```

Inside its node, the important lines are:

```python
decision = interrupt({
    "draft": state["draft"],
    "message": "Review and decide on this exact synthetic draft.",
})
return {"decision": decision}
```

An interrupt is not a blocking browser dialog and not a Python loop that
waits forever. LangGraph saves the pause using its checkpointer and
returns control to the caller. A later request resumes the node with
`Command(resume=decision)`.

The gate saves the review/decision flow. It does **not** itself approve a
portal row, determine eligibility or submit anything. The application
specialist performs the surrounding checks and portal action.

### 6.2 Why each revision needs a different thread

`application_gate_thread_id(conversation_id, draft_id, revision)` uses
UUID5 to produce a stable identifier from all three values.

```text
Conversation C, draft D, revision 1 -> approval thread A
Conversation C, draft D, revision 2 -> approval thread B
Conversation C, draft E, revision 1 -> approval thread C
```

The same inputs identify the same thread. A different draft or revision
gets a different one. This separates reviews without putting the profile
into the thread identifier. UUID5 is deterministic, not an access-control
or authentication mechanism.

### 6.3 Pausing after creation or edit

`pause_for_application_approval`:

1. Builds the per-revision thread configuration.
2. Reads the existing checkpoint.
3. Returns if that thread already has an interrupt.
4. Otherwise invokes the graph with the draft.
5. Reads state again and requires an interrupt to exist.

`application_agent` calls it after successful portal creation or edit.
This is the link between “saved content” and “saved review required”.

Because an edit creates a new revision, it opens a new review thread.
An older revision's paused checkpoint can remain until session cleanup;
it is not a route to approving current content. The API, specialist and
portal compare the requested pair with the current portal record.

### 6.4 Resuming on approve or reject

`resume_application_approval` reads the matching thread. If it has no
interrupt, it calls the pause helper first. It then invokes
`Command(resume=decision)` and checks that the returned `decision` equals
the supplied decision.

The application specialist supplies these decision fields:

```text
action, draft_id, revision, fingerprint
```

It resumes the gate for **approve or reject**, not for submit.
Submission is a later action against the portal's saved approval.

**Important limit:** the gate can create a pause when one is absent; it
does not prove an original pause survived every possible failure.
Furthermore, the specialist resumes the gate **before** the approve/reject
portal write. A portal failure after that point can leave the graph
decision and portal state out of step. Conversely, create/edit writes the
portal before pausing. There is no cross-database atomic commit or fully
implemented crash-recovery guarantee here.

The portal's exact-match approval checks remain essential; the presence
of a graph interrupt is not a substitute for them.

---

## 7. Step 4: let the supervisor route the work

**Files:** `src\workflow\state.py`, `src\workflow\supervisor.py`,
`src\workflow\journey.py`

### 7.1 The task contract

`ApplicationTask` has an `operation` from `ApplicationOperation` and an
`arguments` dictionary. The allowed operations are:

```text
check_documents, create_draft, edit_draft,
approve, reject, submit, delete_journey
```

The backend builds this task from a specific route. The public request
cannot choose an arbitrary MCP tool name. The operation is typed;
individual argument checks also happen in HTTP models, specialist logic
and the portal/checklist models. The task's generic argument dictionary
is not, by itself, a full schema for every operation.

`Handoff` requires supervisor-to-specialist or specialist-to-supervisor
communication. A documents-to-application handoff would fail its route
validation. This is a graph/data contract, not an operating-system
permission boundary between separate privileged processes.

### 7.2 `build_application_plan`: the order depends on the action

The supervisor uses this pure function to choose the request's plan:

| Operation | Plan, in execution order |
|---|---|
| `check_documents` | documents |
| `create_draft` | documents → application |
| `approve` | documents → application |
| `submit` | documents → application |
| `edit_draft` | application |
| `reject` | application |
| `delete_journey` | application |

The first step starts `in_progress`; later ones start `pending`.

Why check documents again before approve and submit? Those operations
must use the checklist saved in the draft, not an unrelated or newer
screen selection. The HTTP approval route extracts the saved item statuses;
the application specialist also compares them with the current record.

Editing only the reference/district does not edit the checklist, which is
why its plan has no document step. Rejecting should not force someone to
complete a checklist or regain eligibility just to decline a draft.

### 7.3 `advance_plan`: a completed check can still stop the application

`SUCCESS_STATUSES["documents"]` includes all five assessment outcomes,
including `missing_items` and `requirements_unverified`. This is not a
mistake: they are valid results of running the checker.

After marking that step `done`, `advance_plan` has a special rule:

```python
if specialist == "documents" and status != "checklist_complete":
    for step in plan.steps:
        if step.status == "pending":
            step.status = "skipped"
    return plan, None
```

So our example's first create attempt would finish as:

```text
documents:   done       result = missing_items
application: skipped   no portal write
```

For `create_draft`, `approve` or `submit`, the graph's supervisor turns
that stop into an application-task error with status 409 and a message to
complete every synthetic demo item.

A tool failure is different:

```text
documents:   failed    result = tool_error
application: skipped
```

A failed tool call does not become a fabricated “documents missing”
assessment or a new eligibility verdict.

### 7.4 `run_application_task`: continue without erasing eligibility

This is the application entry function in `journey.py`. It does not call
`run_journey` with a fresh eligibility request.

It first reads the conversation checkpoint:

- No saved conversation: 404, except deletion is allowed.
- Main journey currently interrupted for an interview: 409, except
  deletion is allowed.
- Otherwise, construct an `ApplicationTask` and run the main graph again.

Its graph input replaces the task/result/error fields and requests a new
plan. It does **not** reset the saved profile, candidate verdicts or full
eligibility results. The new plan version is the previous version plus
one, with the reason `The user requested <operation>.`

After the graph returns, the function raises `ApplicationTaskError` if
the task recorded an error. On success it returns:

```text
specialist result fields + plan_detail
```

This explains a result that can otherwise look contradictory:

> GET journey still says `eligible`, but the visible plan is now
> “Check the document checklist → Prepare a draft and wait for your approval”.

The eligibility status was preserved. The current plan describes the
latest requested work. Approval/submission state lives in the draft
record, not in a replacement eligibility verdict.

### 7.5 `document_agent`: read and report

Inside `build_journey_graph`, `document_agent`:

1. Reads the typed task.
2. Requires an `eligible` saved candidate verdict and a loaded rule
   package for the scheme.
3. Calls the separate MCP `check_documents` tool.
4. Stores the result in `document_assessments[scheme_id]`, preserving
   assessments for other schemes.
5. Reports the assessment status to the supervisor.

A failed MCP call records a safe 502 task error and reports `tool_error`.
This specialist never calls `mock_portal`.

### 7.6 `application_agent`: the workflow's portal writer

The specialist builds portal arguments using the saved conversation ID.
For create, edit, approve and reject it also requires that the approval
graph exists, which means a checkpointer was supplied.

For edit/approve/reject/submit, it reads the portal record first and
compares the current revision. For approve/reject/submit it compares the
fingerprint too.

Then it applies the action-specific checks:

| Action | Important specialist checks before the portal mutation |
|---|---|
| Create | Saved eligible verdict, loaded package, valid current profile, fresh MCP eligibility result |
| Edit | Current revision, not submitted, saved eligible verdict, draft profile/package equal current profile/package |
| Approve | Current exact pair, not rejected/submitted, current eligible profile/package, fresh MCP eligibility result, saved checklist matches task |
| Reject | Current exact pair, not submitted; does not require the profile to remain eligible |
| Submit | Current exact pair, portal says approved, current eligible profile/package, fresh MCP eligibility result, saved checklist matches task |

The rule recheck is deliberately **not** performed for the two-field edit.
Edit still compares the saved profile and package with the current ones.
Creation, approval and submission call `eligibility_tool`, whose default
implementation uses MCP `evaluate_eligibility`. No LLM decides the result.

For creation, the specialist supplies the current profile, package version
and deciding rule IDs to the portal. For approve/submit, it verifies that
the scheme and reported document map match the exact record being acted on.

Finally:

- Create/edit writes the portal, then opens the approval pause.
- Approve/reject resumes the approval pause, then writes the portal.
- Submit writes the portal only after its approval checks.
- Every completed action reports back to the supervisor.

The report statuses are `awaiting_approval`, `approved`, `rejected`,
`submitted` and `deleted`, depending on the operation.

**Do not read “plan step done” as “human review complete”.** After creation
the application specialist has finished *preparing and pausing*. Its plan
step is `done`, while the draft is still unapproved in a separate approval
thread.

### 7.7 What happens after a profile correction?

Phase 3's `correct_journey_answer` remains a multi-scheme correction path.
It clears current candidate/full results, application task fields and
`document_assessments`, then restarts intake/rule checks for the candidates.

Existing portal drafts are not automatically deleted or rewritten.
If the changed facts rule a scheme out, approval is blocked by the missing
current eligible verdict. Even if the new facts remain eligible, a draft
whose profile snapshot differs from the current profile is refused for
edit/approve/submit. The person must create and review a new draft.

That is stricter than silently updating the draft underneath an approval.

---

## 8. Step 5: connect HTTP requests to the specialists

**Files:** `src\api\applications.py`, `src\api\app.py`,
`src\mcp_servers\saathi_mcp_server.py`

### 8.1 Startup: connect once, not once per click

`lifespan` in `app.py`:

1. Loads and validates rule packages.
2. Opens the journey SQLite checkpointer at
   `SCHEME_SAATHI_CHECKPOINT_DB` (default `data/runtime/journey.sqlite3`).
3. Selects the separate application database path and passes it to the
   MCP child process.
4. Starts the MCP server with the API's Python executable.
5. Builds the journey graph using that client, packages and checkpointer.
6. Keeps them available on `application.state` until shutdown.

`saathi_mcp_server.py` registers eligibility, search, documents and
applications on one MCP server. The document and portal tools are distinct
even though they share a server process. Registration alone does not give
them separate OS-level privileges.

### 8.2 The HTTP request contracts

The models in `src\api\applications.py` inherit
`StrictApplicationModel`, which forbids extra fields.

| Model | Required / default input |
|---|---|
| `DocumentAssessmentRequest` | `scheme_id`; `documents` defaults to `{}` |
| `DraftCreateRequest` | `scheme_id`, `documents`; default synthetic reference and district |
| `DraftEditRequest` | Positive `revision`, `applicant_reference`, `district` |
| `DraftApprovalRequest` | `action` of approve/reject/submit, positive `revision`, 64-character `fingerprint` |

The API does not accept a replacement profile or package version inside
an application-create request. Those values come from the saved backend
state. The edit request does not accept arbitrary payload changes.

The fingerprint input model checks its length; the subsequent equality
check against the stored digest is what binds the decision to the record.
Do not describe the input model as performing a cryptographic signature
verification.

### 8.3 Routes and their actual work

All paths below are relative to `/api/v1/journey/{conversation_id}`:

| Method and suffix | Handler | Work |
|---|---|---|
| `POST /documents` | `assess_application_documents` | Check saved eligible state, dispatch `check_documents` |
| `POST /drafts` | `create_application_draft` | Check saved eligible state/package, dispatch creation |
| `GET /drafts` | `list_application_drafts` | Read the conversation's portal drafts |
| `GET /drafts/{draft_id}` | `get_application_draft` | Read one portal draft scoped to the conversation |
| `PUT /drafts/{draft_id}` | `edit_application_draft` | Read/check record and profile/package, dispatch allowlisted edit |
| `POST /drafts/{draft_id}/approval` | `update_application_approval` | Check exact pair and action conditions, dispatch approve/reject/submit |
| `DELETE` with no suffix | `forget_journey` | Delete mock data and checkpoint threads |

`_application_state` reads the journey snapshot and requires a saved
eligible verdict for the selected scheme plus a valid profile.
`_dispatch_application_task` translates `ApplicationTaskError` into an
HTTP error with the specialist's safe status/message.

The write path is:

```text
HTTP route
  -> _dispatch_application_task
  -> run_application_task
  -> supervisor
  -> document_agent when the plan requires it
  -> supervisor
  -> application_agent
  -> MCP mock_portal
  -> supervisor -> response
```

The read path is intentionally shorter:

```text
GET route -> call_application_tool(..., "mock_portal", read action)
          -> saved draft response
```

Therefore “application agent is the only writer” means the **workflow's
portal mutations** are routed through that specialist. It does not mean
every HTTP handler is forbidden to call the portal at all. Listing and
reading drafts are direct, read-only MCP calls.

`call_application_tool` wraps client-call failures in `MCPToolError`,
rejects an error result, requires structured content, and requires that
content to be a dictionary. It does not validate every possible response
field against a dedicated response model.

### 8.4 The request bodies in our example

The create request is simply:

```json
{
  "scheme_id": "IGNWPS-MH",
  "documents": {
    "identity_proof": "available",
    "age_proof": "available",
    "widow_status_proof": "available",
    "bpl_proof": "available"
  }
}
```

After reading the returned draft, the client sends a decision body with:

```text
action:      "approve"                 (or "reject" / "submit")
revision:    the displayed revision
fingerprint: the complete returned 64-character digest
```

The draft ID is in the URL. The client must not manufacture a digest or
send only the shortened fingerprint shown on screen.

For approve/submit, `update_application_approval` gets the scheme and
document statuses from the stored record, not from a new checklist in the
decision body. It checks the current profile/package before dispatch.
The specialist rechecks the rule result before the write.

### 8.5 Errors are not eligibility verdicts

| Situation | Expected boundary |
|---|---|
| Invalid HTTP request shape/value | FastAPI/Pydantic validation, normally 422 |
| Missing conversation for a normal application task | 404 |
| Draft not found under the supplied conversation | 404 from the draft read helper |
| Stale revision/fingerprint or missing approval | 409 |
| Incomplete demo checklist before a dependent action | 409 |
| Main interview still waiting for an answer | 409; finish the interview first |
| Checklist/portal MCP failure in specialist execution | Safe task failure, generally 502 |

These are representative paths, not a claim that every exception from
every storage or checkpoint operation is uniformly translated. The code
has specific error handling, not a comprehensive failure-recovery layer.

### 8.6 Forgetting a session

`forget_journey` lists the conversation's drafts, routes `delete_journey`
through the application specialist, deletes approval checkpoint threads
for revisions 1 through each draft's current revision, and deletes the
main journey thread.

Deletion is allowed even if the interview is paused. It is a cleanup
sequence across storage operations, not one atomic transaction and not a
claim of forensic erasure from SQLite journals or backups.

---

## 9. Step 6: show the saved flow in Streamlit

**Files:** `src\ui\api_client.py`, `src\ui\app.py`

### 9.1 The UI does not run the graph

The application helpers in `api_client.py` are:

| Helper | HTTP operation |
|---|---|
| `assess_documents` | POST checklist metadata |
| `list_application_drafts` | GET saved drafts |
| `create_application_draft` | POST scheme and checklist |
| `edit_application_draft` | PUT revision and the two editable fields |
| `decide_application_draft` | POST action, revision and complete fingerprint |

They use `_application_request`, which decodes the JSON dictionary and
raises `ApplicationApiError` for handled HTTP, connection and decoding
failures. The screen catches that error and shows its message rather than
running backend code locally.

The older fixture-era local approval machinery is not the authority for
the new API-backed flow. `render_application_flow` uses the returned
backend draft's `approved`, `rejected` and `receipt_id` fields.

### 9.2 Where the application panel appears

`render_application_flow(scheme_id, text)` is called after an eligible
result in the single-scheme interview and per eligible scheme in the
multi-scheme results. The widow-pension result screen also calls it for an
eligible result. The function returns immediately if there is no
conversation ID.

An information-only or negative result must not be treated as permission
to prepare a draft. The API and specialists enforce this even if someone
bypasses the intended screen.

### 9.3 No draft yet: load, report, recheck, prepare

The panel first loads saved drafts once for the current conversation and
keeps a dictionary keyed by scheme ID.

When there is no selected draft for that scheme:

```text
Load demo document checklist
    -> assess_documents with no statuses
    -> unknown statuses shown

Choose unknown / available / missing / mismatch for each demo item
    -> Update checklist
    -> assessment returned by backend

assessment.status == checklist_complete
    -> Prepare synthetic draft button appears
    -> create_application_draft
    -> returned draft stored in UI state
```

Changing a selectbox is not itself a backend assessment. The update
button sends the report. When preparing a draft, the screen sends the
current selections again; the backend checks them again rather than
trusting the previous button visibility.

For our example, `bpl_proof="missing"` leaves draft preparation blocked.
Only after all reported demo items are `available` does preparation pass.
That is still not document authentication.

### 9.4 A saved draft: review before action

The panel displays the reference, district, scheme, revision, profile,
document items and synthetic declaration. It shows a shortened
fingerprint for readability, while the client sends the full digest.

The available branches are:

| Draft/UI condition | What the person sees or can do |
|---|---|
| Normal unsubmitted draft | Edit, approve or reject |
| Edit mode | Reference/district inputs and save-new-revision action |
| Approved, not submitted | Submit approved draft to mock portal |
| Rejected | Rejection notice and edit/reopen option |
| Receipt present | Mock receipt success message; normal mutation controls are not shown |

Approval does not automatically submit. The person makes a second,
explicit submit action.

Reopening a rejected draft enters edit mode. Saving creates a new
revision, resets rejection and requires fresh approval; it does not
silently approve the rejected content.

“Start a new draft using current answers” removes the selected draft
from the UI dictionary and resets its local checklist/edit state. It
does **not** delete the old portal draft. A subsequent create request
produces another saved record.

### 9.5 Why `st.rerun()` and session state matter

Streamlit reruns the script after interactions. A plain local variable
would not be a reliable place to keep the current returned draft.

The new flow uses:

- `application_drafts`: selected saved record per scheme;
- `application_drafts_loaded_for`: which conversation's records were loaded;
- `application_flow`: per-scheme assessment, error and edit-mode state;
- `journey_plan_detail`: the plan to show after an action.

`save_application_progress` copies a returned `plan_detail` into
`journey_plan_detail`. Each successful application action can therefore
refresh the plan display without replacing eligibility results.

`save_journey` restores `application_flow` from
`JourneyResponse.document_assessments`. Existing URL-based journey
restoration supplies the saved conversation after refresh, and draft
listing supplies the portal records.

These are two different reads:

```text
GET journey -> eligibility, current plan, saved document assessments
GET drafts  -> draft contents, revision, approval/rejection, receipt
```

The portal can store multiple drafts for a scheme. Because the screen
builds a scheme-keyed dictionary from creation-ordered records, the later
record for that scheme is selected on reload. It is not a draft-history
browser, and the once-per-conversation cache is not live multi-tab
synchronization.

### 9.6 The current language limit

The surrounding UI has the existing English/Hindi/Marathi translation
pattern, but the new application panel currently contains hard-coded
English labels, captions and messages. The `text` argument does not make
those new strings translated. Do not claim Phase 4's checklist/approval
panel is fully localized or manually accepted in all three languages.

---

## 10. Follow one full journey, including an edit and a rejection

This sequence joins the pieces above. It is a teaching trace, not a claim
that a human has completed the pending browser acceptance checks.

### Part A: establish the result and notice missing metadata

1. Start/evaluate the synthetic `IGNWPS-MH` profile from Section 3.
   The intake/eligibility plan runs, and the MCP-backed deterministic
   eligibility tool returns `eligible`.
2. Open the checklist. Empty metadata gives `unknown_items`.
3. Report three available items and `bpl_proof="missing"`.
   The assessment is `missing_items`.
4. If a caller tries to create a draft anyway, its plan runs the document
   specialist, then skips the application specialist. The task returns
   a conflict. There is no draft-creation portal call.
5. Report every demo item available and update. The result is
   `checklist_complete`. No actual document has been inspected.

### Part B: create revision 1 and pause

6. Choose “Prepare synthetic draft”. The route dispatches `create_draft`.
7. Supervisor → documents → supervisor checks the metadata again.
8. Supervisor → application checks the saved profile/verdict/package and
   obtains a fresh deterministic eligibility result through MCP.
9. The portal saves draft D at revision 1, fingerprint F1. The outer record
   says `approved=False`, `rejected=False`, `receipt_id=None`.
10. The application specialist starts the approval thread for
    `(conversation, D, 1)`, which pauses at `interrupt()`.
11. It reports `awaiting_approval`. The main plan ends with both steps
    `done`; the separate review remains waiting.
12. Trying submit now is refused because the exact draft is not approved.

### Part C: approve, then edit

13. The person reviews revision 1 and clicks approve. The client sends
    revision 1 and F1.
14. The API checks that pair, takes document metadata from D, and dispatches
    `approve`. The document specialist checks the saved checklist.
15. The application specialist checks the pair/profile/package again and
    rechecks eligibility. It resumes the revision-1 approval gate with
    the decision, then asks the portal to record exact approval.
16. The returned record now says `approved=True`, but still has no receipt.
17. Instead of submitting, the person edits the reference to
    “Synthetic applicant 2” and district to “Nashik”, then saves.
18. The backend checks the current revision/profile/package. The portal
    saves revision 2, clears approval and rejection, and recalculates F2.
    The application specialist pauses the revision-2 approval thread.
19. A stale approve or submit request carrying revision 1/F1 is refused.
    Approval of the old view cannot approve revision 2.

### Part D: reject, reopen, approve and submit

20. The person rejects revision 2 with F2. Its approval gate resumes with
    that rejection; the portal marks it rejected and keeps no receipt.
21. Submission is refused. Rejection did not authorize anything.
22. The person chooses edit/reopen, changes the two editable fields as
    needed and saves revision 3. Approval is still false, rejection is
    cleared, and a new review pause is saved.
23. They review and approve revision 3/F3. The current checklist and rules
    are checked before exact approval is stored.
24. They explicitly submit revision 3/F3. The workflow rechecks the current
    profile/package, rules and saved checklist; the portal verifies exact
    approval and stores a mock receipt R.
25. Repeating that valid submit returns receipt R again rather than making
    another receipt. The workflow's current-state checks still apply to
    repeated HTTP submissions.

### The state changes in one small table

Here F1/F2/F3 and R are explanatory placeholders, not actual request
values. A no-change edit can keep the same fingerprint even while the
revision increases.

| Point | Revision | Approved? | Rejected? | Receipt? |
|---|---|---|---|---|
| Created | 1 | No | No | None |
| Approved | 1 | Yes | No | None |
| Edited | 2 | No | No | None |
| Rejected | 2 | No | Yes | None |
| Edited/reopened | 3 | No | No | None |
| Approved again | 3 | Yes | No | None |
| Submitted | 3 | Yes | No | R |
| Same valid submit repeated | 3 | Yes | No | Same R |

If the profile or loaded package version changes before approval or
submission, stop this sequence and create a new draft from the current
eligible state. The old draft is not silently made current.

---

## 11. Tests: what they establish, layer by layer

The tests are most useful when read as examples of a boundary being
enforced. Do not treat a passing unit test or mocked UI test as proof that
the whole browser/API journey has been accepted manually.

### 11.1 Tool and graph tests

**File:** `tests\test_application_tools.py`

The graph fixture uses a `MemorySaver`, a test-owned SQLite application
database, the real local metadata/portal functions and an injected
deterministic eligibility function. It records application tool calls.
It does not need a real model request or an MCP subprocess for these cases.

| Test | What its assertions demonstrate |
|---|---|
| `test_document_check_never_calls_demo_items_official` | Empty metadata becomes unknown; demo-only status and the non-official warning are present |
| `test_unknown_scheme_requirements_block_draft` | The checker returns `requirements_unverified` and no requirements for an unknown scheme; this test does not itself attempt portal creation |
| `test_submit_requires_approval_and_is_idempotent` | Direct portal submit is refused before approval; approved repeated submit returns the same receipt |
| `test_edit_invalidates_approval_and_old_fingerprint` | Edit increments revision and clears approval; another journey cannot read that draft by ID alone |
| `test_incomplete_documents_cannot_create_a_draft` | Direct portal creation refuses an incomplete demo checklist |
| `test_supervisor_hands_off_to_both_agents_and_persists_approval` | Handoffs pass through the supervisor, approval has a saved interrupt, eligibility survives the task, approval resumes the gate, repeated submit is stable and workflow edit after submit is refused |
| `test_document_agent_blocks_application_without_portal_access` | Missing/unknown/mismatch reports skip the application step and make no portal call |
| `test_edit_and_rejection_keep_old_approval_unusable` | Stale submit is refused after edit; rejection clears approval, has no receipt and resumes its review pause |
| `test_application_agent_rechecks_rules_before_writing` | A changed ineligible profile blocks creation before a portal write |
| `test_document_tool_failure_reports_back_without_writing` | A failed checker gives a 502 task error and failed/skipped steps, not a portal write |
| `test_correction_after_drafting_rechecks_candidates_and_clears_checklist` | Correction rechecks the candidate, clears saved assessments and prevents approval when the current result is negative |
| `test_application_actions_do_not_replace_waiting_interviews_but_allow_deletion` | A pending interview blocks application creation but not cleanup |

Some test names describe a broad concern while individual assertions cover
a narrower slice. For example, the direct edit test checks revision and
approval invalidation; the graph and API tests supply the explicit stale
request rejection checks. Read them together rather than assuming one test
covers every failure mode.

### 11.2 HTTP integration test

**File:** `tests\test_api_applications.py`

`test_synthetic_application_requires_exact_approval` uses FastAPI
`TestClient`, the application's lifespan, a spawned MCP server, and
test-owned checkpoint/application databases.

It follows a synthetic evaluation through:

```text
eligible -> complete checklist -> create -> restore/read
         -> submit refused
         -> edit to revision 2
         -> stale approval refused
         -> approve revision 2
         -> submit -> repeated submit returns same receipt
         -> forget -> journey missing and draft list empty
```

It also checks plan specialists and that document/application actions do
not overwrite the saved eligibility status.

This exercises the actual route-to-MCP integration without asking a
hosted model to decide anything. It is not a real government-portal test,
a load test or an exhaustive validation/error matrix.

### 11.3 Screen tests

**File:** `tests\test_ui_app.py`

`test_document_action_updates_supervisor_plan_and_restores_checklist`
uses Streamlit `AppTest` with mocked API helpers. It restores a saved
assessment, checks that the checklist item appears, clicks the load
action and checks that the returned document plan is shown.

The existing refresh tests
`test_refresh_restores_saved_conversation_from_url` and
`test_refresh_with_forgotten_conversation_cleans_url` cover the surrounding
conversation-restoration behavior. They are not exhaustive tests of all
new draft-edit/approval buttons against a running backend.

### 11.4 Focused commands for a later code change

These are reference commands from the repository root, not commands run
again for this documentation-only change:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -x tests\test_application_tools.py tests\test_api_applications.py tests\test_ui_app.py
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m pytest -q -x
```

The recorded 3 November result is the existing local full-suite result:
**196 passed**, with local compilation passing. It does not establish
GitHub validation for a pushed commit.

### 11.5 Manual browser gates are still open

The plan still requires a person to check:

- Missing document metadata is listed for an eligible scheme.
- Approve, then submit, records a mock receipt through the running UI.
- Editing after approval makes the old approval unusable.
- Reject leaves the draft unsubmitted.

Refresh behavior, user-facing warnings and the two-scheme experience are
also worth inspecting during that walkthrough. No box is checked here;
automated evidence and manual acceptance remain different things.

---

## 12. Common mistakes and the current limits

### Mistakes to avoid when reading or extending this code

| Mistake | Correct interpretation |
|---|---|
| “All documents are valid” | All configured demo metadata items were reported available |
| “The document checker found a mismatch” | The user reported `mismatch`; no document content was inspected |
| “The model approved eligibility” | Deterministic MCP rules decided the mock verdict |
| “The application plan is done, so the person approved” | The specialist may only have saved a draft and opened a separate review pause |
| “The UI disabled submit, so the backend is protected” | API, specialist and portal must still refuse missing/stale approval |
| “A hash is enough to authorize every later version” | Both revision and payload fingerprint are checked; every saved edit clears approval |
| “Approve means submit” | They are separate explicit actions |
| “One transaction covers the whole workflow” | Portal transactions and graph checkpoints are separate operations |
| “Conversation scoping is user authentication” | No authenticated identity/ownership guarantee is established by these IDs |
| “A mock receipt proves a government submission” | It proves only a local mock record was created |

### What Phase 4 does not yet claim

1. **Official document requirements.** Only two synthetic demo checklists
   are configured. They need separate source review before being used as
   official guidance.
2. **Document or identity verification.** No uploads, OCR, authenticity
   checks or identity validation are implemented by this flow.
3. **Production authorization.** Draft queries are scoped to a conversation
   and draft ID, but the code shown here does not establish authenticated
   users, role permissions or a production security boundary.
4. **Cross-store crash recovery.** Portal writes and graph pauses/resumes
   are not one transaction. Failure between them can leave partial
   progress. Idempotent mock submit is narrower than complete exactly-once
   execution of the whole graph.
5. **Concurrent-session correctness.** SQLite serializes individual portal
   actions and revisions detect stale writes, but that is not a proof of
   safe overlapping graph invocations, multi-tab synchronization or
   distributed concurrency.
6. **A complete immutable audit trail.** The portal keeps the current
   payload/revision and approval fields. Approval checkpoints provide
   workflow state, not a complete signed, tamper-proof application history.
7. **Automatic draft migration.** Corrections invalidate current context
   for an old draft; they do not rewrite it or auto-approve a new one.
8. **Full localization or UI acceptance.** The new panel has English-only
   strings, and the manual browser gates remain pending.
9. **Completed phase gates or deployment.** Earlier sign-offs remain open.
   Local automated success does not resolve them, and no deployment is
   implied.

### A short study exercise

Without changing code or calling a model, trace these questions through
the named functions:

1. Why does a `missing_items` assessment mark documents `done` but
   application `skipped`? Read `advance_plan`.
2. Which state fields survive a document action? Read
   `run_application_task`, then `JourneyState`.
3. Where is the approval pause stored after draft creation? Read
   `application_gate_thread_id` and `pause_for_application_approval`.
4. What rejects revision 1 after an edit creates revision 2? Follow the
   HTTP handler, `application_agent` and `_portal_action`.
5. What happens if a portal approve write fails after the gate resumes?
   Compare the operation order rather than assuming atomicity.
6. Which information returns after refresh from GET journey, and which
   comes from GET drafts? Read `save_journey` and
   `render_application_flow`.

The main lesson is simple: **reported checklist completeness, mock
eligibility, exact human approval and mock submission are four different
states**. Phase 4 connects them through explicit plans, saved revisions
and checked transitions instead of letting one convenient flag stand
for all of them.
