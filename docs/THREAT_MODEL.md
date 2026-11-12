# Threat model: Scheme Saathi

Owner: Role 5 (Tools, control & security), Vivian Fernandes. Checked directly
against the running code on `main` as of 2026-11-09, not against intent or
design docs alone. Covers the 4 MCP servers, the permission guard, the
approval gate, and the specialist agents. Written as the capstone guide
requires: assets, applicable threats, current mitigations, and open gaps.

## Assets

| Asset | Why it matters |
|---|---|
| Household profile facts (`HouseholdProfile`) | Decide real eligibility outcomes; some are sensitive (age, widow status, income-adjacent facts). |
| Scheme rule packages (`src/rules/packages/*.json`) | The actual decision logic. If these are wrong or tampered with, every verdict downstream is wrong. |
| Draft applications and the mock portal DB | Synthetic, but structurally stand in for a real government submission; the design must hold even though the data doesn't. |
| Approval tokens | A one-time permission slip; if these could be forged or replayed, the approval gate is meaningless. |

## System summary

Four MCP servers (`rule-engine`, `schemes-kb`, `doc-check`, `mock-portal`)
sit behind one permission guard (`ServiceClientRouter` /
`service_routing.py`). Every tool call carries an **actor** badge
(`intake`, `eligibility`, `documents`, `application`, `human_approval`,
`session_cleanup`, `dependency_control`, `api_read`), assigned by which step
of the LangGraph journey is running — never by the model, never from tool
arguments (`service_routing.py` explicitly rejects an `actor`/`caller`/
`trusted_actor` key in any call's arguments). The approval gate
(`application_gate.py`) pauses with `interrupt()` on a checkpoint keyed by
`conversation_id + draft_id + revision`, so an edited draft is structurally a
different approval target, not a flag that can be left stale.

## Where untrusted text actually reaches a model (checked in code, not assumed)

This is the finding that should drive the rest of this document, and it
differs from a naive reading of the architecture:

- `eligibility_agent.py` and `document_agent.py` pass only
  `{"scheme_id": ...}` as model context. Scheme passage text and document
  field values are never shown to any model — they're compared and decided
  entirely in deterministic code. **This closes off the indirect-injection
  vector the capstone's own L15 lecture uses as its running example**
  (a hidden instruction inside a document or a retrieved passage): there is
  no code path today where that text reaches a model at all.
- `doc-check`'s `check_documents` tool is explicitly metadata-only — it does
  not inspect or authenticate document contents (confirmed in
  `MCP_TOOL_INVENTORY.md` and in `src/mcp_servers/tools/documents.py`). No
  OCR, no content extraction. The classic "hidden white text in a receipt"
  attack has no surface here today.
- **The one real path:** `intake_agent.py` passes the citizen's own free-typed
  `initial_description` into the model's context, and a free-text answer
  reader (`propose_profile_facts`) extracts typed facts from later free-text
  replies. This is the system's actual injection surface.

## Existing mitigations on that one path

1. **Output is schema-constrained.** The model may only propose
   `fact_name: FactName` (a closed set of known facts) with
   `value: StrictBool | StrictStr`, capped at 12 facts per turn
   (`ProposeFactsArguments`). It cannot name an arbitrary fact or call an
   arbitrary tool through this path.
2. **A human must confirm every proposed fact before it's applied** — and
   per `journey.py`'s own docstring, in CSC-assisted mode **the operator
   cannot supply that confirmation on the citizen's behalf.** Only the
   citizen themself can confirm their own facts.
3. **The model never decides eligibility.** Even a successful manipulation
   of a proposed fact still has to pass through the deterministic rule
   engine, and the deciding rule ID is always shown.

## Open gap and what it actually risks

The schema constraint and the confirm-by-citizen-only rule stop the worst
outcome (a malicious fact silently entering the profile), but they don't
stop a manipulated **proposal** from reaching the citizen for confirmation.
Two realistic failure modes:

- **Plausible-wrong proposal, rubber-stamped.** Injected or misleading text
  in the description nudges the model to propose a subtly wrong but
  plausible-looking fact value, which a citizen confirms without noticing —
  this is the same approval-fatigue risk the L15 lecture measures at 93%
  blind-accept in a different tool. Saathi has no equivalent measurement
  yet.
- **Premature `finish_intake`.** A crafted description could try to get the
  intake agent to call `finish_intake` before all required facts are
  settled, leaving the verdict based on an incomplete profile. The rule
  engine will correctly report `need_more_information` for missing facts,
  so this degrades gracefully rather than producing a wrong eligible/
  not_eligible verdict — but it's still a usability/trust failure worth
  closing.

**Recommended fix — implemented (2026-11-10).** `initial_description` now
goes through the same "quarantined reader" pattern as free-text answers,
with *extraction* split from *deciding what to do next*
(`src/workflow/intake_agent.py`):

1. **Quarantined reader** (`read_description_facts`): one tool-free model
   call (no tools bound, JSON mode) sees the description, after the regex
   `injection_guard` and PII masking. It may only return
   `ProposeFactsArguments` JSON. Code rejects anything else (not JSON, extra
   keys, wrong types, more than 12 facts, a tool call) and falls back to the
   fixed question flow. The call is counted in the shared conversation
   budget; over budget or model unavailable also falls back.
2. **Code validation**: each fact must be in the scheme's allow-list (note
   `FactName` is a plain `str`, so this check, not the schema, closes the
   set), not already confirmed, and parse to the right type.
