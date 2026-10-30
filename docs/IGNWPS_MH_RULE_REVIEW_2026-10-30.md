# Scheme evidence review: IGNWPS-MH

> **LLM-assisted evidence review with reviewer sign-off for the synthetic mock
> portal only. Not legal advice, a government determination, or an individual
> eligibility decision.**

## Review identity

- Scheme: Indira Gandhi National Widow Pension Scheme — Maharashtra
- Scheme ID: `IGNWPS-MH`
- Jurisdiction: Maharashtra implementation of the central scheme
- Applicable-as-of date requested: 2026-10-30
- Reviewer-approved baseline: `0.1.0`; implementation fixture: `0.2.0`
- Input: `src/ui/fixtures/ignwps_mh.json`; schema: `src/ui/models.py`
- Review date: 2026-10-30
- Review pass: 3; reviewer decisions recorded after the independent AI check
- Primary reviewer model/provider: not available in session metadata
- Skill: `.github/skills/review-scheme-evidence/SKILL.md`, loaded from this repository for this pass
- Independent second-model review: performed; model/provider identity not available
- Human policy decision: `approved_for_mock_portal`
- Scope of approval: synthetic demonstration and mock-portal flow only; not a claim that the source is verified current for real applications

## Source register

| Source ID | Publisher and title | Official scheme-specific source? | URL | Retrieved on | Publication/effective date | Location | Limitations |
|---|---|---|---|---|---|---|---|
| S1 | Social Justice & Special Assistance Department, Government of Maharashtra, “Indira Gandhi National Widow Pension Scheme” | Yes; scheme-specific government department page | [Official page](https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-widow-pension-scheme/) | 2026-10-30 (this review); fixture records 2026-10-28 | Page displays `Date: 01/01/2000 -`; the page does not explain whether this is an effective date, publication date, or last-updated date | “Eligibility Criteria”, “Beneficiary”, “Benefits”, and “How To Apply” sections | Page text is direct evidence of what the page states, but does not itself establish that no later guideline or amendment supersedes it. |

S1 directly states:

> “A widow in age group of 40 to 79 years whose family falls under Below
> Poverty Line is eligible under this Scheme.”

It also states:

> “She is eligible to receive Rs 300/- per month from Central Government under
> this scheme.”
>
> “She also receives Rs 1200/- per month under State sponsored Sanjay Gandhi
> Niradhar Anudan Yojana, so total financial assistance of Rs. 1500/- is
> provided.”

And its application section says:

> “The applicant can apply at the Collector’s Office / Tehsildar’s Office,
> Sanjay Gandhi Niradhar Anudan Yojana Branch / Talathi Office.”

These are quotations from the fetched page. They do not establish requirements
that the page does not state.

## Rule-by-rule findings

| Rule ID | Proposed claim | Evidence status | Exact evidence | Location | Analysis and gap | Suggested change (not applied) |
|---|---|---|---|---|---|---|
| `IGNWPS-MH-WIDOW-01` | `is_widow eq true` | `supported` | “A widow in age group of 40 to 79 years whose family falls under Below Poverty Line is eligible under this Scheme.” | S1, “Eligibility Criteria” | Directly supports the widow condition in the proposed rule. The page does not define proof or edge-case interpretation, but those are not encoded in this boolean rule and should not be invented. | No rule-value change suggested. Separately ask Role 1 whether the user-facing definition or evidence requirements need clarification. |
| `IGNWPS-MH-AGE-MIN-01` | `age gte 40`, measured on mock application date | `partially_supported` | “in age group of 40 to 79 years” | S1, “Eligibility Criteria” | The page states the range but not the calculation date or boundary convention. Reviewer decision for this mock: calculate completed age on the application date; 40 is included. | Apply this interpretation only in the synthetic mock flow; it is a reviewer decision, not a detail stated on S1. |
| `IGNWPS-MH-AGE-MAX-01` | `age lte 79`, measured on mock application date | `partially_supported` | “in age group of 40 to 79 years” | S1, “Eligibility Criteria” | The page states the range but not the calculation date or boundary convention. Reviewer decision for this mock: calculate completed age on the application date; 79 is included. | Apply this interpretation only in the synthetic mock flow; it is a reviewer decision, not a detail stated on S1. |
| `IGNWPS-MH-BPL-01` | `bpl_status eq "confirmed"` when a government BPL card is shown | `partially_supported` | “whose family falls under Below Poverty Line” | S1, “Eligibility Criteria” | S1 supports the family-level BPL condition, but does not state which proof is required. Reviewer decision for this mock: a government BPL card must be shown. If it is not shown, status is unverified; do not treat that alone as proof that the family is not BPL. | For mock use, define `confirmed` as the synthetic applicant showing a government BPL card. Keep “not shown/unverified” separate from a verified BPL-negative status. |

