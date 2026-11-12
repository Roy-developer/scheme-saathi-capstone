# Phase 1 gap-closure plan (Round 2 merge)

**Status:** Round 2 / diminishing-returns merge of five planner lanes  
**Date:** 2026-11-12  
**Audience:** Balaji (Role 5) + team leads  
**PDF baseline:** `capstone_projects 2 (1) (1).pdf` (SHA-256 `21a4b6b279628a2768354ae93a4cf88d10224917cf639cd1d4bb352e91e281ee`)  
**Sources merged:** Critic (c0d3c08c), Registry (aa464be2), MCP (7773872b), UI (805cc832), Sign-off (31406709); Round 2 merge (a22ccdaf).  
**PDF conflict rule:** Capstone PDF wins. Team “Phase 1 — Base” is Gate **B** scheduling — never sold as PDF pages.  
**Inventory only (not closure credit):** `origin/supervisor-redesign-3` / [PR #29](https://github.com/Roy-developer/scheme-saathi-capstone/pull/29).

---

## 0. One-sentence verdict

Close Phase 1 with **Gate A PDF honesty → Gate B registry/MCP + local EN four-box browser → R1 templates (no forged approvals) → named Phase 1 ceremony** — and treat that ceremony as **necessary but not sufficient** for paid Phase 5: it closes only the **G1 Phase-1 cell**; announce paid/held-out still paused until Phases 2–4 + full G1–G4.

### Why this order (citizen / viva story)

Imagine Sunita at a CSC on a **local** laptop stack (API `:8000`, Streamlit `:8501`) — not Azure demo day.

- Without **Gate A honesty**, the team will launder registry hashes, engineer `Roy-developer` stamps, or “four modules in one process” as Capstone PDF L7 / “reviewed rules.”
- Without **Gate B registry + MCP evidence**, the four UI boxes prove a UI that may not be the shared foundation the team plan claims.
- Without the **local EN four-box browser**, pytest / AppTest / headless integration prove layers, not “human + Chrome + live stack.”
- Without **R1 templates + real decisions** (or explicit pending + fail-closed), “reviewed JSON” is engineering metadata theater.
- Without a **named Phase 1 ceremony file**, `eval/PHASE_1_4_ACCEPTANCE.md` stays “Sign-off: Pending,” and nobody can honestly mark the Phase 5 **G1 Phase-1 cell**.

**Critic→Sign-off reconciliation (binding):** Round 1 Critic language that Phase 1 + exceptions “authorize paid/held-out” is **over-claim**. Round 2 adopts Sign-off: Phase 1 closes **G1’s Phase-1 cell only**. Paid E1/E3/E4 and final HO remain locked until Phases 2–4 acceptance records exist **and** G1–G4 are real (`docs/PHASE5_GAP_CLOSURE_PLAN.md`).

### What Round 2 cut (vanity work)

| Cut / deprioritize | Why critic killed it |
|---|---|
| Vanity tests that restate existing synthetic numeric/choice / hash / choice / `development_only` coverage in `tests/test_fact_registry.py` | Automated registry gate already closed; more asserts ≠ R1 honesty |
| Expanding `mock_portal` PortalAction E2E beyond a **thin** evidence/annotation harden | Happy-path 11 tools + permission denials already exist; full action matrix is viva polish, not Gate A |
| Playwright (or any browser automation) as Phase 1 blocker | Manual LOCAL EN A–D is the gate; automation is regression later |
| Full HI/MR + a11y independent review as Phase 1 blocker | Named exception `X-P1-HI-MR` OK if EN citizen path passes |
| Catalogue activation / complete-bundle publish / `activation_state` theater | **Phase 6** (`docs/PHASE6_GAP_CLOSURE_PLAN.md` BN*) |
| PR #29 / OTEL / household memory / Role 5 eval reports as Phase 1 credit | Wrong phase; inventory only |
| Azure / Compose / Grafana / streaming / pretty Streamlit MCP error UX / real portal | Phase 6 or out of agreed scope |
| 15 gold, memory L9, E1–E4 paid/HO, κ, Reflexion depth | Phase 5 / signature — not Phase 1 |
| Forging `definition_review_status: approved` / backdated ceremony | Forbidden; Role 5 must refuse |

**Prefer instead:** doc honesty + evidence pack + MCP **startup inventory mismatch** fail-closed test + R1 templates + LOCAL four-box browser + Phase 1 ceremony that still says paid/HO paused.

---

## 1. Honest starting line (do not over-claim)

From `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md` Phase 1, `docs/PHASE1_CODE_WALKTHROUGH.md`, lane inventories on `supervisor-redesign-3`, and Critic Covered/Partial/Missing (Nov 2026):

| Area | Today | Gap for Phase 1 honesty / Gate B |
|---|---|---|
| **PDF “Phase 1”** | Does not exist as a PDF page | Team schedule only — Gate B |
| Deterministic eligibility | **Covered (impl)** — `src/api/eligibility.py` → MCP `rule-engine` → journey; LLM does not decide | Keep true; map `need_more_information` ↔ PDF “can’t tell” in claim matrix |
| Clause-linked pilot JSON | **Covered (structure)** — e.g. `src/rules/packages/ignwps_mh.v1.json`, `pmkisan_in.v1.json`; `test_every_packaged_rule_carries_its_exact_source_clause` | R1 mock-scope human decision still open for ceremony |
| Fact registry + shared evaluator + synthetic data-only gate | **Covered (automated)** — `tests/test_fact_registry.py` (numeric/choice/malformed/`development_only`) | Docs stale (“all pending” / `legacy_compatibility`); human fact/question/privacy review open where pending |
| Bundles / pins | Live pins in `src/rules/bundle_registry.json`; novel `development_only` refused by default | IGNOAPS/APY `activation_state: approved` while some Q/privacy pending — **do not** “fix” by activating; Phase 6 + honesty |
| MCP ×4 + separate portal DB (G02) | **Covered (impl)** — four stdio `*_server.py`; portal FastAPI+SQLite; `docs/MCP_TOOL_INVENTORY.md`; 11 tools | Missing: automated **startup inventory mismatch** refuse-to-serve test; thin annotation/error polish optional |
| Approval before write (L14 shape) | **Mostly Covered (impl)** — `application_gate` / `src/ui/approval.py` / portal fingerprint+TTL | **Manual browser** widow draft→approve→submit still unchecked |
| “Reviewed” rules/facts (PDF human) | **Partial** — engineer reviewers / `approved_for_mock_portal`; APY trio Q/privacy still `pending` | R1 templates + signed reviews **or** remain pending fail-closed — **no forged JSON** |
| Team UI checklist (4 boxes) | Still `[ ]` in `PHASE_WISE` | LOCAL EN manual script + evidence pack |
| Named Phase 1 / 1–4 acceptance | `eval/PHASE_1_4_ACCEPTANCE.md` (on branch): **Sign-off Pending** | Need `eval/PHASE_1_ACCEPTANCE.md` slice; rollup final paid/HO box stays unchecked |
| PR #29 | Memory / monitoring / eval snapshot | **Inventory only** — never Phase 1 done |
| Activation / publish | Not Phase 1 scope | Hand to Phase 6 |

**Citizen scenario (why Partial ≠ closed):** Sunita can already get a code verdict and a fingerprint-bound mock submit in **tests**. An examiner asking “who reviewed that BPL clause as live mock policy?” or “click approve→submit in the browser” still hits open R1 + unchecked UI boxes. That is the honesty gap this plan closes — not more pytest greens.

---

## 2. Roles (RACI for this roadmap)

| Role | Accountable for | Must not do |
|---|---|---|
| **R1 Domain** | Pilot package mock-scope decisions; fill fact/question/privacy templates; define “matches baseline” for UI; named exceptions on language/APY scope | Forge `approved` in `fact_registry.json`; treat engineer stamps as domain review |
| **R2 Knowledge** | Registry/package content honesty; fail-closed pending disclosure behavior; pin/re-pin after real R1 updates | Implement catalogue activate/publish in Phase 1 |
| **R3 Orchestration** | Keep journey on shared evaluator; approval interrupt path coherent for UI A–D | Bypass approval for “smooth browser”; weaken eligibility for easier greens |
| **R4 Tools/MCP** | G02 evidence: four processes, annotations, permissions, **startup mismatch test**; MCP packet for ceremony | Fifth FastMCP; Azure MCP topology; real portal |
| **R5 Eval/claims (Balaji)** | Claim matrix Phase 1 rows; evidence index; anti-claims; pin commit SHA; refuse forged approvals / paid-HO inflation; chair evidence walk | Approve domain meaning; flip rollup paid/HO checkbox; invent R1 signatures |
| **R6 UI/ops** | LOCAL stack runnable; execute four-box browser; screenshots; UI sign-off fields | Claim AppTest = manual pass; use Azure as Phase 1 proof |
| **Named lead** | `decision` + `ceremony_date` + exceptions on `PHASE_1_ACCEPTANCE.md` | Backdate; authorize paid/HO from Phase 1 alone |

**Separation:** defender ≠ domain approver. Role 5 indexes and refuses dishonest claims; Role 5 does **not** sign pilot fact meaning.

---

## 3. Master sequence — four waves (A–D)

Effort: **S** ≈ 1–2 days, **M** ≈ 3–5 days. Priority: **P0** claim-blocking, **P1** evidence polish, **P2** optional viva harden.

**Critic merge order (fixed):** Gate A claim freeze → Gate B packets (Registry honesty + MCP fail-closed + UI browser) → R1 templates/reviews → Sign-off ceremony. Activation never enters these waves.

```text
Wave A  Claim freeze + doc honesty + anti-claims (Gate A spine)
Wave B  Evidence packets in parallel: Registry | MCP | UI LOCAL EN
Wave C  R1 templates + pilot decisions (no forged approvals)
Wave D  Named Phase 1 ceremony → G1 Phase-1 cell only; paid/HO still paused
```

---

### Wave A — Claim freeze / PDF honesty (same day / P0)

| ID | Work | Owner | Effort | DoD (artifact) |
|---|---|---|---|---|
| **A0** | Phase 1 claim matrix: PDF Gate A rows vs team Gate B rows → artifact → owner → `not claimable` / `partial` / `ready` | R5 | S | One table; PDF ≥3 MCP vs design 4 called out explicitly |
| **A1** | Patch honesty in `docs/PHASE1_CODE_WALKTHROUGH.md` + Phase 1 evidence block in `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md`: automated registry gate closed; human review open where pending; activation = Phase 6; `legacy_compatibility` = historical | R5 (+ R2 C) | S | Docs match disk; no “all pending” / “no approved state” lies |
| **A2** | Strike stale “single combined MCP server = scaffolding” in living plans viva might open (e.g. `docs/END_TO_END_IMPLEMENTATION_PLAN.md`) | R5 (+ R4 C) | S | Living docs match four stdio processes |
| **A3** | Inventory note: PR #29 ≠ Phase 1; `bundle_registry.json` activation rows listed; IGNOAPS/APY drift flagged for Phase 6 — **not** fixed by publishing | R5 | S | Dated paragraph in evidence index |
| **A4** | Map `need_more_information` ↔ PDF “can’t tell”; FastMCP → `MCPServer` (mcp 2.x) rename note | R5 | S | Claim-matrix footnotes |

**Kill:** stop when matrix + doc honesty exist. Do not start activation coding, Playwright scaffolding, or vanity registry tests.

**Scenario:** Examiner opens the walkthrough mid-viva and finds “every fact pending” while `fact_registry.json` shows approvals — trust dies. Wave A prevents that accident.

---

### Wave B — Gate B evidence packets (parallel / P0)

Three packets; none alone is Phase 1 closed.

#### B1 — Registry / evaluator packet (mostly already green)

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **R0** | Cite automated gate green: synthetic data-only + malformed reject + `development_only` refused — **no new vanity tests** | P0 | R4/R2 (R5 index) | S | Node IDs from `tests/test_fact_registry.py` in evidence index |
| **R1** | Pilot pin evidence: IGNWPS-MH / PM-KISAN-IN → package file → `package_sha256` → `registry_sha256` → clause ID set | P0 | R5 (+ R1 C) | S | `docs/PHASE1_PILOT_PIN_EVIDENCE.md` (or honesty box) |
| **R2** | Pending metadata rule written: pending Q/privacy ≠ policy-approved / model-disclosable; audit shared intake; **add one test only if a real leak exists** | P0 | R2 (R5 cases) | S–M | Written rule + optional single regression — else “no shared leak found” note |
| **R3** | Explicit non-deliverable: loader refuse of `approved` bundles with pending Q/privacy → **Phase 6** | P0 | R5 | S | Handoff bullet accepted |

#### B2 — MCP / G02 packet

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **M0** | L7/G02 one-pager: four processes, 11 tools, annotations, structured errors, separate portal DB, permissions | P0 | R5 + R4 | S | Packet linked from evidence index |
| **M1** | **Fail-closed startup test:** inject mismatched discovered tools → lifespan raises inventory mismatch; API does not serve | P0 | R4 (R5 indexes) | S | New test + green CI/local note |
| **M2** | Optional thin harden (P2 only if viva pushback): annotate all 11 tools vs inventory; one extra structured-error (`conflict` / unavailable) — **not** full PortalAction E2E expansion | P2 | R4 | S–M | Only if M0–M1 insufficient for examiner |
| **M3** | Local boot note (how to show four children) — **no Azure/Compose** | P1 | R6 | S | One-pager in evidence pack |

#### B3 — UI / journey packet (blocking for Gate B Done-when)

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **U0** | Preflight: `git rev-parse HEAD`, API health, Streamlit health, synthetic banner | P0 | R6 | S | Notes in UI packet |
| **U1** | Manual LOCAL EN **A–D** (see §4.3): widow search; PM-KISAN + mock notice; failed PM-KISAN + rule ID; widow draft→approve→mock submit | P0 | R6 (R1 baseline; R5 residual) | M | Screenshots + pass/fail per box + SHA + tester |
| **U2** | Language residual draft (`X-P1-HI-MR`); CSC light optional | P0 | R6+R1 | S | Explicit exception text — not silent pass |
| **U3** | Check `PHASE_WISE` four boxes **only** with evidence pointer | P0 | R6 (R5 refuse if AppTest-only) | S | Checklist + link |

**AppTest / API / `test_ui_integration.py`:** supporting only. Never substitute for U1.

**Kill for Wave B:** registry citations + pin note + MCP M1 + UI A–D packet. Stop mock_portal action sprawl and Playwright.

---

### Wave C — R1 templates + pilot decisions (P0 process)

| ID | Work | Owner | Effort | DoD |
|---|---|---|---|---|
| **H1** | Add empty templates (do not pre-fill approvals): `docs/checklists/PHASE1_FACT_DEFINITION_REVIEW_TEMPLATE.md`, `…_QUESTION_LOCALIZATION_REVIEW_TEMPLATE.md`, `…_PRIVACY_POLICY_REVIEW_TEMPLATE.md` — tone like `docs/APY-IN_FACT_INTAKE_REVIEW_2026-11-11.md` (“draft only / not policy approval”) | R5 scaffolds; R1 owns | S | Three files exist |
| **H2** | R1 fills pilot instances: IGNWPS-MH + PM-KISAN-IN facts/questions/privacy used in Gate B browser; reuse/amend `docs/IGNWPS_MH_RULE_REVIEW_*.md` / PM-KISAN rule reviews for packages | R1 | M | Signed docs with real name/date |
| **H3** | APY pending trio: approve Q/privacy **or** remain `pending` with fail-closed — **never** silent JSON flip | R1 (+ R2) | S–M | Written decision; registry honest |
| **H4** | Only after signed R1 docs: update registry review fields with **real** reviewer/date; re-pin SHA in `bundle_registry.json` if bytes change | R1/R2 | S | Diff matches review docs |

**Role 5 must not** invent `approved`, rewrite `reviewer_name`, or close R1 rows.

---

### Wave D — Sign-off ceremony → G1 Phase-1 cell only (P0)

| ID | Work | Owner | Effort | DoD |
|---|---|---|---|---|
| **S0** | Create `eval/PHASE_1_ACCEPTANCE.md` with required header fields (`commit_sha`, `ceremony_date`, `pdf_baseline_sha256`, `decision`, `approver_name`/`role`, `exceptions[]`, `anti_claims_acked`) | R5 draft; named lead decides | S | File exists; no blanks / no backdating |
| **S1** | Rows minimum: **P1-R1-PKG**, **P1-R1-REG**, **P1-R1-SYN**, **P1-MCP-G02**, **P1-ENG**, **P1-UI-MAN**, **P1-UI-LANG**, **P1-CLAIM**, **P1-LEAD** (statuses + evidence paths) | Owners per row | S | All pass or **allowed** exception IDs |
| **S2** | Update `eval/PHASE_1_4_ACCEPTANCE.md`: Phase 1 status **links** to Phase 1 file; mis-file deploy/monitoring/activation → Phase 6; **final paid/HO authorization checkbox remains unchecked** | R5 | S | Rollup honest |
| **S3** | Ceremony (30–45 min): Critic 2′ → R1 → R4 MCP → R6 UI → R5 anti-claims → named lead decision → announce pause | All | S | Dated decision |
| **S4** | Team announcement: “Phase 1 signed; Phase 5 paid/held-out remains **paused** pending Phases 2–4 + G1–G4.” | Named lead / R5 | S | Chat/issue record |
| **S5** | Feed Phase 5 G1 draft: Phase 1 cell = `accepted` / `accepted_with_exceptions` + exception residuals | R5 | S | G1 checklist row only |

**Allowed exceptions (examples):** `X-P1-HI-MR`, `X-P1-REG-META` (non-pilot pending + fail-closed), `X-P1-APY-SCOPE`, `X-P1-AUTO-ONLY-CSC`, `X-P1-PY312-CI`.  
**Disallowed as exceptions:** missing pilot R1 decisions; one-process MCP; LLM eligibility; forged approvals; AppTest-as-manual; Phase 1 “authorizes paid/HO.”

**Kill:** Phase 1 file signed; rollup paid/HO still open; announcement made. No celebration drift into freeze/HO spend.

---

## 4. Lane details (condensed)

### 4.1 Registry & Evaluator

**Already true:** eligibility in code; clause-linked packages; synthetic data-only gate; hash pins; `development_only` refused (`src/rules/data_provider.py`, `tests/test_fact_registry.py`).

**Still do:** doc honesty; pin evidence; R1 templates; pending fail-closed audit (**one** new test max if leak found).

**Do not:** rebuild `src/rules/facts.py`; resurrect `legacy_compatibility`; vanity hash tests; implement activate/publish; flip pending→approved without R1.

**Exit language:** “Phase 1 registry/evaluator **automated** gate closed; human fact/question/privacy open where pending; catalogue publish/activate deferred to Phase 6.”

### 4.2 MCP / G02

**Already true:** four stdio servers (`schemes-kb`, `rule-engine`, `doc-check`, `mock-portal`); portal separate DB; 11 tools; typed errors; annotations; permission denials (`docs/MCP_TOOL_INVENTORY.md`, `docs/MCP_PERMISSIONS_WALKTHROUGH.md`, `tests/test_mcp_services.py`, `tests/test_mcp_permissions.py`).

**Still do:** claim freeze; **startup mismatch fail-closed test**; evidence pack (list_tools / pytest node IDs / rename note).

**Do not:** fifth MCP; HTTP MCP rewrite; Azure/Compose; real portal; pretty Streamlit errors; split `mock_portal` into many top-level tools; full PortalAction E2E expansion unless viva-critical (P2).

**PDF honesty:** L7 minimum is **≥3**; four is **Scheme Saathi design**. Four modules on one process ≠ G02.

### 4.3 UI / Journey acceptance

**Blocking script (LOCAL EN):**

| Box | Pass means |
|---|---|
| A Widow | Search `widow pension` → IGNWPS-MH → chat (prefer) → eligible matches synthetic baseline + plan + clause/rule |
| B PM-KISAN | Search `farmer income support` → PM-KISAN-IN → mock/currentness notice visible + eligible mock baseline |
| C Fail rule | Exclusion fires → `not_eligible` + **visible rule ID** (expander / deciding list) |
| D Approve | Checklist → draft → submit blocked until approve → approve exact → mock submit → receipt; demo banner intact |

Primary surface: `src/ui/app.py` (+ `api_client.py`, `approval.py`). Stack: `PROJECT_SETUP.md` local ports.

**Playwright / Azure:** non-blocking for Phase 1. HI/MR full review: exception OK.

### 4.4 Sign-off & Phase 5 unlock slice

**Split files:** `eval/PHASE_1_ACCEPTANCE.md` (ceremony) + `eval/PHASE_1_4_ACCEPTANCE.md` (rollup).

**Phase 1 can unlock:** G1 Phase-1 cell; freeze *inputs* (hashes/inventory SHA); Phase 1 claim-matrix honesty; parallel Phase 5 Wave 0 prep (already allowed without unpause).

**Phase 1 cannot unlock:** paid E1/E3/E4; final HO; “Phases 1–4 accepted”; MEMORY_POLICY/L9; Azure/Grafana; activation; PR #29 credit.

---

## 5. Phase 6 handoff bullets

Hand these off; **do not implement in Phase 1 waves:**

1. Enforce activate policy: `activation_state=approved` requires package fitness + definition approvals + team decision on whether pending Q/privacy **blocks activate** vs only blocks model disclosure.
2. Complete-bundle stage → validate → activate (BN0–BN5 in `docs/PHASE6_GAP_CLOSURE_PLAN.md`); image-bake vs share stage; crash/rollback without mixed versions or restored approvals.
3. Catalogue honesty for IGNOAPS/APY current `approved` rows (provisional mock-only caveats vs bring under activate gate).
4. Azure inventory, runbook, Managed Grafana, streaming, CI fail artifact, Hindi-widow Azure flagship.
5. Public MCP/HTTP-in-Docker topology if ever required for L16 — not Gate B.
6. Real government portal integration.

---

## 6. Relationship to Phase 5 unpause

| After Phase 1 DoD | Phrase to use |
|---|---|
| Ceremony complete | “**Phase 1 G1 cell closed**” (`accepted` / `accepted_with_exceptions`) |
| Still required | Phase **2–4** acceptance records + full **G1** honesty pass across open items |
| Then | **G2** freeze manifest, **G3** attack authorship, **G4** held-out secrecy |
| Only then | “Unpause = authorize **paid** E1/E3/E4 and final HO runs” |

Phase 5 Wave 0 (HO unstage, count honesty, claim matrix draft, threshold pre-register) may proceed **with or without** Phase 1 sign-off. **Paid / final HO may not.**

Do **not** use Critic Round 1 “authorize paid under Phase 1 exceptions” wording in viva or acceptance files.

---

## 7. Anti-claims (say out loud in ceremony; R5 enforces)

1. “Phase 1 is a Capstone PDF requirement / page.” — False; team schedule (Gate B).
2. “PDF L7 minimum is four MCP servers.” — Minimum **≥3**; four is design.
3. “PR #29 / `supervisor-redesign-3` closes Phase 1.” — Inventory; Sign-off was Pending.
4. “Rules/facts are PDF-reviewed because `Roy-developer` / `approval_status` is in JSON.” — ≠ Role 1 domain sign-off.
5. “L14 / approval done because unit tests / AppTest / headless integration passed.” — Need recorded LOCAL browser A–D.
6. “Four modules on one MCP process satisfy G02.”
7. “Phases 1–4 accepted / Phase 5 paid-HO authorized” from Phase 1 alone.
8. “IGNOAPS/APY `activation_state: approved` means publication done.” — Activation is Phase 6.
9. “Azure / Grafana / streaming / 15 gold / memory-on-off / E1–E4 prove Phase 1.”
10. “Inventory mismatch fail-closed is proven” before M1 lands.
11. “`doc-check` does authenticated extraction.” — Metadata checklist compare only.
12. Free/local smoke ≠ E1 ≠ freeze ≠ paid authorization.

---

## 8. Exit claim language — allowed / forbidden

### Allowed (after Waves A–D)

- “Gate A PDF-shaped foundation is honest on this commit: eligibility in tested code; clause-linked pilot JSON; ≥3/design-4 MCP processes with inventory + tests; human approval before mock write demonstrated on LOCAL EN path.”
- “Team Gate B Phase 1 Done-when met for registry automated gate + G02 evidence + signed UI four-box, with named exceptions (e.g. HI/MR).”
- “R1 templates exist; pilot decisions recorded **or** pending left fail-closed — no forged approvals.”
- “`eval/PHASE_1_ACCEPTANCE.md` signed; Phase 5 **G1 Phase-1 cell** closed.”
- “Phase 5 paid/held-out remains **paused** until Phases 2–4 + G1–G4.”
- “Catalogue activation/publish deferred to Phase 6.”
- “PR #29 treated as inventory only.”

### Forbidden

- “Phase 1 PDF page complete.”
- “All registry metadata approved” / “pending privacy is fine because the bundle says approved.”
- “New schemes activated / complete-bundle gate closed.”
- “Phase 1 UI accepted” from AppTest alone.
- “Phases 1–4 accepted.”
- “Phase 5 unpaused / paid E1–E4 / held-out authorized.”
- “L9 / E1–E4 / Grafana / 15 gold closed as a side-effect of Phase 1.”
- “Playwright will backfill the unsigned manual boxes.”

---

## Claim matrix (working template)

| Item | Gate | Required artifact | Owner | Status (start) |
|---|---|---|---|---|
| Eligibility in code (not LLM) | A | Path + tests cited | R3/R4/R5 | partial → ready after A0 |
| Clause-linked pilot JSON | A | Packages + pin evidence + R1 mock-scope | R1/R5 | partial |
| MCP ≥3 / design 4 + portal DB | A/B | Inventory + M1 startup test | R4/R5 | partial (impl; M1 open) |
| Approval before write | A/B | LOCAL Scenario D + portal binding | R6/R3 | partial (tests; browser open) |
| Registry automated gate | B | `test_fact_registry` citations | R4/R5 | ready (automated) |
| R1 fact/Q/privacy | B/C | Templates + signed reviews / pending | R1 | not claimable |
| UI four-box | B | LOCAL EN packet | R6 | not claimable |
| Phase 1 ceremony | D | `PHASE_1_ACCEPTANCE.md` | Named lead | not claimable |
| Phases 1–4 + paid HO | Phase 5 | Full G1–G4 | Lead + R5 | **locked** |
| Activation/publish | Phase 6 | BN* | R4/R6 | out of scope |

---

## Definition of Done = evidence artifacts (not “tests pass”)

| Wave | Evidence pack |
|---|---|
| A | Claim matrix; walkthrough/phase-plan honesty; anti-claim footnotes; PR #29 inventory note |
| B | Pin evidence; MCP M1 test; LOCAL EN A–D screenshots + SHA; optional MCP P2 only if needed |
| C | Three templates; R1-signed pilot docs or explicit pending; no forged registry flips |
| D | `PHASE_1_ACCEPTANCE.md` signed; rollup link; paid/HO unchecked; announcement; G1 Phase-1 cell updated |

**Closed for Phase 1 story:** On a recorded commit, examiner sees four MCP children, a deterministic widow/PM-KISAN path with clauses, LOCAL approve→submit, R1 paperwork or honest pending, and a named Phase 1 signature that **still refuses** to spend paid held-out budget.

---

## Stop-polish kill criteria (post on the wall)

| If you are about to… | Stop unless… |
|---|---|
| Add another synthetic/hash registry test | Pin evidence or R1 honesty still open |
| Expand mock_portal action E2E | M1 startup test + inventory packet still missing |
| Make Playwright a Phase 1 blocker | Manual A–D unsigned |
| Block Phase 1 on full HI/MR | You refuse the named exception path |
| Implement activate/publish | You are willing to mislabel Phase 6 work as Phase 1 |
| Flip registry to `approved` without R1 | Forbidden |
| Flip rollup paid/HO checkbox | Phases 2–4 + G1–G4 are actually done |
| Credit PR #29 as Phase 1 done | Ceremony file is signed without that lie |
| Merge a plan whose DoD is “tests pass” | Rewrite DoD to artifacts + ceremony |

---

## Round 2 process note

- Round 1 produced five rich lanes (Critic, Registry, MCP, UI, Sign-off).
- Round 2 **merged** them, cut vanity, fixed Critic unlock language to **G1 Phase-1 cell only**, and fixed DoD to **honesty + ceremony artifacts**.
- Further planning rounds have **diminishing returns**: implement Wave A–B immediately; only reopen this plan when acceptance file reality, MCP startup proof, or Phase 5 G1 status changes.

---

## Key file touch list

**Claims / ceremony:** `docs/PHASE1_GAP_CLOSURE_PLAN.md` (this file), `eval/PHASE_1_ACCEPTANCE.md` (new), `eval/PHASE_1_4_ACCEPTANCE.md`, Phase 1 rows in claim matrix / evidence index, `docs/PHASE1_CODE_WALKTHROUGH.md`, `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md`, stale MCP sentences in `docs/END_TO_END_IMPLEMENTATION_PLAN.md`.

**Registry:** `src/rules/fact_registry.json`, `src/rules/bundle_registry.json`, `src/rules/packages/ignwps_mh.v1.json`, `pmkisan_in.v1.json`, `docs/PHASE1_PILOT_PIN_EVIDENCE.md`, `docs/checklists/PHASE1_*_REVIEW_TEMPLATE.md`, existing rule reviews under `docs/`.

**MCP:** `src/mcp_servers/*_server.py`, `src/api/app.py` lifespan, `docs/MCP_TOOL_INVENTORY.md`, `docs/MCP_PERMISSIONS_WALKTHROUGH.md`, `tests/test_mcp_services.py`, `tests/test_mcp_permissions.py` (+ new startup mismatch test).

**UI:** `src/ui/app.py`, LOCAL evidence pack (screenshots/notes; may live outside git), checklist rows in `PHASE_WISE`.

**Explicit non-touches for Phase 1:** Phase 6 BN activate paths, Azure runbooks, MEMORY_POLICY / E1–E4 paid harnesses, Playwright-as-blocker suites, real portal.

---

*PDF wins on conflicts. Team decisions (15-minute approval TTL, Gate B Done-when checklist, EN-first language residual, APY pending vs approve) must be attributed as team decisions — not invented as PDF quotes. Phase 1 sign-off is necessary but not sufficient for paid Phase 5.*
