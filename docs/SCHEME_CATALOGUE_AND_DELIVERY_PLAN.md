# Scheme Saathi: proposed scheme catalogue and delivery plan

**Status:** proposal for team review; the catalogue below is a shortlist, not a
verified or approved policy corpus.
**Prepared:** 2026-10-30
**Scope:** central Government of India schemes plus Maharashtra schemes.

This document combines the project target, a diverse 50-scheme shortlist, a
proposed 15-scheme gold-policy set, and an implementation and evaluation plan.
It does not establish current eligibility, benefit amounts, application
availability, or policy approval for any scheme.

## 1. Target and current baseline

The project brief calls for:

- **Scheme corpus:** 40–60 official schemes from central government and one
  state; each record needs an official page or PDF, scheme ID and name, source
  URL, collection date, state/category metadata, and clause-level text for
  retrieval.
- **Gold policy set:** 15 corpus schemes with exact quoted eligibility clauses,
  deterministic hand-coded rules, boundary cases, explicit unknowns/conflicts,
  Role 1 approval, and technical review by Roles 3 and 4.
- **Evaluation:** at least 60 synthetic personas; approximately 20 visible
  development cases and at least 40 protected held-out cases. Expected results
  must be written before system runs; two people independently label each
  persona; related boundary variants stay in the same split.
- **Security evaluation:** at least 30 separate red-team cases covering scams,
  prompt injection, eligibility fraud, cross-household access, and ID leakage.
- **User journey:** eligible, not-eligible, and insufficient-information
  scenarios; typed profile/verdict/citation/application models; consent and
  citizen/CSC-assisted screens; citations and document checklists; mock
  approve/edit/reject; approval invalidation after edits; and a “Forget
  demonstration data” control.
- **Deployment:** GitHub Actions validation must pass before deploying a new
  Azure Container Apps revision.

The repository currently has a synthetic Maharashtra widow-pension fixture,
seven development examples, a Streamlit demonstration, and a frontend
fingerprint demonstration for approval invalidation. The fixture policy is
still marked draft. That is a useful starting point, not the requested corpus,
gold set, held-out set, or secured production workflow.

## 2. Catalogue decision

Use the **50 candidates** below as the initial curation backlog: 25 central and
25 Maharashtra. The selection intentionally spans pensions, health, housing,
agriculture, education, women and children, insurance, and livelihoods. The
names are candidates, not evidence that all are active, distinct in
administration, or suitable for machine-readable rules.

### Source and counting rules

1. Count a scheme only after Role 2 records a **scheme-specific official
   government page or official PDF**, not just a search result or third-party
   explainer. A national or departmental directory is a discovery source only.
2. Record the precise page/PDF URL and the date the team retrieved it. The
   source-retrieval date is not necessarily the document's publication date.
3. Use a canonical scheme ID. If one scheme is delivered through central and
   state components, represent the relationship explicitly instead of
   double-counting the same benefit.
4. Keep separate schemes only where the official rules establish separate
   eligibility/benefit programs. Similar names are not enough to merge or
   distinguish them.
5. Mark inactive, superseded, merged, contradictory, or inaccessible sources
   **quarantined** until Role 1 resolves the issue. Replace a rejected candidate
   from the same category, preserving the 40–60 target and category balance.
6. The inventory date below is the date this shortlist was prepared. It is
   **not** a scheme-level collection date. Scheme-level collection dates remain
   “pending” until each official source is actually retrieved and logged.

### Central government candidates (25)

