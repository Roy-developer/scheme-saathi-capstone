# Scheme evidence review: IGNOAPS-MH

> **Draft evidence review only. Not policy approval or an eligibility
> decision.** Scope: an answer key for rule-extraction Reflexion development
> (option A). This review does not add IGNOAPS to the app.
>
> **Amended 2026-11-08:** the reviewer later approved IGNOAPS for the app as a
> mock scheme. See the amendment at the end of this document.

## Review identity

- Scheme name: Indira Gandhi National Old Age Pension Scheme — Maharashtra
- Scheme ID: `IGNOAPS-MH`
- Jurisdiction: Maharashtra implementation of the central scheme
- Applicable-as-of date: 2026-11-08
- Proposed rule-set version: `1.0.0`
- Input file/source: model draft `data/runtime/reflexion_drafts/ignoaps-mh_2026-11-07T200842.json`, produced by `scripts/scheme_rules.py extract` (since moved to `src/rule_extraction_reflexion/scheme_rules.py`) from `data/schemes/rule_extraction_sources/ignoaps_mh.json` (model `openai/gpt-4o-mini`, playbook `1.0.0`, no lessons applied)
- Review date: 2026-11-08
- Reviewer model/provider (if known): Claude (Opus 5.5), in the Claude Code session that produced the draft
- Skill/prompt version: `.github/skills/review-scheme-evidence/SKILL.md` and `REVIEW_TEMPLATE.md` from this repository
- Independent second-model review: performed 2026-11-08 (Claude Sonnet, without access to this report's conclusions); summarized below
- Human policy decision: `approved` by `Roy-developer` on 2026-11-08 for the Reflexion development answer key only (see Human sign-off); extended the same day to the app as a mock scheme (see Amendment).

## Source register

| Source ID | Publisher and title | Official scheme-specific source? | URL | Retrieved on | Publication/effective date | Location (page/heading/clause) | Limitations |
|---|---|---|---|---|---|---|---|
| S1 | Social Justice & Special Assistance Department, Government of Maharashtra, "Indira Gandhi National Old Age Pension Scheme" | Yes; scheme-specific government department page | [Official page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-old-age-pension-scheme/) | 2026-11-08 | Page shows "Date: 01/01/2000 -" and "Last updated 29.04.2025"; neither is stated to be an effective date | "Eligibility Criteria", "Nature of Benefits", "Beneficiary", "Benefits", "How To Apply" | Direct evidence of what the page states. It does not prove that no later notification supersedes it. The central NSAP guidelines (linked from the page, nsap.nic.in) were not reviewed. |

| S2 | "Indira Gandhi National Old Age Pension Scheme (IGNOAPS), Ministry of Rural Development, Government of India (Under National Social Assistance Programme – NSAP)", a 4-page summary provided by the reviewer on 2026-11-08 | Describes the central scheme; **not** the ministry's guideline document itself | Local file `1077501448-INDIRA-GANDHI-NATIONAL-OLD-AGE-PENSION-SCHEME-IGNOAPS-...pdf` (SHA-256 begins `773a1c29345edd2e`); the reviewer reports downloading it from a government website, URL not recorded | 2026-11-08 | Not stated; file metadata: created 2026-04-27 in Google Docs | p. 2 "Eligibility Criteria"; p. 4 FAQ 5 | No letter number, date of issue or clause numbers; ends with text copied from an AI assistant's reply. The reviewer chose to consider its eligibility content. The official guideline (nsap.dord.gov.in, IGNOAPS, 08/11/2012) was not obtained. |

S1 "Eligibility Criteria" states:

> "Eligible elderly individuals aged 65 and above, whose names are on the Below
> Poverty Line (BPL) list, receive monthly financial assistance under the Indira
> Gandhi National Old Age Pension Scheme."

S1 "Nature of Benefits" sets amounts by age band (central ₹200 per month at 65
to 79 years and ₹500 at 80 and above; state Shravanbal Seva ₹1300 and ₹1000).
"Benefits" states "Rs. 1500 per month is given to each beneficiary".
"Beneficiary" states "All Categories". These describe amounts and coverage, not
additional eligibility conditions.

## Rule-by-rule findings

| Rule ID | Proposed claim (field/operator/value/scope) | Evidence status | Exact source quote | Source ID and precise location | Analysis, gaps, or conflict | Suggested change (not applied) |
|---|---|---|---|---|---|---|
| `IGNOAPS-MH-AGE-MIN-01` | `age gte 65`, unit `years`, person | `supported` by S1; `conflicting_sources` with S2 (60), resolved by reviewer decision for 65 | "aged 65 and above" | S1, "Eligibility Criteria" | The threshold and its inclusion of 65 are stated directly ("and above"). The page does not say on which date age is measured; reviewer decision: the application date, as for IGNWPS. There is no upper age limit: the 65 to 79 and 80+ bands change only the amount. | None. Record `age_as_of: application_date` and `age_boundaries_inclusive: true` in the package. |
| `IGNOAPS-MH-BPL-LIST-01` | `name_on_bpl_list eq true`, person | `supported` | "whose names are on the Below Poverty Line (BPL) list" | S1, "Eligibility Criteria" | Directly stated. The page does not say which BPL list (state or central) or how inclusion is verified; the fact deliberately does not claim more. Reviewer decision: use `name_on_bpl_list`, not the card-based `bpl_card_shown`, because S1 mentions no card; a "no" answer means not eligible and "don't know" stays unknown. | None. Keep the default unmet outcome (`not_eligible`); an unknown answer stays unknown. |

No rule is `contradicted`. The draft contained exactly these two conditions and
nothing that S1 does not state.

## Independent second-model review (2026-11-08)

The second reviewer re-read S1 itself, without seeing this report.

- **Agrees:** both rules are `supported` by S1; no upper age limit (the 65 to 79
  and 80+ bands are amounts only); no card or document requirement on the page;
  the human decisions (age on the application date, 65 included; the
  `name_on_bpl_list` fact) are consistent with the evidence. It overturned
  nothing.
- **Disposition: `changes_required`**, for two reasons:
  1. Its web tool showed only the start of the eligibility sentence. **Resolved:**
     the full sentence was captured verbatim from the page's HTML on 2026-11-08
     and is quoted above.
  2. It could not open the central NSAP guidelines, so a possible conflict is
     unchecked: from background knowledge (unverified) the central IGNOAPS
     guideline is often described as age 60 and above, while S1 says 65.
     **Not resolved:** the Ministry of Rural Development NSAP site
     (nsap.dord.gov.in, "Guidelines") lists "Indira Gandhi National Old Age
     Pension Scheme (IGNOAPS)" dated 08/11/2012, "IGNOAPS (Hindi/English)"
     dated 30/06/2011 and "NSAP Guidelines (R.)" dated 31/10/2014, but their
     links are script placeholders and could not be downloaded here.
- **Smaller points:** whether "names" means the individual or the household,
  and which BPL list applies, are not stated in S1 (the fact deliberately
  asks about the applicant's own name).

## Conflicting source and reviewer decisions (2026-11-08)

S2 states, for the central scheme: "An applicant must: Be a citizen of India;
Belong to the Below Poverty Line (BPL) category; Be 60 years of age or above"
(p. 2), repeated in FAQ 5 (p. 4), and lists "Affidavit confirming
non-receipt of any other pension" among required documents (p. 3).

| Topic | S1 (Maharashtra) | S2 (central summary) | Reviewer decision (`Roy-developer`) |
|---|---|---|---|
| Minimum age | "aged 65 and above" | "60 years of age or above" | **65**: IGNOAPS-MH follows the Maharashtra department's official page; S1's benefit bands also start at 65. The 60/65 difference is recorded as `conflicting_sources` and remains open for confirmation against the official central guideline. |
| Citizenship | Not stated | "Be a citizen of India" | **Not a rule**; recorded as an open question (a rule would need a new reviewed fact). |
| No other pension | Not stated | Only as a required document (affidavit) | **Not a rule**; recorded as an open question. |

## Questions requiring a person

| Question | Why the source does not settle it | Suggested reviewer |
|---|---|---|
| Is the S1 page the current rule baseline? | Its dates are ambiguous ("01/01/2000 -", "last updated 29.04.2025"). | Domain/policy reviewer |
| Do the central NSAP guidelines state a different age threshold (possibly 60) or extra conditions? Is 65 a deliberate Maharashtra rule? | The guidelines (08/11/2012, 30/06/2011, revised 31/10/2014) are listed on nsap.dord.gov.in but could not be downloaded; no GR or notification number is given on S1. | Domain/policy reviewer |
| Is Indian citizenship a condition for the Maharashtra implementation? | Stated only in S2 (unofficial summary), not in S1. | Domain/policy reviewer |
| Is "non-receipt of any other pension" an eligibility condition? | S2 lists only an affidavit among documents. | Domain/policy reviewer |
| Should the state Shravanbal Seva top-up be modelled? | S1 lists it under benefit amounts; treat it as part of the amount, not a separate eligibility decision, unless a source says otherwise. | Domain/policy reviewer |
| Native-language wording of the `name_on_bpl_list` question and help text | Hindi and Marathi were written in this session; questions remain `pending`. | Native speakers |

## Provisional development tests

Synthetic facts only. Expected results are provisional until a person labels them.

| Case ID | Synthetic facts | Provisional expected result | Rule/source being tested | Human label/reviewer |
|---|---|---|---|---|
| DEV-IGNOAPS-AGE-64 | age 64 on application date; on BPL list | `not_eligible` — provisional | AGE-MIN, "65 and above" | Pending |
| DEV-IGNOAPS-AGE-65 | age 65; on BPL list | `eligible` — provisional | AGE-MIN boundary included | Pending |
| DEV-IGNOAPS-AGE-85 | age 85; on BPL list | `eligible` — provisional | No upper age limit | Pending |
| DEV-IGNOAPS-NOT-ON-LIST | age 70; answer "no" to BPL list | `not_eligible` — provisional | BPL-LIST | Pending |
| DEV-IGNOAPS-LIST-UNKNOWN | age 70; answer "don't know" to BPL list | `cant_tell` — provisional | BPL-LIST unknown stays unknown | Pending |

## Overall disposition

Disposition: `ready_for_human_review` (first reviewer); `changes_required`
(second reviewer) until the central age question is checked or the reviewer
decides to use S1 as the baseline

Summary and limitations: both proposed rules are directly supported by the
official Maharashtra page. The age-measurement date and the choice of BPL fact
are reviewer decisions, already recorded. The source's currency and the central
NSAP guidelines were not verified, and no independent second-model review was
performed. Approval would cover only the Reflexion development answer key, not
adding IGNOAPS to the app.

## Human sign-off

- Policy/domain reviewer: `Roy-developer`
- Decision: `approved` (both rules: `IGNOAPS-MH-AGE-MIN-01` age gte 65 years; `IGNOAPS-MH-BPL-LIST-01` name_on_bpl_list eq true)
- Conditions or corrections: approved **only as a Reflexion development answer key** (option A); IGNOAPS is not added to the app. Age is measured on the application date and 65 is included. The 60 (central summary) versus 65 (Maharashtra page) conflict, citizenship and other-pension questions stay open. Package: `data/schemes/reflexion_packages/ignoaps_mh.v1.json` (SHA-256 `9e342f7833cfdd9aa286054c8aa8930f6a0dc49dd5c140b506ff7a4a6fda675c`, pinned in `data/schemes/rule_extraction_cases_dev.json`), deliberately outside `src/rules/packages` because the app loads every file there and requires a bundle for each.
- Date: 2026-11-08

Approval applies only to the listed scheme, jurisdiction, source versions,
and rule-set version. It does not approve any other scheme or decide any
individual's eligibility.

## Amendment 2026-11-08: approved for the app as a mock scheme

The sign-off above is kept as written. This amendment extends it.

- **Decision:** `Roy-developer` approved `IGNOAPS-MH` for use in the app as a
  mock scheme (package status `approved_for_mock_portal`, bundle state
  `approved`). Both rules are unchanged: `IGNOAPS-MH-AGE-MIN-01` (age gte 65
  years) and `IGNOAPS-MH-BPL-LIST-01` (name_on_bpl_list eq true).
- **Still pending:** native-speaker review of the question wording, privacy
  review, and human labels for the provisional development tests.
- **Update 2026-11-09:** `Roy-developer` set the question and privacy status of all
  registered facts to approved for the synthetic mock. No separate native-speaker
  or privacy review was performed.
- **Still open:** the central age of 60 versus the Maharashtra page's 65,
  citizenship, and non-receipt of another pension. The app lists these as
  unresolved checks. The result is a mock and not a government decision.
- **What changed in the package:** it moved to
  `src/rules/packages/ignoaps_mh.v1.json`. Two pieces of text shown to users
  were reworded: `notice` (it held internal development wording) and the
  `need_more_information` reason (it named the date of birth even when that was
  given). No rule, required fact or source changed.
- **Package SHA-256:** `cd4652b8a7da119561eee6ee8a532b4059cca8b750c9d323d93c6a05c00a6549` (previously
  `9e342f7833cfdd9aa286054c8aa8930f6a0dc49dd5c140b506ff7a4a6fda675c`), pinned in
  `src/rules/bundle_registry.json` and
  `data/schemes/rule_extraction_cases_dev.json`.
- App approval: `IGNOAPS-MH` approved by `Roy-developer` on 2026-11-08 for package SHA-256 `cd4652b8a7da119561eee6ee8a532b4059cca8b750c9d323d93c6a05c00a6549`
- **Correction:** "no independent second-model review was performed" under
  Overall disposition was written before that review took place. The review is
  summarized above.

## Update 2026-11-09: document checklist

The demo checklist was replaced by version `v2` and approved at the reviewer's
instruction, using the best official text available, which may not be current.
It cites a Chhatrapati Sambhajinagar district page (undated, and describing the older National Old Age Pension Scheme) and a Department of Rural Development evaluation of NSAP based on discussions with beneficiaries. Hindi and Marathi labels have had no native-speaker review.
