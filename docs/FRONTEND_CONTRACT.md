# Frontend prototype contract

> **Historical first-slice contract, not the current API or completion status.**
> The sections below preserve the original frontend-only demonstration.
> Since `770bc5c`, the UI uses backend eligibility and saved mock drafts with
> server-side approval; it is not limited to this fixture simulation.
> Current routes/target invariants are in
> [the end-to-end plan](END_TO_END_IMPLEMENTATION_PLAN.md), and remaining
> acceptance work is in [the phase-wise plan](PHASE_WISE_IMPLEMENTATION_PLAN.md).
> Follow its G03/G06–G10 gates for stale approval, unknown eligibility,
> document mismatch, referral, language parity and Citizen/CSC consent.
> The additive Phase 2 request/response contract is recorded below; the
> historical first-slice description remains unchanged.

Status: provisional; Roles 1, 3 and 4 must review the later domain and service
contracts.

## Phase 2 interview contract (2026-11-04)

The existing `POST /api/v1/journey` interview request remains compatible.
Optional `profile_description` (up to 1,200 characters), `locale` (`en`, `hi`,
`mr`), `mode` (`citizen`, `csc`) and `citizen_present` fields extend it. A CSC
interview is rejected unless the citizen is declared present. The operator may
assist, but the citizen confirms profile facts and remains the only person who
can approve an exact application draft.

When the existing `OPENROUTER_API_KEY` is configured, versioned bounded agent
actions may propose a dependency-checked plan and typed facts. Only code may
validate profile values; every proposed fact is shown for explicit confirmation
before it changes the profile. Existing confirmed facts cannot be overwritten
by an extraction proposal. If a model action, schema, permission or budget check
fails (or no key is configured), the journey keeps its deterministic C0 planner
and code-selected questions. Neither path delegates eligibility or approval to
a model.

The response adds `locale`, `mode`, a localized mode acknowledgement, the
agent fallback status, durable conversation counters and a bounded list of
scrubbed trace events. Trace events contain action names, model/config version,
counts and timings, never prompts, free text, proposed values or chain-of-thought.
The Streamlit interface still calls the backend only through
`src/ui/api_client.py`. Model calls are not made by automated tests.

## Phase 3 discovery and correction contract (2026-11-04)

Registry-backed interviews also accept `candidate_scheme_ids`. Questions are
selected deterministically from the loaded rules, preferring the missing
registered input shared by the most unresolved candidates; ties retain candidate
and rule order. Only the same ID in the same pinned registry shares an answer,
never a similar question label. All interviews use the same bounded models;
a model's proposal is only saved after the person confirms it. Synthetic
development bundles are explicitly injected only in offline tests.

Corrections accept registered fact IDs and use their exact number, integer,
date, boolean, finite-choice or explicit-unknown parser. Decimal values retain
the tagged `$decimal` checkpoint/MCP representation; the correction request
continues to send the user's exact answer text. Additive `fact_questions` maps
correctable IDs to localized registry question labels, without answer values.

Development bundles remain on typed intake even when they explicitly map some
facts to legacy profile fields; only loader-validated pinned compatibility
pilots select legacy-only intake. Proposed answers and corrections are checked
against the complete typed store and mapped profile before a resume or
invalidation write. A conflicting date answer reissues the question safely,
without saving an invalid fact or losing the ability to retry.

Interviews use bounded confirmed-fact discovery, using only confirmed registered
facts. Discovery runs before choosing the next question, including after
corrections, and can introduce more candidate schemes. Existing supported language/limit arguments, durable search attempts,
information-only results and same-conversation limits remain unchanged.

Saved conversations bind the complete loaded registry (including meaning,
scope, units, periods and review metadata), bundles and rule contents. A changed
or withdrawn dependency returns a safe localized `invalid_input` review notice,
clears exposed verdicts/reports and cancels unsubmitted approvals. Answers remain
saved, but are not reinterpreted. The persisted review latch survives restart and
A-to-B-to-A; returning to old files cannot restore approval. Reconfirmation in a
new conversation is required; automatic migration is not provided. Old legacy
checkpoints remain usable; pre-binding typed checkpoints require this same
explicit review rather than silently accepting unpinned meanings.

