# Phase 6 gap-closure plan (Round 2 merge)

**Status:** Round 2 / diminishing-returns merge of five planner lanes  
**Date:** 2026-11-12  
**Audience:** Role 6 (UI/ops) primary + Balaji (Role 5) for claim honesty / CI / evidence pack  
**PDF baseline:** `capstone_projects 2 (1) (1).pdf` (SHA-256 `21a4b6b279628a2768354ae93a4cf88d10224917cf639cd1d4bb352e91e281ee`)  
**Sources merged:** Critic (b95db1db), Monitoring (8264b12e), Deploy (b8df27bc), Streaming/CI/evidence (a1df5107), Bundle (a05fde21).  
**Team demo constraint:** Azure-only final demo — FE+BE Container Apps; App Insights + Managed Grafana already initiated; Compose Prometheus is **not** demo acceptance (document equivalent). Cost-effective metrics-first.

---

## 0. One-sentence verdict

Close Phase 6 PDF honesty in this order — **Deploy → Monitoring → Streaming/CI/evidence → Bundle last** — and treat **Definition of Done** as Azure-proven artifacts (runbooked revision, five live Grafana panels, one fired can't-tell alert, streaming without leaks, ratified failing CI, Hindi-widow Azure demo, then complete-bundle stage/activate), not JSON theater, PR #29 merge credit, or “Container Apps exist.”

### Why this order (citizen / viva story)

Imagine Meena, a synthetic widow, at a CSC on demo day. The examiner opens the **public Azure UI URL**, not a laptop Compose stack.

- Without **deploy topology + runbook**, monitoring and evidence packs float (wrong revision, missing secrets, MCP/portal cold-start surprises).
- Without **live Azure monitoring**, L13/L16 ops claims stay “`/metrics` JSON + alerts.yml recipe.”
- Without **streaming + CI fail artifact + evidence pack + language/UI drills**, L16 streaming / threshold / submit-list items stay open even if Grafana looks pretty.
- **Bundle publish/rollback** is the highest product risk for mixed versions / restored approvals, but it must **not** block the ops screenshot triangle. Design in parallel; **sign-off last**.

### What Round 2 cut (vanity work)

| Cut / deprioritize | Why critic killed it |
|---|---|
| Grafana JSON polish without live Azure datasource | Dashboard theater |
| Second/third alerts, SLOs, conversation-duration panel, FinOps depth | PDF asks five panels + one unknown-rate alert |
| Compose Prometheus scrape of public ACA `/metrics` “to match L16 literally” | Cost + ingress risk; team Azure equivalent already chosen |
| Separate Container Apps for MCP / portal / Qdrant unless verify fails | Idle spend; in-BE topology already designed |
| Claiming PR #29 / OTEL scaffolding = Phase 6 done | Snapshot inventory, not Azure proof |
| Softening CI thresholds after a red run | Fake gate |
| Evidence-pack / slides first | Invents completion before operable demo |
| Bundle-first as ops blocker | Delays the three screenshots + failing CI |
| Writable hot packages on file share / multi-replica SQLite | Breaks scale-to-zero + WAL rules |

---

## 1. Honest starting line (do not over-claim)

From `docs/MONITORING.md`, Phase 6 section of `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md`, and lane inventories (Nov 2026):

| Area | Today | PDF-shaped gap |
|---|---|---|
| FE / BE hosting | Azure Container Apps exist (`scheme-saathi-ui` / `scheme-saathi-api`) | Hosting ≠ L16 clean-install / full-stack proof |
| MCP ×4 + mock portal + vectors | Spawned **inside BE** (stdio + in-memory Qdrant) | Must **verify** on Azure cold start; not separate CAs |
| Persistence | Live SQLite on container disk; periodic backup to `/mnt/saathi-runtime`; **one BE replica** | Azure revision / scale-to-zero **resume** not yet the proof of record |
| Monitoring code | `GET /metrics` + dashboard JSON + `alerts.yml`; App Insights / Managed Grafana **initiated** | No viva claim until custom metrics + five panels + **fired** alert |
| Metric honesty | Verdict re-count skew; pending gauge in-memory; cost incomplete; some mask paths miss counters | Panels on lies = worse than sparse honest panels |
| Streaming | Upload body streaming only; **no** journey SSE / safe progress events | L16 FastAPI streaming open |
| CI eval gate | `frontend-checks.yml` runs `scripts/run_role5_dev_evals.py` (fails on bad metrics) | Thresholds not ratified; **no kept failing-run + explanation** |
| Deploy workflows | Validate compile/pytest; Role 5 evals **not** re-run on deploy | Do not claim “eval-gated deploy” until policy + wiring match |
| Bundle publish | Phase 4 **single-file** checklist/form + filelock + monotonic revision | **No** atomic complete-bundle stage→validate→activate |
| MEMORY_POLICY | Missing (Phase 5 Wave 2) | Evidence pack may only **link** when real; do not invent |
| Languages / flagship demo | Contracts + offline/AppTest; EN-heavy | Hindi widow → approved mock draft + CSC/Citizen + forget on Azure still open |
| Compose | Dev/historical L16 wording | **Not** final demo acceptance |

**PR #29 note:** Treat as instrumentation inventory (dual Prom/OTEL path if/when merged). It is **not** Phase 6 closed.

---

## 2. Roles (RACI for this roadmap)

| Role | Accountable for | Must not do |
|---|---|---|
| **R1 Domain** | Demo narrative; HI/MR wording sign-off; meaning of **approved** bundle activate; threshold ratification (with R5) | Treat deploy smoke as policy approval; invent PDF numeric bars |
| **R2 Knowledge/memory** | Bundle content packing; MEMORY_POLICY substance (Phase 5) | Silent answer conversion across meaning changes |
| **R3 Orchestration** | Streaming contract + API; checkpoint resume coherence; reconfirm latch under activate | Stream model reasoning / tool guts; bypass latch for “smooth demo” |
| **R4 Tools/security** | Publish lock / malformed reject; least-privilege (portal/MCP not public); stream PII review | Multi-replica share writers; expose applicant facts in diagnostics |
| **R5 Eval/RT (Balaji)** | Claim matrix honesty; CI threshold ratification + failing-run artifact; 4–6p report; monitoring semantics / M4 accuracy; evidence index | Claim Grafana/alert from JSON alone; soften gates after red runs; invent held-out completion |
| **R6 UI/ops** | Azure inventory, runbook, secrets, cost scale-to-zero, App Insights wire, Managed Grafana panels/alert, Azure resume/CSC/delete drills, image install root, CI 3.12 platform proof | Own final eval claims; resurrect Compose as demo acceptance |

**PDF conflict rule:** Capstone PDF wins on **evidence classes** (L13 dashboard + traces intent; L16 streaming, deploy story, CI threshold, one working alert). Team decision wins on **where** demo evidence lives: Azure Container Apps + App Insights + Managed Grafana. Say the Compose→Azure equivalent out loud — do not silently rewrite the PDF.

---

## 3. Master sequence — five waves

Effort: **S** ≈ 1–2 days, **M** ≈ 3–5 days, **L** ≈ 1–2 weeks. Priority: **P0** claim-blocking, **P1** full-bar, **P2** polish.

**Critic merge order (fixed):** Deploy → Monitoring → Streaming/CI/evidence → Bundle last.

```text
Wave 0  Claim freeze + Compose→Azure map
Wave 1  Deploy / runbook / secrets / Azure resume
Wave 2  Monitoring (App Insights → Managed Grafana + one alert + M4 honesty)
Wave 3  Streaming + CI fail artifact + UI/language drills + evidence pack
Wave 4  Complete-bundle stage/activate (sign-off last; design may parallel earlier)
```

---

### Wave 0 — Stop the bleed / claim freeze (same day / P0)

| ID | Work | Owner | Effort | DoD (artifact) |
|---|---|---|---|---|
| **D0** | Freeze Phase 6 claim matrix: requirement → Azure artifact → owner → `not claimable` / `partial` / `ready` | R5+R6 | S | One table covering L13 ops + L16 + New Phase 6 bundle gate |
| **D0b** | Write **Compose→Azure equivalent** one-pager (L16 intent map) | R6 (R5 narrative C) | S | Mapping table linked from README / runbook; explicit non-claim of literal Compose demo |
| **D0c** | Monitoring claim freeze: Azure Managed Grafana + App Insights = demo acceptance; local `/metrics` = developer proof only | R5+R6 | S | Paragraph in `docs/MONITORING.md` matching reality |
| **BN0** | Bundle gate inventory: single-file ≠ complete-bundle; choose activate strategy (image bake vs share stage) | R5+R6 (R4 C) | S | Dated non-claim; Azure path decision written **before** coding activate |

**Compose→Azure map (minimum rows)**

| L16 / Compose role | Azure-demo equivalent |
|---|---|
| `docker compose up` | Deploy frozen commit to FE+BE Container Apps + warm-up |
| App UI + API | `scheme-saathi-ui` + `scheme-saathi-api` |
| MCP servers | Four stdio children inside BE |
| Vector store | In-memory Qdrant inside `schemes-kb` |
| Prometheus | BE emission → App Insights custom metrics (local `/metrics` optional) |
| Grafana | Azure Managed Grafana |
| One working alert | Managed Grafana **or** Azure Monitor alert (one only) |
| Clean-machine | Clean browser + public URLs on frozen revision |
| Failed CI | Kept Actions fail URL + explanation (Wave 3) |

**Kill:** stop when matrix + Compose→Azure map + monitoring claim language exist. Do not start panel cosmetics or activate coding before D0b/BN0 decisions.

---

### Wave 1 — Deploy / runbook / topology (P0)

Stable Azure revision and secrets unlock every later screenshot.

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **D1** | Full-demo Azure inventory (verify-or-deploy): FE, BE, MCP×4, portal, vectors, file share, App Insights, Managed Grafana | P0 | R6 | M | Signed inventory in runbook; **no** extra CAs unless verify fails |
| **D2** | Clean Azure demo runbook (not local): RG/env, trusted deploy, warm-up, URLs, rollback, cost kill-switch | P0 | R6 | M | Stranger-on-team can reach known-good revision; rehearsal log with revision IDs |
| **D3** | Secrets/config audit: OpenRouter + App Insights on **BE only**; UI has API URL only; never bake keys in image | P0 | R6 (R4 C) | M | Checklist set/missing/N/A; rotation sentence in runbook |
| **D4** | Health/revision strategy: `/health` + `/api/v1/info` + functional smoke; max 1 BE replica; single active revision; co-deploy FE/BE same tag | P0 | R6 | S–M | Readiness definition written; portal health stays internal |
| **D5** | Cost policy: scale-to-zero idle; min=1 only in demo window; no idle Prometheus/Grafana/MCP CAs | P0 | R6 | S | Idle=0 / demo=1 written and applied |
| **D6** | Azure **revision-resume** proof: mid-journey recycle or scale-to-zero+wake; answers return | P0 | R6 (R3 if graph bug) | M | Dated evidence: SHA, revision, pass/fail notes |
| **D7** | Cold-start note: first search after wake may rebuild in-memory index; warm before live slot | P1 | R6 | S | Runbook warm-up step |

**Scenario (closed):** Demo morning Role 6 deploys a frozen commit, warms `/health` + one search, hands public UI URL to the presenter. Meena’s conversation survives a BE revision recycle because backup restore worked. Secrets are in Azure Portal, not git.

**Kill:** inventory + runbook + secrets + one Azure resume proof. Stop spinning new SKUs, second regions, or Compose-as-demo resurrection.

---

### Wave 2 — Monitoring L13/L16 ops (P0 partial → P1 full)

Needs Wave 1’s stable BE revision + App Insights secret.

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **M0** | (Done in Wave 0 as D0c) claim freeze | P0 | R5+R6 | S | — |
| **M1** | Wire/verify OTEL → Application Insights from BE Container App | P0 | R6 (R5 defines green) | M | Custom `scheme_saathi.*` series visible after controlled traffic; secret redacted evidence |
| **M2** | Managed Grafana: **five PDF panels** from live Azure traffic | P0 | R6 (R5 semantics A) | M | Questions; can't-tell rate; waiting approvals; masked-ID hits; cost/conversation |
| **M3** | One can't-tell / unknown-rate alert — **fire + clear** once | P0 | R6 (R5 threshold A) | M | Screenshots + rule text + team threshold + SHA/revision |
| **M4a** | Verdict once-per-new-result (fix re-count skew) | P0 | R5 | M | Offline: 3 turns same can't-tell → +1; Azure rate trustworthy **or** disclosed |
| **M4b** | Pending approvals from durable truth **or** single-replica caveat | P0–P1 | R5+R6 | M | Full or explicit partial on panel 3 |
| **M4c** | Cost/tokens completeness on main journey LLM paths | P1 | R5 | M | Panel labeled “estimated USD” |
| **M4d** | Masked-ID hits on live Azure Aadhaar-like paste | P1 | R5 | S–M | Panel increments |
| **M5** | Cost controls: metrics-first, low cardinality, one alert, short retention, no scrape CA | P0 | R6 | S–M | Written cost note |
| **M6** | Monitoring evidence pack (architecture, panels, alert, honesty table, Compose-equivalent sentence) | P0 | R5+R6 | S | Linked from claim matrix |
| **M7** | `/metrics` hygiene if public ingress (prefer unused for acceptance) | P1 | R6 | S | Note in MONITORING.md |

**PDF five panels (must map 1:1 in viva)**

1. Questions / chat  
2. Can't-tell / unknown rate (`need_more_information`)  
3. Waiting approvals  
4. Masked-ID hits  
5. Cost / conversation (estimate OK if labeled)

**Team threshold note:** `HighCantTellRate` >20% for 5m in `monitoring/alerts.yml` is a **team decision**, not a PDF number. PDF only requires a working unknown-rate jump alert.

**Partial claim allowed early:** App Insights shows custom metrics; some panels live; alert not yet fired; M4 gaps disclosed.  
**Do not claim full L13/L16 ops** until M1–M3 + M6, with M4a fixed or disclosed.

**Kill:** five live panels + one fired/cleared alert + honesty table. Stop after that — no second alert, no NOC, no Compose Grafana rebuild.

**Scenario (closed):** Three short Azure journeys move questions, spike can't-tell, leave one pending approval, increment masked-ID, show rough cost. Forced can't-tell storm fires the alert; normal traffic clears it. Examiner sees Managed Grafana, not empty JSON.

---

### Wave 3 — Streaming, CI, UI/language, evidence pack (P0 → P1)

Parallelize streaming build with CI ratification; evidence pack **documents** Waves 1–2, it does not invent them.

#### 3a — Streaming (L16)

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **S1** | Safe event contract (`stage_started`, `plan_updated`, `awaiting_user`, `verdict_ready`, `approval_required`, `error_safe`, `done`) — no reasoning / tool stderr / unmasked IDs | P0 | R3 (R4/R5 C) | S–M | Spec in `FRONTEND_CONTRACT.md` |
| **S2** | FastAPI streaming endpoint (SSE or equivalent) on same graph path; non-stream remains authoritative | P0 | R3 (R6 ingress C) | M–L | Works on Azure API; errors → `error_safe` |
| **S3** | UI consumes allow-listed events only; poisoned payload test | P0 | FE/R6 (R3 A) | M | Azure browser progress without raw guts |
| **S4** | Mid-stream disconnect → refresh resumes via checkpoint | P0 | R3+FE | S–M | Stream is not a second source of truth |

#### 3b — CI thresholds (L16)

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **C1** | Ratify **development** thresholds **before** further tuning (eligibility floor, RT fails=0, E2 ASR-on=0, false-block=0, …) | P0 | R5 R / R1 A | S | Dated signed note; PDF has no numeric cutoffs — team decision explicit |
| **C2** | Keep deliberately failing Actions run + written explanation | P0 | R5 (R6 C) | S | Public run URL + “what failed / why gate correct / how fixed without weakening” |
| **C3** | Document primary gate = `frontend-checks` Role 5 evals; optional “same SHA green before deploy” as **team policy** | P1 | R6 (R5 C) | S | README/evidence honesty; do not claim deploy eval-gated if only pytest runs |

#### 3c — UI ops + languages (Phase 6 checklist)

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **U1** | Azure resume drill mid-interview (complements D6; browser-facing) | P0 | R6 (R5 witnesses) | S | Named sign-off at commit SHA |
| **U2** | CSC presence + delete/forget manual matrix on Azure UI; retention limits stated | P0 | R1+FE (R6 env) | S | Human sign-off; scoped forget across stores |
| **L1** | Independent HI/MR language review (consent, CSC, forget, stream captions) | P1 | R1 A + reviewer | M | Signed review |
| **L2** | Same facts EN/HI/MR → same rule verdicts | P1 | R5 (R3 C) | S–M | Scripted or manual matrix |
| **L3** | Flagship: **Hindi widow → approved mock draft** + Citizen vs CSC + refuse under-report + scam screen + scoped forget | P0 | R1 A / R6 R | M | Recording or live checklist on Azure |

#### 3d — Final evidence pack (submit list)

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **Ev1** | Architecture redraw + numbered walkthrough matching **Azure** reality | P0 | R6+R3 (R1 A) | M | Viva figure; not Compose-only as sole path |
| **Ev2** | Threat model + MEMORY_POLICY **links** (policy content = Phase 5 R2) | P0 | R5 pack | S | Honest “pending” if L9 open — never fake policy |
| **Ev3** | Freeze **4–6 page** evaluation report (dev honesty; no invented HO) | P0 | R5 | M | Submission-length artifact |
| **Ev4** | Experiment log + keep CONTRIBUTIONS current | P1 | R5 (+ all rows) | S–M | Human-readable experiment narrative |
| **Ev5** | Slides + backup Azure demo recording (no secrets/PII) | P0 | R1 A / R6 R | M | Backup if live Azure hiccups |
| **Ev6** | Evidence index: PDF item → path/URL → owner → partial/full | P0 | R5 (R6 C) | S | One checklist including failing CI + Grafana screenshots |

**Three screenshots + failing CI (critic bar for ops honesty):**  
(1) Managed Grafana five panels with live series, (2) alert Fired after can't-tell spike, (3) alert Resolved — plus (4) Actions fail URL with explanation. Without these, do not say Phase 6 ops closed.

**Kill:** streaming without leaks on Azure; C1–C2 artifacts; L3 flagship path; Ev3+Ev6. Stop slide padding and threshold churn.

---

### Wave 4 — Complete-bundle gate (P0 for gate claim; sign-off last)

New Phase 6 gate from `docs/PHASE_WISE_IMPLEMENTATION_PLAN.md`: stage/validate/activate a **compatible complete bundle**; recover from partial publish/restart without mixed versions, lost receipts, or **restored old approvals**. Deploy remains a separate exact-commit step.

| ID | Work | Pri | Owner | Effort | DoD |
|---|---|---|---|---|---|
| **BN1** | Install root contract: registry + packages + checklist + evidence + forms; startup from packaged paths; safe bundle IDs on `/api/v1/info` (no PII) | P0 | R6+R4 (R2 content) | M | Clean container boots without git tree mount |
| **BN2** | Stage → validate → activate under existing filelock + forward-only revision; readers see pre- or post-set only | P0 | R4+R3 | L | Crash mid-activate leaves last coherent set; A→B→A never restores approval |
| **BN3** | Checkpoint/API migration doc: reconfirm on meaning change; no silent conversion; bundle rollback ≠ SQLite restore | P0 | R3+R2 (R1 C) | M | Operator-readable note + fixture |
| **BN4** | Demo proofs: clean install, data-only **development** scheme, malformed reject, restart, rollback, scoped delete, current-vs-outdated draft UI | P1 | R6+R4 | M | Offline suite first; Azure after explicit deploy |
| **BN5** | Prove on **CI Python 3.12** + Azure exact-commit smoke | P0 for claim | R6 | M | No laptop 3.14 as proof of record |
| **BN6** | Walkthroughs + frontend contract sync; R5 readability review | P1 | Implementers + R5 review | S–M | Docs match single-file vs full-bundle honesty |

**Azure file-share constraints (non-negotiable)**

- Share = backup copies (`SCHEME_SAATHI_BACKUP_DIR`), optional **staging bytes**, never live SQLite/WAL hot path.  
- Preferred activate for approved live bundles = **new image revision** (cost-effective; matches “deploy is separate”).  
- One BE replica forever under current backup design.  
- Scale-to-zero loses writable container-disk publishes — design for that.

**Partial claim:** Phase 4 single-file publish + monotonic revision + meaning-change latch.  
**Full New Phase 6 gate:** BN1–BN2 + BN5 (with BN3–BN4 for demo bar).

**Kill:** refuse “gate closed” if activate is still hand-edited files, mid-publish can mix A/B, rollback restores approvals or decrements revision, or proof is only local 3.14.

**Scenario (closed):** Activate dies after writing checklist but before form/registry flip; restart still serves the previous coherent bundle. Republishing old bytes never re-lights Meena’s unsubmitted approval; her receipt (if submitted) stays.

---

## 4. Claim matrix (working template)

Fill as waves close. Default today: **not claimable** unless noted.

| PDF / Phase 6 item | Required Azure / artifact | Owner | Status (start) |
|---|---|---|---|
| L13 Grafana dashboard | Managed Grafana, five live PDF panels | R6/R5 | not claimable (`/metrics` JSON only) |
| L13 traces every run | PII-masked traces (metrics ≠ traces) | R5/R6 handoff | partial / separate from metrics-first |
| L16 one working alert | Fired + cleared can't-tell jump on Azure | R6/R5 | not claimable (`alerts.yml` recipe) |
| L16 FastAPI streaming | S1–S4 on Azure | R3/FE | not claimable |
| L16 deploy / clean install | Runbook + frozen revision + inventory | R6 | partial (CAs exist; runbook/resume open) |
| L16 CI evaluation threshold | Ratified thresholds + failing run + explanation | R5/R6 | partial (script fails; no kept fail artifact) |
| Compose Prometheus/Grafana | Written Azure equivalent (D0b) | R6/R5 | **not claimed** as demo path |
| UI resume / CSC / delete | Azure manual sign-off | R6/R1 | partial (product exists; Azure drill open) |
| EN/HI/MR + Hindi widow | L1–L3 | R1/R6/R5 | not claimable for flagship |
| Submit pack (4–6p, slides, recording, logs) | Ev1–Ev6 | R5/R1/R6 | partial |
| New Phase 6 bundle gate | BN1–BN5 | R4/R6/R5 | not claimable (single-file ≠ gate) |
| PR #29 / App Insights initiated | — | — | **inventory only** — never “Phase 6 done” |

---

## 5. What NOT to claim (until green)

1. “L13 monitoring / Grafana complete” — until five panels show **live Azure** demo traffic.  
2. “L16 one working alert” — until fire + clear screenshots on the demo stack.  
3. “L16 deployment / clean-machine satisfied” — FE/BE up alone is insufficient.  
4. “Compose requirement met” — only after written equivalent + live metrics/alert; never imply `docker compose up` ran for the viva.  
5. “App Insights initiated” or “PR #29 merged” as Phase 6 ops complete.  
6. “Pending approvals / cost / can't-tell rate are trustworthy” — until M4 fixes or disclosed caveats.  
7. “Eval-gated deploy” — until C3 matches reality.  
8. “Streaming done” — until safe contract + UI + Azure proof (no raw model/tool text).  
9. “CI evaluation threshold done” — until C1 ratification **and** C2 failing-run artifact.  
10. “Phase 6 done when dashboard merges” / evidence slides alone.  
11. “Complete-bundle / New Phase 6 gate closed” from Phase 4 single-file publish.  
12. “MEMORY_POLICY / L9 / held-out E1–E4 closed” as side-effects of Phase 6 ops (see `docs/PHASE5_GAP_CLOSURE_PLAN.md`).  
13. Traces-for-every-call from metrics-only App Insights wiring.

---

## 6. Role 6 (+ Role 5) — first 2-week concrete backlog

Assume Role 6 drives Azure ops; Balaji (R5) owns claim language, M4 accuracy, CI fail artifact, and evidence packaging. Parallel R3 starts streaming contract early without blocking Wave 1.

### Days 1–2 (Wave 0 + Deploy start)

1. Publish **Phase 6 claim matrix** v0 (D0) — every L13/L16/bundle row `not claimable` unless proven.  
2. Write **Compose→Azure equivalent** one-pager (D0b); link from README ops.  
3. Freeze monitoring acceptance language in `docs/MONITORING.md` (D0c).  
4. Freeze bundle activate strategy decision (BN0) — image bake vs share stage.  
5. Complete Azure inventory verify (D1): MCP×4 + portal + vectors after cold start.  
6. Secrets audit (D3): App Insights connection string on BE; UI has no model keys.

### Days 3–5 (Runbook + Monitoring path)

7. Draft Azure demo runbook (D2): deploy, warm-up, rollback, scale 0/1 (D5).  
8. Codify readiness = health + info + functional smoke (D4).  
9. Wire/verify App Insights custom metrics (M1); capture redacted evidence.  
10. R5: land **M4a** verdict once-per-new-result fix (or hard schedule it before calling rate “true”).  
11. Point Managed Grafana at Azure Monitor / App Insights; rebuild five panels (M2).  
12. R5: draft C1 threshold ratification for R1 sign-off (do not peek-and-tune).

### Days 6–8 (Alert + resume + CI fail)

13. Implement **one** can't-tell alert; force fire + clear; screenshot (M3).  
14. Azure revision-resume proof (D6) + browser U1.  
15. Produce deliberately failing CI run + explanation (C2); store URL in evidence index.  
16. Sign C1 thresholds; document C3 gate honesty.  
17. Cost note (M5) + monitoring evidence pack skeleton (M6).

### Days 9–10 (Streaming start + flagship rehearsal + bundle design)

18. R3: freeze streaming event contract (S1); start S2 scaffolding (non-stream remains fallback).  
19. Rehearse L3 Hindi-widow path on Azure (even if recording waits); note CSC/delete gaps (U2).  
20. Start BN1 install-root design (not sign-off); list offline crash tests needed for BN2.  
21. R5: evidence index Ev6 v0 pointing only at **proven** artifacts; Ev3 outline with explicit non-claims.  
22. Status note: what moved from `not claimable` → `partial` → `ready`.

### Explicitly not in the first 2 weeks

- Full Wave 4 bundle activate sign-off (BN2/BN5 full).  
- Multi-alert / FinOps / conversation-duration panels.  
- Compose Prometheus as viva acceptance.  
- Claiming Phase 5 held-out / κ / MEMORY_POLICY closed.  
- Softening Role 5 CI thresholds to paint green.  
- Separate MCP/portal/Qdrant Container Apps “for PDF parity.”

---

## 7. Parallelization map (safe concurrency)

```text
Wave 0 claim freeze (R5+R6) ─────────────────────────────────────┐
Wave 1 Deploy (R6) ──► secrets/runbook/resume ───────────────────┤
         │                                                       │
         └─ Wave 2 Monitoring (R6 Azure + R5 M4/semantics) ──────┤
                  │                                              │
                  ├─ Wave 3 CI C1–C2 (R5) ───────────────────────┤
                  ├─ Wave 3 Streaming S1–S4 (R3/FE) ─────────────┤
                  ├─ Wave 3 U/L drills (R6/R1) after D6 ──────────┤
                  └─ Wave 3 Evidence Ev* documents 1–2 (R5) ─────┤
BN0 decision early; BN1–BN2 implementation parallel after D1 ────┤
Wave 4 Bundle sign-off LAST (R4/R6 + R5 claim review) ───────────┘
```

**Safe now:** D0/D0b/D0c/BN0, inventory probes, secrets checklist, M4a offline fix, C1 draft, S1 contract, Ev6 skeleton.  
**Not safe to claim:** Grafana/alert, streaming L16, eval-gated deploy, complete-bundle gate, Phase 6 “ready for capstone demo.”

---

## 8. Definition of Done = Azure-proven PDF artifacts

A wave is done when these exist — **not** when “JSON merged” or “tests pass on a laptop.”

| Wave | Evidence pack |
|---|---|
| 0 | Claim matrix; Compose→Azure map; monitoring + bundle non-claims frozen |
| 1 | Inventory; Azure runbook; secrets checklist; cost scale policy; revision-resume proof |
| 2 | App Insights custom metrics; five live panels; one fired/cleared alert; honesty table; cost note |
| 3 | Streaming Azure demo; ratified thresholds; failing CI URL + explanation; Hindi-widow path; 4–6p report + evidence index + slides/recording |
| 4 | Install root; stage/validate/activate; crash/rollback without mixed versions or restored approvals; CI 3.12 + Azure smoke |

**Closed for final review (story):** Examiner on a clean laptop opens only Azure URLs. Meena’s Hindi CSC journey streams safe progress, resumes after API recycle, forgets scoped data, and never re-approves a rolled-back draft fingerprint. Managed Grafana shows the five ops signals; one can't-tell alert fired for real. CI has a kept red eval gate with explanation. Complete-bundle activate is coherent. The report says clearly what remains Phase 5 (held-out, κ, MEMORY_POLICY) and that Compose Prometheus was replaced by a documented Azure equivalent — not ignored.

---

## 9. Stop-polish kill criteria (post this on the wall)

| If you are about to… | Stop unless… |
|---|---|
| Edit Grafana JSON cosmetics | Live Azure datasource + five panels still empty |
| Add a second alert or conversation-duration panel | M3 fire/clear still missing |
| Stand up Prometheus/Grafana Container Apps | Team Azure equivalent decision is still the plan |
| Claim Phase 6 from PR #29 / App Insights “initiated” | Panels + alert + runbook proofs missing |
| Soften CI thresholds after a red run | You are willing to disclose gate theater |
| Write slides claiming dashboard/alert/CI | Screenshot/URL artifacts do not exist |
| Hand-edit files in a running replica as “publish” | BN2 activate path exists |
| Point live SQLite at the file share | You accept multi-writer corruption |
| Call bundle gate closed from Phase 4 single-file tests | BN2 + BN5 Azure/CI proofs missing |
| Merge a plan whose DoD is “tests pass” | Rewrite DoD to Azure PDF artifacts |

---

## 10. Round 2 process note

- Round 1 produced five rich lane plans (critic + monitoring + deploy + streaming/CI/evidence + bundle).  
- Round 2 **merged** them into one sequenced roadmap, cut vanity, and fixed DoD to **Azure-proven** PDF artifacts.  
- Critic order is binding: **Deploy → Monitoring → Streaming/CI/evidence → Bundle last.**  
- Further planning rounds have **diminishing returns**: implement Wave 0–1 immediately; only reopen this plan when Azure topology, App Insights wiring reality, or Phase 1–4 acceptance status changes.

---

## 11. Key file / surface touch list (by wave)

**Claim / ops docs:** `docs/MONITORING.md`, `docs/PHASE6_GAP_CLOSURE_PLAN.md` (this file), README ops section, new Azure runbook, Compose→Azure one-pager, claim matrix / evidence index.

**Deploy:** `.github/skills/deploy-scheme-saathi*`, Container App secrets/env, `/mnt/saathi-runtime` backup config, `GET /health` + `/api/v1/info`.

**Monitoring:** OTEL / App Insights path (PR #29 lineage if present), `monitoring/grafana/dashboards/scheme_saathi_overview.json` (Azure-query rebuild), `monitoring/alerts.yml` → one Azure alert, journey metric recorders (M4a).

**Streaming / FE:** `src/api/app.py`, `FRONTEND_CONTRACT.md`, `src/ui/app.py`, journey checkpoint resume paths.

**CI / evidence:** `.github/workflows/frontend-checks.yml`, `scripts/run_role5_dev_evals.py`, `docs/EVALUATION_REPORT.md` (4–6p freeze), `docs/CONTRIBUTIONS.md`, `docs/THREAT_MODEL.md`, slides/recording (out of git or linked carefully).

**Bundle:** `src/rules/bundles.py`, `RulePackageProvider`, `src/documents/publication.py`, Dockerfile/image COPY layout, diagnostics on `/api/v1/info`, CI 3.12 job selection.

---

*PDF wins on evidence classes. Team decisions (Compose→Azure demo topology, alert numeric threshold, activate = image bake vs share stage, deploy-blocked-on-eval policy, App Insights retention) must be attributed as team decisions — not invented as PDF quotes.*