Discovery source for all central candidates: [myScheme, Government of India](https://www.myscheme.gov.in/).
This directory is for discovery; it does not replace the required primary
scheme page or government guideline PDF.

| ID | Candidate scheme | Category | Gold candidate | Source record |
|---|---|---|---|---|
| CEN-001 | Indira Gandhi National Widow Pension Scheme (IGNWPS) | Social assistance / widow pension | Yes | [Official Maharashtra scheme page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-widow-pension-scheme/); retrieve the current central guideline and record the state implementation relationship |
| CEN-002 | Indira Gandhi National Old Age Pension Scheme (IGNOAPS) | Social assistance / old age | Yes | [Official Maharashtra scheme page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-old-age-pension-scheme/); current national guideline still required |
| CEN-003 | Indira Gandhi National Disability Pension Scheme (IGNDPS) | Social assistance / disability | Yes | [Official Maharashtra scheme page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-disability-pension-scheme/); current national guideline still required |
| CEN-004 | National Family Benefit Scheme | Social assistance / family support | Yes | [Official Maharashtra scheme page](https://sjsa.maharashtra.gov.in/en/scheme/national-family-benefit-scheme/); confirm current guideline |
| CEN-005 | Pradhan Mantri Matru Vandana Yojana (PMMVY) | Maternity / women | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-006 | Janani Suraksha Yojana (JSY) | Maternal health | No | Scheme-specific official source URL and retrieval date pending |
| CEN-007 | Ayushman Bharat – Pradhan Mantri Jan Arogya Yojana (AB PM-JAY) | Health coverage | No | Scheme-specific official source URL and retrieval date pending; check relationship with Maharashtra's MJPJAY |
| CEN-008 | Pradhan Mantri Awas Yojana – Gramin (PMAY-G) | Housing / rural | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-009 | Pradhan Mantri Awas Yojana – Urban 2.0 (PMAY-U 2.0) | Housing / urban | No | Scheme-specific official source URL and retrieval date pending |
| CEN-010 | Pradhan Mantri Kisan Samman Nidhi (PM-KISAN) | Agriculture / income support | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-011 | Pradhan Mantri Fasal Bima Yojana (PMFBY) | Agriculture / crop insurance | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-012 | Kisan Credit Card (KCC) | Agriculture / credit | No | Scheme-specific official source URL and retrieval date pending |
| CEN-013 | Pradhan Mantri Kisan Maandhan Yojana | Agriculture / pension | No | Scheme-specific official source URL and retrieval date pending |
| CEN-014 | Pradhan Mantri Ujjwala Yojana (PMUY) | Household energy | No | Scheme-specific official source URL and retrieval date pending |
| CEN-015 | PM Street Vendor’s AtmaNirbhar Nidhi (PM SVANidhi) | Livelihood / urban vendors | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-016 | PM Vishwakarma | Livelihood / traditional artisans | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-017 | Pradhan Mantri Suraksha Bima Yojana (PMSBY) | Insurance / accident | No | Scheme-specific official source URL and retrieval date pending |
| CEN-018 | Pradhan Mantri Jeevan Jyoti Bima Yojana (PMJJBY) | Insurance / life | No | Scheme-specific official source URL and retrieval date pending |
| CEN-019 | Atal Pension Yojana (APY) | Pension / contributory | No | Scheme-specific official source URL and retrieval date pending |
| CEN-020 | PM POSHAN | Nutrition / school-age children | No | Scheme-specific official source URL and retrieval date pending |
| CEN-021 | National Means-cum-Merit Scholarship Scheme (NMMSS) | Education / scholarship | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-022 | Pre-Matric Scholarship for Scheduled Caste students | Education / scholarship | No | Scheme-specific official source URL and retrieval date pending; verify current class/coverage rules |
| CEN-023 | Post-Matric Scholarship for Scheduled Caste students | Education / scholarship | Yes | Scheme-specific official source URL and retrieval date pending |
| CEN-024 | PM Young Achievers Scholarship Award Scheme for Vibrant India (PM-YASASVI) | Education / scholarship | No | Scheme-specific official source URL and retrieval date pending; verify current components and naming |
| CEN-025 | Antyodaya Anna Yojana (AAY) | Food security | No | Scheme-specific official source URL and retrieval date pending |

### Maharashtra government candidates (25)

Discovery sources include the [Social Justice & Special Assistance Department
scheme directory](https://sjsa.maharashtra.gov.in/en/schemes-programmes/) and
the [MahaDBT portal](https://mahadbt.maharashtra.gov.in/). These are starting
points, not substitutes for scheme-specific source records. Some candidates
may be administered by other Maharashtra departments; Role 2 must locate each
owning department's official source.

| ID | Candidate scheme | Category | Gold candidate | Source record |
|---|---|---|---|---|
| MH-001 | Sanjay Gandhi Niradhar Anudan Yojana (SGNY) | Social assistance / destitution | No | [Official scheme page](https://sjsa.maharashtra.gov.in/en/scheme/sanjay-gandhi-niradhar-anudan-yojana/); explicitly review overlap with IGNWPS/IGNDPS |
| MH-002 | Shravanbal Seva Rajya Nivruttivetan Yojana | Social assistance / old age | Yes | Scheme-specific official source URL and retrieval date pending |
| MH-003 | Mahatma Jyotirao Phule Jan Arogya Yojana (MJPJAY) | Health coverage | No | Scheme-specific official source URL and retrieval date pending; confirm current integration/relationship with AB PM-JAY |
| MH-004 | Mukhyamantri Majhi Ladki Bahin Yojana | Women / income support | Yes | Scheme-specific official notification/page and retrieval date pending; confirm current rules before use |
| MH-005 | Lek Ladki Yojana | Girl child / staged assistance | Yes | Scheme-specific official notification/page and retrieval date pending |
| MH-006 | Namo Shetkari Mahasanman Nidhi Yojana | Agriculture / income support | No | Scheme-specific official source URL and retrieval date pending; mark its relationship to PM-KISAN and avoid double-counting |
| MH-007 | Bal Sangopan Yojana | Child welfare / care | No | Scheme-specific official source URL and retrieval date pending |
| MH-008 | Ramai Awas Yojana (Rural and Urban) | Housing / Scheduled Caste | Yes | [Official department directory](https://sjsa.maharashtra.gov.in/en/schemes-programmes/); capture the exact scheme page/PDF |
| MH-009 | Shabari Adivasi Gharkul Yojana | Housing / Scheduled Tribe | No | Scheme-specific official source URL and retrieval date pending |
| MH-010 | Modi Awas Gharkul Yojana | Housing / OBC | No | Scheme-specific official source URL and retrieval date pending; verify official name and current status |
| MH-011 | Pandit Deendayal Upadhyay Gharkul Yojana | Housing | No | Scheme-specific official source URL and retrieval date pending; verify scope and current status |
| MH-012 | Yashwantrao Chavan Mukta Vasahat Yojana | Housing / nomadic and denotified communities | No | Scheme-specific official source URL and retrieval date pending |
| MH-013 | Dr. Babasaheb Ambedkar Krushi Swavalamban Yojana | Agriculture / Scheduled Caste farmers | Yes | Scheme-specific official source URL and retrieval date pending |
| MH-014 | Birsa Munda Krushi Kranti Yojana | Agriculture / Scheduled Tribe farmers | No | Scheme-specific official source URL and retrieval date pending |
| MH-015 | Bhausaheb Fundkar Falbaag Lagwad Yojana | Agriculture / horticulture | No | Scheme-specific official source URL and retrieval date pending |
| MH-016 | Rajarshi Chhatrapati Shahu Maharaj Shikshan Shulkh Shishyavrutti Yojana | Education / tuition support | Yes | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); exact scheme page and current guidelines required |
| MH-017 | Dr. Panjabrao Deshmukh Vasatigruh Nirvah Bhatta Yojana | Education / hostel allowance | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); exact scheme page and current guidelines required |
| MH-018 | Post-Matric Scholarship to OBC students | Education / scholarship | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); exact scheme page and current guidelines required |
| MH-019 | Tuition Fees and Examination Fees to OBC students | Education / fee reimbursement | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); verify distinctness from MH-018 and current guidelines |
| MH-020 | Post-Matric Scholarship to VJNT students | Education / scholarship | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); exact scheme page and current guidelines required |
| MH-021 | Tuition Fees and Examination Fees to VJNT students | Education / fee reimbursement | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); verify distinctness from MH-020 and current guidelines |
| MH-022 | Post-Matric Scholarship to SBC students | Education / scholarship | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); exact scheme page and current guidelines required |
| MH-023 | Tuition Fees and Examination Fees to SBC students | Education / fee reimbursement | No | [MahaDBT portal](https://mahadbt.maharashtra.gov.in/); verify distinctness from MH-022 and current guidelines |
| MH-024 | Reimbursement of Education Fees and Examination Fees for Backward Class Students | Education / fee reimbursement | No | [Official department directory](https://sjsa.maharashtra.gov.in/en/schemes-programmes/); confirm target class/category and whether it duplicates another record |
| MH-025 | Financial Assistance to Family Members of Scheduled Castes and Scheduled Tribes Victims of Atrocities | Social assistance / victim support | No | [Official department directory](https://sjsa.maharashtra.gov.in/en/schemes-programmes/); capture exact scheme page/PDF |

### Proposed 15-scheme gold set

This is a **balanced draft selection**, not a claim that the policy clauses have
already been reviewed. It prioritizes different populations and benefit types,
clear source text, and testable decision boundaries. A candidate stays out of
the gold set if rules are changing, source text is missing, or a linked scheme
makes the decision ambiguous until Role 1 resolves it.

| ID | Scheme | Why it adds distinct coverage | Initial rule-review note |
|---|---|---|---|
| CEN-001 | IGNWPS | Widow pension; current prototype is a starting point | Verify age, BPL, and Maharashtra top-up relationship; do not model SGNY as an extra duplicate payment |
| CEN-002 | IGNOAPS | Old-age social pension | Verify age bands and BPL/source version |
| CEN-003 | IGNDPS | Disability-related social pension | Verify disability threshold, age, BPL, and linked state benefit |
| CEN-004 | National Family Benefit Scheme | One-time survivor/family assistance | Verify qualifying death, age, household, and timing clauses |
| CEN-005 | PMMVY | Maternity assistance | Review parity/component changes against current official guidelines |
| CEN-008 | PMAY-G | Rural housing | Resolve household, housing status, and selection-list criteria before coding |
| CEN-010 | PM-KISAN | Farmer income support | Review landholding exclusions and beneficiary-family definition |
| CEN-011 | PMFBY | Crop insurance | Prefer an application-window/coverage explanation; avoid inferring coverage from demographic profile alone |
| CEN-015 | PM SVANidhi | Urban street-vendor credit | Verify vendor identification and loan-stage criteria |
| CEN-016 | PM Vishwakarma | Traditional artisan support | Confirm eligible trades and current benefit components |
| CEN-021 | NMMSS | School scholarship | Review school, exam, income, and continuation criteria |
| MH-004 | Mukhyamantri Majhi Ladki Bahin Yojana | Maharashtra women-focused assistance | Freeze a dated official notification; do not code from news summaries |
| MH-005 | Lek Ladki Yojana | Girl-child staged benefit | Model stage-specific conditions explicitly |
| MH-008 | Ramai Awas Yojana | Maharashtra SC-targeted housing | Verify rural/urban variant and deduplicate them only if official rules justify it |
| MH-013 | Dr. Babasaheb Ambedkar Krushi Swavalamban Yojana | Maharashtra SC farmer support | Verify eligible applicant, land, irrigation, and component criteria |

Before any scheme becomes gold, Role 1 must approve the exact quoted clauses and
their interpretation; Roles 3 and 4 must review the typed rule representation,
unknown/conflict behavior, and deterministic tests. If a candidate fails that
gate, replace it with a better-sourced scheme from the same category.

## 3. Required data record for each accepted scheme

Keep the catalogue and clause corpus separate from user profiles and test
personas. A versioned record should include at least:

```text
scheme_id                 stable canonical ID
scheme_name               official name; aliases in separate fields
government_level          central | Maharashtra
state_scope               India | Maharashtra
department                source publisher/owning department
category                  controlled category plus optional tags
official_source_url       exact official page or PDF URL
source_title              page/PDF title as published
published_at               date if explicitly shown, otherwise unknown
collected_at               ISO date the team retrieved the source
source_version_or_hash    version/etag/content hash when practical
source_status              verified | pending_review | conflict | superseded
relationship_ids           linked, merged, state top-up, or component scheme IDs
clauses[]                  clause_id, exact quote, page/heading, language
                           retrieval text, and normalized-rule references
policy_approval             reviewer, date, and approval state
```

Do not treat the current fixture's `collected_at` as proof that all schemes
were retrieved on that date. Keep quoted text faithful to its source; store
translated display text separately and do not use a translation as the sole
policy authority.

## 4. Delivery plan and gates

| Phase | Work and accountable roles | Exit gate |
|---|---|---|
| 0. Scope lock | Roles 1 and 6 agree that the list is central + Maharashtra, assign owners/backups, and define whether linked central/state components count as one record or related records. | Team approves 40–60 candidate scope and naming/counting rules. |
| 1. Source curation | Role 2 gathers scheme-specific official pages/PDFs; Role 1 checks currentness and ownership. Quarantine inaccessible, inactive, or conflicting candidates and replace them by category. | At least 40, at most 60 accepted records have every required metadata field, exact official URL, collection date, and clause text. |
| 2. Typed contracts | Roles 3 and 4 define versioned profile, verdict, citation, checklist, consent, and application models. Represent unknown answers explicitly; reject undeclared or malformed fields. | Contract examples and validation tests cover all three verdicts, citations, missing facts, and synthetic-only data. |
| 3. Gold policies | Role 1 quotes and approves clauses for the selected 15. Role 3 writes deterministic rules; Role 4 reviews fail-closed behavior and tests boundaries, conflicts, and unknowns. | Every gold rule traces to a clause; no AI-generated verdict can bypass the rule engine. |
| 4. Development and held-out evaluation | Role 5 authors/labels the 60+ synthetic personas before system evaluation: ~20 development and >=40 held-out. Keep related boundary families in one split. | Two independent labels per persona; adjudicated expected results; protected set inaccessible to app/agent code. |
| 5. User journey | Role 6 wires consent, citizen/CSC-assisted mode, three scenarios, citations, checklist, mock application, approve/edit/reject, edit invalidation, and forget-data control. Roles 3/4 own API and approval controls. | Automated UI/API tests prove the full journey; only synthetic fixtures are used; edits clear approvals; forget clears demo state. |
| 6. Security suite | Role 5 maintains >=30 separate red-team cases; Role 4 tests access boundaries, prompt/data separation, injection handling, redaction, and approval enforcement. | Tests include scams, prompt injection, fraud requests, cross-household access, and ID leakage. The suite does not contain held-out expected answers. |
| 7. CI and deployment | Role 6 runs formatting/static checks, unit/integration tests, fixture validation, and image build in GitHub Actions. Deploy only after validation passes; configure the Container Apps workflow to create a new revision and perform health/readiness checks. | Failed checks cannot deploy; successful deploy identifies the image/version and revision; smoke test passes; rollback path is documented. |
| 8. Freeze and held-out run | All roles freeze corpus, rules, prompts, and lessons. Role 5 alone runs held-out evaluation and reports metrics. | Any exposed held-out case is reclassified as development and replaced; no tuning occurs against held-out answers. |

### User-facing behavior to preserve

- Explain consent before capturing any profile facts; offer citizen and
  CSC-assisted modes without implying the operator can consent on another
  person's behalf.
- Label every scenario and draft **synthetic demonstration only**.
- Return **eligible**, **not eligible**, or **insufficient information** from
  deterministic rules. Unknown facts never become “no.”
- Show the official citation supporting each deciding rule. A document
  checklist must distinguish source-verified requirements from items not yet
  verified; never invent a required document.
- Approval is bound to the exact draft/version. Any edit invalidates it.
  Rejection ends the mock flow; approval can reach only a mock endpoint.
- “Forget demonstration data” clears the active synthetic session and any
  stored demo state covered by the feature. State its limits clearly.
- The live deployment never submits to government services and never uses real
  Aadhaar, bank, or other sensitive personal data for this prototype.

## 5. Evaluation split and access controls

Recommended layout and access policy:

```text
eval/
  development/        # about 20 synthetic cases; available to builders
  held_out/            # >=40 cases; not in app image, indexes, prompts, or CI artifacts
  red_team/            # >=30 attacks; separate from gold personas
```

The directory names are illustrative; **do not create or populate a
developer-readable held-out directory**. Use repository permissions or an
external controlled location accessible only to Role 5. CI for the application
must not checkout, package, index, print, or upload held-out fixtures.

For each persona, store its synthetic profile, expected verdict, citations,
missing facts, and two independent labels in the evaluation system—not in
agent-facing application fixtures. Keep every age/income/category boundary
family in one split. Freeze the corpus, prompts, rules, and improvement lessons
before held-out execution. If any held-out result is seen by a builder and
leads to a code/prompt/rule change, retire that case from the held-out set and
replace it with a newly authored, independently labelled persona.

## 6. Bounded agent/autopilot operating model

Use agents to accelerate bounded, independently reviewable tasks—not to
silently approve policy or deploy unreviewed changes.

1. Suitable parallel tasks: collect official URLs for separate scheme
   categories, extract candidate clauses from public official documents, or
   draft tests from already approved rules.
2. Give each task a fixed scheme-ID range, required output fields, official
   source requirement, and a stop condition. Do not give research agents
   held-out personas, secrets, production credentials, or deployment authority.
3. A human checks each source, clause, and interpretation. Agent-generated
   rules remain drafts until Role 1 approval and Roles 3/4 technical review.
4. Use a diminishing-returns stop: after two targeted source-finding attempts,
   if no official primary source is available or no new trustworthy evidence
   appears, mark the candidate `pending_review`/`quarantined` and move to the
   next candidate. Do not spend repeated cycles polishing unsupported claims.
5. Merge one bounded batch at a time; run the smallest relevant tests, then the
   full validation workflow before any deployment.
6. Keep deployment credentials and production approval outside agent context.
   The workflow deploys only a reviewed commit after CI passes; an agent does
   not decide to bypass the gate or promote a revision autonomously.

## 7. First practical milestones

1. Have the team approve/revise the candidate list and the 15-scheme gold
   proposal.
2. Fully verify the existing IGNWPS source, linked SGNY relationship, and
   rules; retain the current three demo outcomes as development examples.
3. Add source records and clause-level retrieval text for the first 15 gold
   schemes, then expand the verified catalogue to at least 40.
4. Finalize typed contracts and an end-to-end mock flow before broadening rule
   extraction or adding autonomous agents.
5. Ask Role 5 to build and protect the 60+ persona evaluation and 30+ red-team
   sets before the prompts/rules are tuned against them.
6. Require a successful GitHub Actions run and smoke check before each new
   Container Apps revision.

## 8. Official discovery sources consulted

- [myScheme — Government of India](https://www.myscheme.gov.in/) — central and
  state scheme discovery; scheme-specific primary pages still required.
- [Maharashtra Social Justice & Special Assistance Department — Schemes](https://sjsa.maharashtra.gov.in/en/schemes-programmes/)
  — departmental catalogue consulted on 2026-10-30.
- [MahaDBT](https://mahadbt.maharashtra.gov.in/) — Maharashtra scholarship and
  benefit portal; current portal notices indicate a transition between portal
  versions, so check the current scheme page before relying on old links.
- [IGNWPS — Maharashtra official scheme page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-widow-pension-scheme/)
  — consulted 2026-10-30; states the widow age/BPL criteria and describes
  central and state assistance together.
- [SGNY — Maharashtra official scheme page](https://sjsa.maharashtra.gov.in/en/scheme/sanjay-gandhi-niradhar-anudan-yojana/)
  — consulted 2026-10-30; lists multiple beneficiary groups, including
  destitute widows, and needs overlap review against linked pension schemes.
- [IGNOAPS — Maharashtra official scheme page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-old-age-pension-scheme/)
  — consulted 2026-10-30.
- [IGNDPS — Maharashtra official scheme page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-disability-pension-scheme/)
  — consulted 2026-10-30.
- [National Family Benefit Scheme — Maharashtra official scheme page](https://sjsa.maharashtra.gov.in/en/scheme/national-family-benefit-scheme/)
  — consulted 2026-10-30.

**Completion status:** 50 candidates listed; none of the pending entries count
as corpus-complete until their exact official scheme source, collection date,
metadata, and clause text have been captured and reviewed.