Discovery still uses the existing search tool and supported arguments only.
The synthetic multi-bundle test injects clearly labeled search results through
the actual API/graph; it is not evidence of a corpus hit or live retrieval recall.
Generic development-only forms are covered by the revised Phase 4 contract below.

The eligibility specialist uses `check_candidate`, `handoff_verdict`,
`request_clarification` and `refer_for_help` under its own bounded allowlist.
Its observations and typed handoffs cannot replace the deterministic engine's
verdict. A failed model/permission/budget check returns an explicit unchecked
candidate, never a fabricated result; unconfigured models use the C0 engine path.

Responses additionally expose `dependency_version`, `search_calls`,
`discovery_notices` (code-owned status codes), localized `discovery_messages`,
typed `discovery_events` (code, cumulative attempts, added/processed IDs and
unprocessed IDs), and `unprocessed_candidate_ids`. At most 20 distinct IDs are
processed; overflow is reported, not silently dropped. Four conversation search
attempts include retries. Discovery uses only confirmed category/age query
hints and explicit language selection; the current schema does not support
invented state/gender facts or age/gender retrieval filters.

`POST /api/v1/journey/{conversation_id}/corrections` works for single and shared
interviews. An explicit unknown clears the fact rather than making it false.
`known_fact_names` still means non-null facts; `correctable_fact_names` also
includes explicitly skipped/unknown answers, allowing their later restoration.
Profile corrections revoke persisted approval of every unsubmitted conversation
draft even when the profile stays eligible or returns to an earlier value.
Document-report and observed rule changes also revoke affected approvals.
The portal's monotonic dependency versions and transaction checks reject stale
or concurrent writes; persistence failures keep writes closed pending
reconciliation. Submitted receipts remain available as history.

Portal draft/status responses expose `stale`. The UI invalidates its draft
cache after corrections/version changes, reloads from the API, displays a
localized notice and offers no approval/submit controls for stale drafts.
Fresh drafts require fresh exact human approval. Discovery/error/referral
notices work in English, Hindi and Marathi. Budget reservations and per-fact
attempts survive failed nodes, corrections and same-ID SQLite restart.
Independent, manual, language and approved live-model acceptance remain open.

## Phase 4 document and approval contract (2026-11-04)

The UI submits user-entered synthetic document statuses, names and dates to
the API. Comparisons use confirmed synthetic profile values in deterministic
code; the app does not read or authenticate documents, perform OCR, or claim
that the demo checklist is an official requirements source. A discrepancy
requires correction and recheck or human referral before a draft can proceed.

The scheme checklists are read through one versioned, typed file-backed
loader shared by both checklist MCP tools. Current files are explicitly
demo-only, while source-backed use remains fail-closed until reviewed evidence
and a human approval record match the exact checklist and evidence content
fingerprints. Missing or invalid data is shown as unverified, never as an empty
official list. The UI renders required groups, any-one alternatives, supported
conditions, active version, trust state and approved-source citations in
English, Hindi and Marathi.

Registered checklist conditions and fact-mapped mock form fields must belong
to the actual active scheme bundle's `fact_ids`, with compatible registry
definitions and value types. A globally registered fact, including one already
confirmed for another scheme, is not permission to use it. Invalid mappings
fail loading/readiness, supported publication and MCP/portal revalidation.
Additional registered form facts require explicit bundle membership; only
trusted development fixture injection permits novel bundles in tests. These
checks do not approve pending source, fact, question or privacy metadata.

Allowed derived values (currently age on application date) are resolved from
confirmed typed inputs using the trusted fact store, never supplied by a client.
Every derivation dependency must also belong to the scheme bundle. Missing
dependencies leave document conditions unknown and required form values missing;
the birthday boundary uses the same deterministic calculation as eligibility.

Bounded document and application specialists select only actor-allowlisted
actions. The application specialist can write drafts to the mock portal, but
only a person can approve the exact current revision. Model actions cannot
approve, reject or create consent. The review remains bound to current profile,
document report and rule versions plus the draft fingerprint; corrections or
changed reports invalidate approval, including an A-to-B-to-A correction.
Checklist/evidence changes are re-read by the portal for current create,
approval and submission actions. Journey refreshes also compare and rebind
saved reports, marking outdated reports and staling unsubmitted drafts, while
an already-submitted exact retry keeps its saved receipt.

