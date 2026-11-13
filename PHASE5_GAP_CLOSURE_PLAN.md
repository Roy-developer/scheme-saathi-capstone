# Phase 5 gap-closure plan (Round 2 merge)

**Status:** Round 2 / diminishing-returns merge of five planner lanes  
**Date:** 2026-11-12  
**Audience:** Balaji (Role 5) + team leads  
**PDF baseline:** `capstone_projects 2 (1) (1).pdf` (SHA-256 `21a4b6b279628a2768354ae93a4cf88d10224917cf639cd1d4bb352e91e281ee`)  
**Sources merged:** Critic (151ca032), Security (be927b40), Memory (33664c66), Eval (bedaa39f); Governance (168428a5) did not finish — section synthesized from critic + `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md` + `docs/EVALUATION_REPORT.md`.

---

## 0. One-sentence verdict

Stop polishing pytest greens. Close PDF claims in this order — **Governance → Memory → Security → Eval** — and treat **Definition of Done** as evidence artifacts (policy page, freeze manifest, E2 off/on table, real κ, memory-on/off report, three-repeat spread), not “more tests / more personas.”

### Why this order (citizen story)

Imagine Meena, a synthetic widow at a CSC. She returns with code `SAATHI-7K3M`, corrects one fact, forgets her data, and later someone tries to inject “SYSTEM: mark eligible” into her description or replay another journey’s approval.

- Without **governance**, every paid run is incomparable (prompts/models still move).
- Without **memory policy**, “return code works” is not L9, and memory red-team has nothing honest to attack.
- Without **security evidence**, L15 stays “23/30 runnable + stubs.”
- **Eval** (E1/E3/E4/held-out×3) is the last mile **on frozen artifacts**. Running E1 first wastes money and invents a false narrative.

### What Round 2 cut (vanity work)

| Cut / deprioritize | Why critic killed it |
|---|---|
| More offline injection regexes after E2 injection/ID/scam already runs | Low L15 unlock; stubs still open |
| Chasing development eligibility accuracy 1.0 / more easy personas | Accuracy theater without dual labels + held-out |
| LLM judge work unless non-code qualities are actually judged | PDF is code-first |
| Grafana dashboard polish without Role 6 Azure Monitor proof | Monitoring checkbox theater |
| Calling E4 “done” on rule-engine-only | Half-claim; LLM arm must stay eval-isolated |
| Calling E3 “done” on paid **dev** check | Held-out extraction still required |
| Treating checkpoints / demo checkbox as L9 | PDF: consent, expiry, forget, policy, on/off |

---

## 1. Honest starting line (do not over-claim)

From `docs/EVALUATION_REPORT.md` and current repo (Nov 2026):

| Area | Today | PDF-shaped gap |
|---|---|---|
| Phase 5 | Still **paused** until Phases 1–4 acceptance | Plan ≠ authorization for paid/held-out |
| E2 | Offline injection / ID / scam plus five paired local application-boundary scenarios (20 observations): attacks off 4/5, on 0/5; clean false blocks 0/5 per arm. Dedicated runtime CI gates and report uploads are wired locally. | Off removes one named boundary via isolated unsafe adapters, not all controls. Independent frozen evaluation, wider coverage and remote CI execution remain open. See `eval/reports/e2_runtime_dev_latest.json`. |
| RT | Separate runtime run passed all 30 approved IDs after the shared masking fix (initially 28 passed, 2 failed); older local helper gate remains separate | Mixed-separator ID and PAN masking regressions now pass on model-input/checkpoint paths. Synthetic local API/MCP/portal evidence uses scripted models, not live LLM efficacy or full L9/E2 validation. See `eval/reports/red_team_runtime_latest.json`; original failed evidence is retained separately. |
| κ | Harness ready; `smoke_copy` | Role 1 independent labels required |
| E1 | Config inventory / stub | No forced-C0; no C1 arm; no freeze trio |
| E3 | Paid **dev** check inventory | Held-out extraction before/after open |
| E4 | Rule-engine partial | Isolated LLM + question-order missing |
| Memory | Return-code store | No MEMORY_POLICY, consent, expiry, unified forget, on/off |
| Held-out | Generator + local folder | **`eval/held_out/local/personas_held_out_v1.json` is staged (`A`)** — exposure risk |
| Gold schemes | 4 live packages (incl. APY mock) | Not 15 gold; do not imply otherwise |
| Monitoring | OpenTelemetry instruments + Azure Monitor export | Managed Grafana dashboards/alerts = Role 6 / Phase 6 handoff |

