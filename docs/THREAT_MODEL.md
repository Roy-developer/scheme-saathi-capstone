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

**Recommended fix (not yet implemented, next task):** treat
`initial_description` and any free-text answer the same way the L15
lecture's "quarantined reader" pattern treats untrusted text — a separate,
tool-free model call that extracts only the typed fields it's allowed to
extract, with the raw free text discarded immediately after. The existing
`ProposeFactsArguments` schema already gives this pattern a natural home;
what's missing is isolating the *extraction* step from the *decide what to
do next* step so a crafted description can at most produce a wrong-looking
proposal, never influence anything beyond proposing.

## OWASP ASI walk-through

| ASI | Threat | Applies here? | Mitigation / status |
|---|---|---|---|
| ASI01 Goal hijack | Injected text redirects an agent's goal | Narrow surface only (intake description) | Schema-constrained output + citizen-only confirm. Gap: proposal quality not yet hardened (see above). |
| ASI02 Tool misuse | A legitimate tool used for harm | Low | Every tool call is scoped by `ACTOR_TOOLS`; `mock_portal` additionally scoped by `PORTAL_ACTIONS`. |
| ASI03 Identity/privilege abuse | Confused deputy — acting beyond the caller's own rights | Needs a live test | Portal calls require the bound `journey_id` to match (`service_routing.py` line 107-108); not yet verified against a crafted cross-journey request. |
| ASI04 Agentic supply chain | Poisoned tool, package, or server | Low, not yet tested | Startup inventory check (`SERVICE_TOOLS` match) is fail-closed; no dependency-pinning review done yet. |
| ASI05 Unexpected code execution | Text becomes a shell command | None found | No agent has shell or code-exec access anywhere in `src/`. |
| ASI06 Memory/context poisoning | Bad content saved and reused later | Low | No long-term memory store exists yet in the code (confirmed by grep) — nothing to poison yet, but also nothing protecting one once it's built. |
| ASI07 Insecure inter-agent comms | Spoofed/unchecked messages between agents | Low | Agents only talk through typed `Handoff`/observation objects validated by Pydantic, not free text. |
| ASI08 Cascading failures | One agent's error becomes another's trusted input | Needs a live test | Each specialist re-derives its own facts from the rule engine rather than trusting a peer's claim, by design — not yet stress-tested with a deliberately wrong upstream result. |
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
- Live verification of ASI03 (cross-journey access) and ASI08 (cascading
  failure) rather than code-reading alone.
- No measurement yet of how often a human actually reads an approval before
  clicking it, vs. rubber-stamping.
- This document covers the tools/control/security layer only. Evaluation,
  red-team execution, and the memory-policy document are owned elsewhere
  (see `docs/Scheme_Saathi_Roles_and_Work_Plan.pdf`) and are out of scope
  here.