The `supported` label above means the source text directly supports that
specific atomic claim; it does not certify that the page is current. The age
and BPL rules remain
`partially_supported` because their operational interpretation is not fully
specified by S1, although the reviewer has supplied mock-only interpretations
below. No rule is marked `contradicted`: the accessible page did not
contradict these proposed conditions. That is not proof that no conflicting
source exists.

## Reviewer decisions for the mock portal

The project reviewer made these decisions on 2026-10-30:

| Topic | Reviewer decision | Scope and evidence note |
|---|---|---|
| Source baseline | Use the reviewed Maharashtra government page as the latest rule baseline for this mock submission. | This is an explicit mock-project assumption. The page's displayed date is ambiguous, so this review does not independently prove it is the latest government rule for real applications. |
| Age boundaries | Include both 40 and 79. | Ages 39 and 80 fall outside the mock rule. S1 states “40 to 79 years”; endpoint inclusion is the reviewer's interpretation. |
| Age calculation | Calculate completed age on the mock application date. | The source does not specify the date; this is the reviewer's chosen rule for the mock. |
| BPL evidence | The applicant must show a government BPL card for the mock to treat BPL status as confirmed. | This evidence requirement comes from the reviewer, not from S1. If no card is shown, treat status as unknown and ask for the evidence; do not infer a verified negative. |

These decisions are the reviewer's sign-off for the criteria and assumptions
used by the synthetic mock portal. They do not establish government policy
outside that demo.

## Independent second-model check

An independent AI reviewer was asked to inspect S1 and the four atomic claims
without seeing this report's conclusions. It independently found the widow
condition and family-level BPL requirement directly stated by the page, while
classifying both age-bound rules as `partially_supported` because the page
does not explicitly settle inclusivity. It also found that the page does not
specify the age-as-of date, BPL proof or verification process, or establish
currentness. The second reviewer noted the displayed `Date: 01/01/2000 -`
without treating it as proof of a last-updated date.

The second review assessed “family BPL status is required” as an atomic claim;
the rule table above assesses the fixture's more specific
`bpl_status eq "confirmed"` mapping, including what `confirmed` means. These
are different claim scopes, not conflicting conclusions. Model/provider
identity is unavailable. This AI review is supporting evidence only, not
human policy review or approval.

## Schema and fixture observations

1. `PolicySource.collected_at` is `2026-10-28`; this review re-fetched S1 on
   `2026-10-30`. The source's displayed `01/01/2000 -` value should not be
   interpreted as a verified last-updated date without confirmation.
2. The internal `source_clause_id` value
   `IGNWPS-MH-ELIGIBILITY-01` is not a clause identifier visibly printed on
   S1. It can be an internal anchor only if the project documents its mapping
   to an exact quoted section/text and URL. It must not be presented as an
   official government clause number.
3. Fixture version `0.2.0` stores synthetic date of birth and application
   date; age is calculated as completed years on the application date.
   February 29 birthdays advance on March 1 in non-leap years in this
   implementation. This convention is a technical choice for the demo and
   should be revisited if a real application flow is ever considered.
4. The generic `PolicyRule.value: bool | int | str` and independent
   `field`/`operator` fields allow combinations that may be semantically
   invalid (for example, an age comparison with a text value). Add
   cross-field validation and explicit units before using these models as
   executable rules.
5. Fixture version `0.2.0` records whether a government BPL card was shown.
   A card not shown maps to unknown BPL status and `cant_tell`, not a verified
   negative. A separate verified-negative state is not represented.
6. The fixture records reviewer name, decision, date, and mock-only scope.
   Its overall status remains `draft_pending_technical_review`; reviewer
   approval does not mean the implementation has passed technical checks.
7. Each scenario embeds an `expected_verdict`. Keep this existing development
   fixture out of prompts/tools used for evaluation runs. It is not a
   held-out set and must not be treated as independent evaluation evidence.
8. The policy page lists the application offices quoted above, but the schema
   has no application-channel field. The page excerpt does not specify a
   required document checklist. Keep documents `not_verified`; do not infer
   extra requirements.

## Remaining review and implementation notes