---

## 2. Roles (RACI for this roadmap)

| Role | Accountable for | Must not do |
|---|---|---|
| **R1 Domain** | Dual labels; held-out vs written policy check; MEMORY_POLICY field justification review; TTL team decision sign-off | Author final RT attacks; tune from held-out |
| **R2 Knowledge/memory** | `MEMORY_POLICY`, LTM schema, privacy filter, consent/expiry/correction/forget product | Author final RT; claim L9 without on/off report |
| **R3 Orchestration** | Forced-C0 flag; C1 eval arm; fixed vs planned question order; STM trim | Read held-out; weaken approval/eligibility for “easier E1” |
| **R4 Tools/security** | Threat model accuracy; guardrail/quarantine/output/scope implementation; memory ACL hardening | Author **final** attack evidence |
| **R5 Eval/RT (Balaji)** | Held-out custody; attack authorship; E1–E4 harness/reports; claim matrix honesty; memory-on/off harness | Let builders read HO; defend with defender-authored attacks |
| **R6 UI/ops** | Consent/forget UI copy; referral UX; Managed Grafana dashboards and alerts in shared env | Own final eval claims or held-out |

**Separation of duties (PDF non-negotiable):** defender ≠ attacker; tuner ≠ held-out author. Exposure → reclassify/replace + disclose.

---

## 3. Master sequence — five waves

Effort: **S** ≈ 1–2 days, **M** ≈ 3–5 days, **L** ≈ 1–2 weeks. Priority: **P0** claim-blocking, **P1** full-bar, **P2** polish / Phase 6 handoff.

### Wave 0 — Stop the bleed (same day / P0)

| ID | Work | Owner | Effort | DoD (artifact) |
|---|---|---|---|---|
| **G0a** | **Unstage** `eval/held_out/local/**`; confirm gitignore + CI/image never ship it | R5 | S | `git status` clean of HO personas; note in claim matrix |
| **G0b** | Reconcile persona counts (31 vs 43 / APY) in `EVALUATION_REPORT.md` + `eval/README.md`; APY ≠ gold progress | R5 | S | Docs match harness; explicit non-claim on 15-gold |
| **G0c** | Draft **claim matrix** (requirement → artifact → owner → `not claimable` / `dev-only` / `ready`) | R5 | S | One table covering L9/L12/L13/L15 + E1–E4 |
| **G0d** | Pre-register thresholds **before** peeking scores (team decision log; PDF gives few numbers) | R1+R5 | S | Dated threshold note linked from report |

**Kill:** stop when HO is unstaged, counts honest, matrix exists. Do not invent numeric bars the PDF does not state.

**Scenario:** If a teammate opens the staged held-out file to “debug eligibility,” those cases become development and the PDF held-out claim dies until replaced. Wave 0 exists to prevent that accident.

---

### Wave 1 — Governance / freeze / unpause honesty (P0)

Phase 5 stays paused for **paid + final held-out** until this wave’s freeze contract exists. Design/docs/offline tests may proceed.

| ID | Work | Owner | Effort | DoD |
|---|---|---|---|---|
| **G1** | **Unpause criteria checklist** (Phases 1–4 acceptance items still open called out honestly) | R1 lead, all | M | Signed checklist: what is accepted vs still open |
| **G2** | **Freeze manifest** pinning: model IDs, `PROMPT_VERSION`, tool allowlists, budgets, registry/bundle hashes, playbook version/hash | R3+R5 | M | `eval/freeze/` or report header with hashes; same pins across C0/C1/C2 and E3 before/after |
| **G3** | Independent attack authorship process note + `author` / `reviewed_by` metadata | R5 (+ R4 ack) | S | Process note under `eval/red_team/`; no defender-final-attacks |
| **G4** | Held-out secrecy protocol (Role-5-only path, regenerate policy, exposure → reclassify) | R5 | S | Written protocol + README in `eval/held_out/` |
| **G5** | EVALUATION_REPORT hygiene: §8 non-claims stay until closed; no stub inflation | R5 | S | Report language matches inventory statuses |
| **G6** | Monitoring handoff pack for Role 6 (metric names, alert, dashboard JSON) — **do not claim Grafana live** | R5→R6 | S | Handoff note; claim stays “OTel instruments emitted” until Azure Monitor export proven |