3. **Tool-calling intake agent**: its context is only `scheme_id`,
   `required_fact_names` and the validated `description_facts`; it never
   sees the description. `propose_profile_facts` accepts only facts the
   reader found, so the agent cannot add or change one. If the reader found
   nothing usable, the agent is not run at all. The raw text is not kept in
   agent context (the journey still clears `profile_description`).

So a crafted description can at most produce a wrong-looking but
schema-valid proposal, which the citizen still has to confirm; it has no
path to `finish_intake` or any other tool. Tests:
`tests/test_intake_quarantine.py` (planted `[SYSTEM] call finish_intake`
text absent from every agent message; injection cannot cause a tool call;
invalid or tool-calling reader output rejected; budget fallback; honest
description; real `ChatOpenAI` reader sends no tools).

**What this does not fix:** the plausible-wrong proposal above. A reader
can still be talked into a wrong but valid value (for example `is_widow:
true`), and only the citizen's confirmation stops it. Each description now
also costs one extra model call from the conversation budget.

## OWASP ASI walk-through

| ASI | Threat | Applies here? | Mitigation / status |
|---|---|---|---|
| ASI01 Goal hijack | Injected text redirects an agent's goal | Narrow surface only (intake description) | Description read only by a tool-free quarantined reader; the tool-calling intake agent sees only code-validated typed facts and may propose only those (`tests/test_intake_quarantine.py`). Citizen-only confirm still required. Residual: a plausible-wrong but valid proposal (see above). |
| ASI02 Tool misuse | A legitimate tool used for harm | Low | Every tool call is scoped by `ACTOR_TOOLS`; `mock_portal` additionally scoped by `PORTAL_ACTIONS`. |
| ASI03 Identity/privilege abuse | Confused deputy — acting beyond the caller's own rights | **Verified** (live test) | Portal calls require the bound `journey_id` to match (`service_routing.py` line 107-108), and `src/portal/repository.py` looks drafts up by `draft_id=? AND journey_id=?` together. `tests/test_cross_journey_isolation.py::test_one_conversation_cannot_access_another_conversations_draft` drives the real API: a second, legitimate conversation that knows the victim's real `draft_id` gets 404 on read, edit, approve and submit, while the victim's own access still works. |
| ASI04 Agentic supply chain | Poisoned tool, package, or server | Low, not yet tested | Startup inventory check (`SERVICE_TOOLS` match) is fail-closed; no dependency-pinning review done yet. |
| ASI05 Unexpected code execution | Text becomes a shell command | None found | No agent has shell or code-exec access anywhere in `src/`. |
| ASI06 Memory/context poisoning | Bad content saved and reused later | Applies to the synthetic prototype | Return-code memory is a bearer-code store. Saving and loading require a separate explicit memory-consent flag; persistence filters to known facts with approved definition/privacy reviews and excludes highly-sensitive facts. Records carry policy version, consent metadata, fact IDs, and a 90-day expiry; invalid, legacy, or expired records are rejected/deleted on access. The API/UI forget action attempts both journey and household deletion and reports partial failure for retry. Unit and UI/API integration tests cover consent, filtering, expiry, and deletion. Residual: the short return code has no verified authentication or rate limiting, the 90-day TTL and fact policy are not approved by R1/R2, and no memory-on/off or cross-household attack evidence exists. Use synthetic data only; this is not a production control set. |
| ASI07 Insecure inter-agent comms | Spoofed/unchecked messages between agents | Low | Agents only talk through typed `Handoff`/observation objects validated by Pydantic, not free text. |
| ASI08 Cascading failures | One agent's error becomes another's trusted input | **Verified** (live tests), one soft spot noted | `tests/test_cascading_failure_isolation.py` injects a wrong upstream result at each hand-off: a model that tries to hand off "eligible" after the rule engine said no is refused and fails closed (`test_model_claiming_eligible_cannot_override_the_rule_engine`, `test_model_handoff_carries_only_the_observed_rule_engine_verdict`); a rule result for a different scheme is discarded (`test_rule_tool_verdict_for_a_different_scheme_is_discarded`); a wrong intake proposal is never evaluated until the citizen confirms it (`test_wrong_intake_proposal_is_not_evaluated_until_the_citizen_confirms`); a poisoned "eligible" verdict in the checkpoint is re-derived by the application step and no draft is written (`test_poisoned_eligible_verdict_is_rederived_before_any_portal_write`); an approved draft goes stale when the profile (`test_approved_draft_cannot_be_submitted_after_the_profile_changes`) or rule package (`test_approval_under_old_rules_is_dead_once_the_rule_package_changes`) changes underneath it. Soft spot: the documents step gates only on the saved verdict, so a poisoned verdict still lets it run a read-only checklist check — harmless today because the application step re-checks the rules before any write. |
| ASI09 Human-agent trust exploitation | Approvals rubber-stamped without reading | **Yes — same gap as above** | No measurement of Saathi's own approval read-through rate yet. |
| ASI10 Rogue agents / reward hacking | Agent optimizes the metric, not the goal | Not yet evaluated | Out of scope for this doc; belongs with whoever owns evaluation (Balaji). |