| Remaining issue | Why it remains open | Suggested owner |
|---|---|---|
| Currentness for real applications | The reviewer accepts S1 as the latest baseline for the mock, but its displayed date is ambiguous and no later-amendment search was completed. Do not extend the mock assumption to real applications. | Roles 1 and 2, if the project later targets real-world guidance |
| Record source mapping | `IGNWPS-MH-ELIGIBILITY-01` is not printed as an official clause number; map it to the exact quoted text and URL as an internal identifier. | Roles 1 and 2 |
| Verify translations | English, Hindi, and Marathi scheme names, benefit text, and expected explanations were not independently checked. | Role 1 and fluent language reviewers |
| Verify technical behavior | Run the focused fixture tests and confirm the UI shows the calculated age and card evidence correctly. | Technical owner |

## Reviewer-approved mock development cases

The reviewer approved the mock-only interpretations above. These expected
outcomes are **reviewer-approved development examples for the mock**, not
evidence that the official page specifies every operational detail. Do not
copy these into protected held-out data.

| Case ID | Synthetic facts | Reviewer-approved mock result | Rule/source being tested | Human label/reviewer |
|---|---|---|---|---|
| DEV-IGNWPS-AGE-39 | Maharashtra, widow, age 39 on application date, government BPL card shown | `not_eligible` | Lower age boundary; S1 Eligibility Criteria | Project reviewer, 2026-10-30 |
| DEV-IGNWPS-AGE-40 | Maharashtra, widow, age 40 on application date, government BPL card shown | `eligible` | Included lower age boundary; S1 Eligibility Criteria | Project reviewer, 2026-10-30 |
| DEV-IGNWPS-AGE-41 | Maharashtra, widow, age 41 on application date, government BPL card shown | `eligible` | Age range; S1 Eligibility Criteria | Project reviewer, 2026-10-30 |
| DEV-IGNWPS-AGE-79 | Maharashtra, widow, age 79 on application date, government BPL card shown | `eligible` | Included upper age boundary; S1 Eligibility Criteria | Project reviewer, 2026-10-30 |
| DEV-IGNWPS-AGE-80 | Maharashtra, widow, age 80 on application date, government BPL card shown | `not_eligible` | Upper age boundary; S1 Eligibility Criteria | Project reviewer, 2026-10-30 |
| DEV-IGNWPS-NOT-WIDOW | Maharashtra, not widowed, age 52 on application date, government BPL card shown | `not_eligible` | Widow condition; S1 Eligibility Criteria | Project reviewer, 2026-10-30 |
| DEV-IGNWPS-BPL-NO-CARD | Maharashtra, widow, age 52 on application date, no government BPL card shown | `cant_tell` / need more information; do not guess | Mock BPL evidence requirement; reviewer decision | Debadyuti Roy, 2026-10-30 |
| DEV-IGNWPS-BPL-CARD | Maharashtra, widow, age 52 on application date, government BPL card shown | `eligible` | Card shown confirms BPL for mock; reviewer decision | Debadyuti Roy, 2026-10-30 |

## Overall disposition

**Disposition: `changes_required`**

S1 is an accessible, official, scheme-specific source. It directly supports
the atomic widow condition and states the 40–79 age range and BPL condition.
The project reviewer has approved the inclusive boundaries, application-date
age calculation, use of a government BPL card, and S1 as the baseline for
this mock only. Fixture version `0.2.0` now records those decisions using
synthetic dates, card-shown state, and reviewer metadata. The page itself does
not establish those operational details or prove currentness. Technical
checks remain before this fixture can be treated as an approved executable
ruleset.

The second pass re-fetched the same page and reviewed fixture version `0.1.0`;
the source text and rule values were unchanged. An independent second-model
check supported the source reading but is not the basis for the human
decisions above. The reviewer sign-off was provided in this conversation on
2026-10-30. Fixture and schema implementation changes are recorded in version
`0.2.0`; those changes implement the mock assumptions and do not alter S1.

## Human sign-off

- Policy/domain reviewer: Debadyuti Roy
- Decision: `approved_for_mock_portal`
- Scope: synthetic mock portal; decisions first recorded against fixture `0.1.0` and implemented in `0.2.0`
- Conditions: do not present this as verified current government policy or use it to decide a real person's eligibility. Keep the fixture status unchanged until the implementation and reviewer metadata reflect this sign-off.
- Date: 2026-10-30

This report applies only to `IGNWPS-MH`, the Maharashtra page retrieved for
this review, and the mock decisions recorded above. Its sign-off is limited
to the synthetic mock portal; it does not approve any other scheme or decide
any individual's eligibility.