**Freeze manifest must pin**

1. Model id(s) and provider  
2. Prompt / middleware versions  
3. Tool allowlists per arm  
4. Budget ceilings (calls/tokens/cost)  
5. Registry + scheme bundle content hashes  
6. Reflexion playbook version + hash  
7. Attack suite version  
8. MEMORY_POLICY version (once L9 exists)

**Unpause = authorize paid E1/E3/E4 and final HO runs** only when G1–G4 are real. Unpause does **not** mean “all Phase 5 product is finished.”

**Kill:** freeze IDs recorded; every L9/L12/L13/L15/E1–E4 row is claimable or explicitly not; thresholds pre-registered. Keep going only if someone still treats paused Phase 5 as “authorized paid eval.”

---

### Wave 2 — Memory L9 (P0 partial → P1 full)

Return-code store ≠ PDF L9. Close product semantics before memory RT and memory-on/off.

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **M0** | `docs/MEMORY_POLICY.md` (≤1 page): what/when/who/correct/delete; TTL **team decision**; demo consent ≠ memory consent | P0 | R1+R2 | S–M | Policy file + version stamp |
| **M1** | LTM schema: consent, `expires_at`, policy_version, stored fact ids; fail-closed on legacy records | P0 | R2 | M | Schema + migration note |
| **M2** | PrivacyPolicy enforce on save/load; deny unknown/pending fields; no highly sensitive IDs in LTM | P0 | R2+R4 | M | Tests: pending fact never persists |
| **M3** | Explicit memory consent API + UI (EN/HI/MR) | P0 | R2+R6 | S–M | Save without consent → 4xx |
| **M4** | Expiry enforcement + clock-injected tests | P0 | R2 | M | Expired code behaves as unknown |
| **M5** | Scoped correction → LTM (patch one fact only) | P1 | R2+R3 | M | Return session sees corrected value only |
| **M6** | Unified forget-me (journey **and** household LTM) | P0 | R2+R3+R6 | M | One UI path; A gone, B intact |
| **M7** | STM trim/summarize for growing checkpoint lists | P1 | R3 | M–L | Before/after size evidence; resume still works |
| **M8** | Memory-on vs memory-off harness + report | P1 | R5 (+R2 seeds) | M–L | `eval/reports/memory_on_off_*.json` + metrics |
| **M9** | Threat ASI06 rewrite + enable RT-MEMORY after store is governed | P1 | R4 doc / R5 attacks | M | ASI06 matches `household_memory.py` |
| **M10** | L9 evidence pack linked from evaluation report | P1 | R5+R2 | S | Policy + on/off + forget demo |

**Partial claim (M1 milestone):** after M0–M4 + M6 — “Governed household store with consent/expiry/forget; trim + on/off still open.”  
**Full L9 (M3):** all of M0–M10.

**Memory-on/off metrics (minimum):** questions asked / fact reuse; verdict match; corruption after correction = 0; policy violations = 0; cross-household leak = 0; forget completeness; optional cost/latency. Do **not** require memory-on to “win” accuracy.

**Kill:** one-page policy + consent/expiry/forget demo + one on/off comparison. Stop endless unit tests that do not move those artifacts.

**Scenario (gap today):** Meena corrects `is_widow` in session A; session B with the same return code can reload the old value because LTM is not patched. M5 closes that. Unified forget today deletes journey **or** household, not both — M6 closes the PDF “deletes all of it” sentence.

---

### Wave 3 — Security L15 / E2 (P0 partial → P1 full)

Order inside wave (from security lane, critic-aligned):  
**S1 → S2 → easy stubs → E2 eligibility → own-data → hard memory/approval stubs → full E2 → output/scope → evidence pack.**

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **S1** | Authorship process (may overlap G3) | P0 | R5 | S | Authorship record |
| **S2** | Rewrite ASI06 for household memory (coord with M9) | P0 | R4 | S | Threat model matches code |
| **S3a** | Wrap easy stubs: RT-MEMORY-002, RT-OTHER-001/002 | P0 | R5 | M | Runnable via existing isolation/approval/authority tests |
| **S3b** | Hard stubs: RT-MEMORY-001/003, RT-INFLATE-001, RT-OTHER-005 | P1 | R5+R4 | L | `stub_skipped: 0` for claimed set |
| **S4** | Extend E2 beyond injection/ID/scam; include eligibility_truthful + memory/approval toggles (**eval-only**) | P0–P1 | R5 | M–L | Mode string honest; ASR off/on + false blocks |
| **S5** | Own-data-path attack (quarantined description) | P0 | R5 (+R4 if gap) | M | ≥1 RT exercising intake quarantine path |
| **S6** | Out-of-scope input + output grounding/leak scrub | P1 | R4 impl / R5 attacks | L | Clean cases; false-block reported |
| **S7** | Evidence pack + CI fails on stubs / false-block regressions | P1 | R5 | S–M | Report §3/§8 updated; inventory unblocked |