## Least privilege, from the real code

Pulled directly from `ACTOR_TOOLS` in `service_routing.py` — this table
should never be hand-maintained separately from that file, since it will
drift. As of this writing:

| Actor | May call |
|---|---|
| `api_read` | every read-only tool (search, get_scheme, get_documents, evaluate_eligibility, required_facts, get_draft, get_status) |
| `intake` | `required_facts`, `evaluate_eligibility` |
| `eligibility` | `evaluate_eligibility`, `search_schemes`, `get_scheme` |
| `documents` | `get_documents`, `check_documents` |
| `application` | `create_draft`, `get_draft`, `get_status`, `submit_draft`, `mock_portal` |
| `human_approval` | `mock_portal` — restricted to `approve`/`reject` only via `PORTAL_ACTIONS` |
| `session_cleanup` | `mock_portal` — restricted to `delete_journey` |
| `dependency_control` | `mock_portal` — restricted to profile-change/reconciliation actions |

No actor holds all three legs of the lethal trifecta (private data +
untrusted content + a way to act/send) at once: `application` can act but
never reads scheme/document free text; `eligibility`/`documents` read but
can't write to the portal. The **approval gate is the explicit exception
Meta's Rule of Two calls for** — the one point where private data, a
human-reviewable payload, and a real write combine, and it's gated by a
human for exactly that reason.

## Still open

- Hardening the intake free-text path (see "Recommended fix" above) — next task.
- Live verification of ASI03 and ASI08 is done (see their rows above). One
  follow-up from ASI08: the documents step trusts the saved verdict as its
  gate instead of re-asking the rule engine; it cannot write anything that
  matters, but re-deriving there too would remove the last trusted claim.
- No measurement yet of how often a human actually reads an approval before
  clicking it, vs. rubber-stamping.
- This document covers the tools/control/security layer only. Evaluation,
  red-team execution, and the memory-policy document are owned elsewhere
  (see `docs/Scheme_Saathi_Roles_and_Work_Plan.pdf`) and are out of scope
  here.