Approval has a provisional 15-minute expiry, pending team ratification. The
backend keeps authorization internal, consumes it once on submission, and
returns the stored receipt for an identical retry. Malformed, expired, stale,
altered or replayed authorization cannot submit another draft. Portal writes
use a transaction; process-kill and multi-worker recovery guarantees still
require operational acceptance.

This local demonstration does not authenticate a person or verify that the
operator is the citizen. A conversation identifier is not proof of identity;
use synthetic data only. The approval pause records a human action in the demo,
not verified citizen consent.

Possession of the conversation UUID acts as a demo capability for its HTTP
routes, including the human decision route; it is not authentication. Agents
cannot select the approval/rejection actor or call that route as a tool.

The shared ceiling remains eight model calls per conversation, including
reservations saved before failed calls. When model availability or that ceiling
blocks a document/application specialist, code may perform the already-selected
request once using a reserved remaining tool allowance. Denied or malformed
model actions do not trigger recovery. Eligibility, current dependencies and
exact human approval are still checked; exhaustion never manufactures consent.
The model/token/step ceilings remain 8 calls, 12,000 tokens and 12 steps.
The 24-action allowance includes deterministic checklist rechecks, recovery
after a lost draft response and receipt retries; it does not permit more paid
model calls and persists across requests/restarts.
A completed portal result is returned even if the later model handoff fails.
Exact create retries reuse the stored current draft (including after edits),
scoped to the conversation, scheme, original payload and dependency versions;
changed inputs/dependencies require a fresh unapproved draft. Submission retries
return the existing receipt rather than submit again.

Forget deletes the conversation's journey, revision approval pauses, its
budget record (LangGraph `Store`, namespace `("budget",)`), portal drafts and profile/document/rule
dependencies without deleting another conversation. Read-only draft/status
requests do not recreate those dependency rows.
When backups are enabled, a 204 also follows refresh of the current backup;
an incomplete deletion or backup refresh returns 503 and should be retried.

The synthetic APY eligibility check returns `need_more_information` without a
verdict for application dates before 1 October 2022, pending review of the
historical rules. It requires the application date before issuing any APY
verdict.

Document checks, draft creation/listing, edits and approval continue through
the additive `/api/v1/journey/{conversation_id}` routes. On refresh the UI
reloads draft status from the API and removes approval/submit controls for stale
drafts. User-facing mismatch, referral, stale and expiry notices follow the
English/Hindi/Marathi translation pattern, including rejection, edit/reopen,
synthetic applicant-reference and receipt labels.

The first deployed frontend is a synthetic demonstration. It does not evaluate
eligibility, collect real personal data, contact a government service or submit
an application.

## Initial shell

The first revision provides:

- a persistent synthetic-demonstration warning;
- English, Hindi and Marathi presentation;
- an application version supplied through `APP_VERSION`;
- a container health endpoint supplied by Streamlit.

## Fixture-backed journey

The first policy fixture uses the Maharashtra implementation of the Indira
Gandhi National Widow Pension Scheme. Policy metadata comes from the official
Social Justice & Special Assistance Department page collected on 28 October
2026. The policy interpretation remains a draft until the assigned domain,
orchestration and control owners review it.

Seven synthetic development scenarios cover the published widow, age and BPL
conditions. Three representative scenarios are visible in the UI; none are
held-out evaluation cases.

## Invariants

1. The warning must remain visible in every language.
2. No secrets or real personal information may be placed in the image.
3. The frontend must not claim to determine eligibility.
4. Future fixture responses must include clause, source URL and collection date.
5. Future backend state must remain outside Streamlit session state.
6. Unverified document requirements or exclusions must not be invented.
7. Frontend approval applies only to the exact synthetic draft fingerprint.

## Approval simulation

The eligible development scenario can prepare a synthetic application draft.
The frontend calculates a SHA-256 fingerprint from the full draft. Editing any
field changes the fingerprint and invalidates the earlier approval.

This describes the historical frontend-only prototype. The current backend
flow supplies server-side exact-draft authorization and a mock-portal receipt,
but remains a synthetic demonstration and does not contact a government
service.

## Replacement path

The next frontend revision will use explicitly synthetic fixture responses.
Those responses will later be replaced by versioned FastAPI contracts without
changing the user journey.