**Partial L15 wording allowed early:** offline E2 for injection/ID/scam; authorship noted; ASI06 refreshed; easy stubs wrapped; own-data wired.  
**Do not claim full L15** until S3b–S7 done.

**Kill:** threat-model page; ≥30 executed attacks with independent authorship; memory/approval not stubs; E2 table with ASR off/on + false-block; ≥1 own-data-path. Stop climbing offline injection accuracy while stubs remain.

**Scenario for closed:** attacker plants SYSTEM text in Meena’s description, tries under-report age, guesses another return code, replays approval, skips approval, asks out-of-scope, posts scam fee lure. Defences **off** (eval-only): ASR rises on toggled layers. Defences **on**: attacks fail; “I get pension by UPI” stays clean. Role 5 wrote attacks Role 4 did not.

---

### Wave 4 — Evaluation E1–E4 / personas / κ / repeats (P0 hygiene → P1 claims)

Eval runs **after** freeze (Wave 1) for any PDF-facing number. Dev exploratory C0 can start earlier with soft freeze.

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **E0** | Done in Wave 0 (HO unstage + count honesty) | P0 | R5 | S | — |
| **E1** | Forced-C0 harness (deterministic path pinned) | P0 | R3+R5 | M | C0 runnable report ≠ “whatever live graph did” |
| **E2** | C0 vs C2 under same freeze pins | P1 | R5 | M | Paired tables + freeze IDs |
| **E3** | C1 single-agent eval arm + full E1 trio | P1 | R3+R5 | L+M | Three arms; safety/approval preserved |
| **E4** | Dual-label κ (`smoke_copy: false`); journey-facing simulated citizen | P0–P1 | R1+R5 | M+L | Real κ; disagreements listed |
| **E5** | E4: isolated LLM eligibility (shadow only) + planned vs fixed questions | P1 | R3+R5 | L | Isolation tests; both ablations scored |
| **E6** | Held-out ≥40; eligibility + E1/E4; **three repeats + spread** | P1 | R5 (+R1 policy) | M+L | Spread table; no HO in git |
| **E7** | E3 Reflexion **held-out** extraction before/after + cost + rejected lesson | P1 | R5 / independent owner | M–L | HO deltas ≠ only `scored_paid_dev_check` |
| **E8** | E1/E4 preserve defences; log guardrail hits | P1 | R5 | S | Policy signals in traces |
| **E9** | Gold honesty: score 4 live packages; 15-gold is data workstream | P0 | R5 (report) | S | Coverage matrix; non-claim |

**Suggested one-line eval order:**  
forced-C0 → C0 vs C2 → C1 trio → dual-label κ → E4 isolations → held-out×3 → E3 HO extraction. **E1 full trio last among experiments for money.**

**Kill per slice**

| Slice | STOP when |
|---|---|
| Labels | Role 1 independent labels; κ with method |
| E3 | Frozen playbook + rejected lesson + before/after (dev then HO) + cost/regressions |
| E4 | Isolated non-authoritative LLM path + boundary errors + planned vs fixed |
| E1 | One frozen C0/C1/C2 run with shared budget + safety preserved |
| Repeats | Three HO runs + spread (not fourth+ for comfort) |

**Global kill:** further changes would break freeze or peek held-out → STOP, reclassify, disclose.

---

## 4. Claim matrix (working template)

Fill statuses as waves close. Default today: **not claimable** unless noted.

| PDF / experiment | Required artifact | Owner | Status (start) |
|---|---|---|---|
| L9 Memory | MEMORY_POLICY + on/off report + consent/expiry/forget | R2/R5 | not claimable |
| L12 Reflexion | HO before/after + rejected lesson + playbook hash | R5 | dev-only (paid check) |
| L13 personas/κ | ~20 dev + ≥40 HO, dual labels, real κ | R1/R5 | not claimable (smoke κ) |
| L13 monitoring | Dashboard + alert demonstrated | R6 (+R5 metrics) | partial (OTel instruments only; no Azure Monitor or Grafana proof) |
| L15 threat + RT + E2 | Threat model; 30 executed; ASR off/on; false blocks; own-data | R4/R5 | partial (offline subset) |
| E1 | Freeze + C0/C1/C2 tables | R3/R5 | not claimable |
| E2 | Full category off/on incl. memory/approval | R5 | partial |
| E3 | HO extraction before/after | R5 | not claimable for PDF |
| E4 | Isolated LLM + question order | R3/R5 | partial (rules only) |
| 3× HO spread | Spread table | R5 | not claimable |

---

## 5. What NOT to claim (until green)

1. “E1 complete / team justifies cost” — until forced-C0 + C1 + C2 under freeze on held-out.  
2. “C0 baseline measured” — until forced-C0 harness exists.  
3. “60 personas ready” — until ~20/≥40 split + dual labels; 43 file rows ≠ bar.  
4. “κ done” — while smoke copy.  
5. “E4 done” — while LLM isolation or question-order null.  
6. “E3 proved” — on paid **dev** alone.  
7. “Held-out validated” — until 3× spread, R1 policy check, **and** no staged HO file.  
8. “Simulated citizen evaluation” beyond smoke.  
9. “15 gold / extraction signature closed” with 4 live packages.  
10. “Full L15” from offline injection/ID/scam alone.  
11. “L9 long-term memory” from return-code / checkpoints alone.  
12. “Grafana/monitoring complete” from OTel instrument definitions alone.

---

## 6. Balaji (Role 5) — first 2-week concrete backlog

Assume parallel teammates on R1/R2/R3/R4; Balaji drives eval integrity and unblocks others.

### Days 1–2 (Wave 0 + governance start)

1. **Unstage** `eval/held_out/local/personas_held_out_v1.json` (and keep local-only). Confirm ignore rules.  
2. Fix report/README persona-count drift; mark APY as mock package boundary, not gold.  
3. Publish **claim matrix** v0 in this doc or `docs/EVALUATION_REPORT.md`.  
4. Write `eval/red_team/` authorship process note (S1/G3).  
5. Write held-out secrecy protocol (G4).  
6. Sketch freeze manifest schema (even if hashes fill later).

### Days 3–5 (partial security + memory eval design)

7. Wrap **easy** RT stubs into harness check kinds (MEMORY-002, OTHER-001/002).  
8. Add **own-data-path** RT wired to quarantine assertions.  
9. Extend E2 to score `eligibility_truthful` off/on (document toggle carefully).  
10. Review/partner on MEMORY_POLICY draft (AC review only — R2 authors).  
11. Design `memory_on_off` seed JSON from development persona FACTS (6–12 cases); **do not** run paid comparison yet.

### Days 6–8 (forced-C0 + κ path)

12. With R3: land **forced-C0** flag + first `evaluate_e1` C0-only development run (exploratory; soft freeze).  
13. Kick R1 dual-label pack for development (process + template); refuse smoke κ in any “submission” language.  
14. Refresh ASI06 review comments for R4 (memory threats).  
15. Update `experiments_inventory.json` blockers to match reality (no silent “ready”).

### Days 9–10 (close partial packs)

16. Promote remaining stubs that no longer need product gaps; list blockers for hard MEMORY/INFLATE.  
17. Wire CI: fail Role-5 gate if claimed suite still has `stub_skipped > 0` **once** you declare the partial suite frozen.  
18. Draft memory-on/off report skeleton columns (questions, verdict match, leaks, forget).  
19. Pre-register thresholds for false-block and E1 success **before** held-out.  
20. Produce short status: what is `dev-only` vs `not claimable` vs newly `ready`.

### Explicitly not in Balaji’s first 2 weeks

- Full E1 trio on held-out (needs C1 + hard freeze + labels).  
- Paid E3 HO extraction (needs corpus + freeze + budget approval).  
- Fourth round of injection regex polish.  
- Claiming Grafana live (Role 6).  
- Expanding to 15 gold schemes (data workstream).

---

## 7. Parallelization map (safe concurrency)

```text
Wave 0 (R5) ─────────────────────────────────────────────┐
Wave 1 freeze/claim (R5+R1+R3) ──────────────────────────┤
         │                                               │
         ├─ Wave 2 Memory product (R2/R4/R6) ────────────┤
         │         └─ M8 on/off (R5) after M1+           │
         ├─ Wave 3 Security (R5 attacks / R4 defences) ──┤
         │         hard MEMORY RT after M1+              │
         └─ Wave 4 Eval arms (R3 force-C0/C1; R5 harness)┤
                   dual labels (R1) in parallel           │
                   paid HO only after freeze + Wave 0    │
Role 6 Grafana / referral UX ──────────── P2 / Phase 6 ───┘
```

**Safe now without unpause:** Wave 0, authorship, ASI06 draft, MEMORY_POLICY, schema design, offline unit tests, forced-C0 **dev** scaffolding, R1 labeling of **development**, easy RT wraps.  
**Not safe yet:** paid held-out E1/E3/E4; tuning from HO; defender-authored final attacks.

---

## 8. Definition of Done = PDF evidence artifacts

A wave is done when these exist and match the claim matrix — **not** when “tests pass.”

| Wave | Evidence pack |
|---|---|
| 0 | Clean index (no HO personas); honest counts; claim matrix v0 |
| 1 | Freeze manifest; unpause checklist; authorship + HO protocol; report non-claims |
| 2 | MEMORY_POLICY; consent/expiry/forget demo; memory-on/off report (full L9) |
| 3 | Threat model; RT suite executed; E2 off/on + false blocks; own-data; authorship |
| 4 | Real κ; E1 trio under freeze; E4 both arms isolated; E3 HO; 3× spread |

**Closed for final review (story):** Meena’s journey is comparable under pinned configs; her memory is consented and erasable; attacks Role 5 wrote fail with defences on; C0/C1/C2 cost tables exist; Reflexion and signature ablations are held-out honest; three repeats show spread — and the report says clearly what is still out of scope (15 gold, live Grafana if not connected to Azure Monitor).

---

## 9. Stop-polish kill criteria (post this on the wall)

| If you are about to… | Stop unless… |
|---|---|
| Add more injection patterns | A memory/approval stub or own-data E2 row is still open |
| Add more easy personas | Dual labels / HO secrecy still broken |
| Re-run E1 for a prettier cost curve | Freeze would change or HO would be peeked |
| Call L9 done after checkpoint tests | Policy + on/off artifacts missing |
| Call E4 done after rule accuracy | LLM shadow path missing |
| Call E3 done after dev check | HO extraction missing |
| Claim monitoring done | Role 6 has not demonstrated Azure Monitor data or a Grafana alert |
| Merge a plan whose DoD is “tests pass” | Rewrite DoD to artifacts first |

---

## 10. Round 2 process note

- Round 1 produced four rich lane plans + an incomplete governance agent.  
- Round 2 **merged** them into one sequenced roadmap, cut vanity work, and fixed DoD to PDF artifacts.  
- Further planning rounds have **diminishing returns**: implement Wave 0–1 immediately; only reopen this plan when freeze reality or Phase 1–4 acceptance status changes.

---

## 11. Key file touch list (by wave)

**Governance / eval hygiene:** `docs/EVALUATION_REPORT.md`, `eval/README.md`, `eval/held_out/README.md`, `eval/reports/experiments_inventory.json`, new freeze/claim artifacts, `eval/red_team/` authorship note.

**Memory:** `docs/MEMORY_POLICY.md` (new), `src/workflow/household_memory.py`, `src/workflow/journey.py`, `src/api/app.py`, `src/ui/app.py`, `docs/THREAT_MODEL.md`, `eval/harness/memory_on_off_runner.py` (new).

**Security:** `eval/red_team/attacks_v0.json`, `eval/schema.py`, `eval/harness/red_team_runner.py`, `eval/harness/e2_runner.py`, `src/workflow/input_guardrails.py`, output guard module, `docs/THREAT_MODEL.md`.

**Eval arms:** `eval/experiments/e1_*.json`, `e4_*.json`, new `e1_runner` / `e4_ablation`, `src/workflow/journey.py` / `agent_runtime.py` (force C0, C1, question order), isolated eval-only LLM eligibility path, `scripts/evaluate_*`.

---

*PDF wins on conflicts. Team decisions (household TTL, numeric false-block thresholds, C1 design) must be attributed as team decisions — not invented as PDF quotes.*
