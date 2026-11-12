# APY-IN scheme evidence review

> **Draft evidence review only. Not policy approval or an eligibility
> decision.**

## Review identity

- Scheme name: Atal Pension Yojana (APY)
- Scheme ID: `APY-IN`
- Jurisdiction: India, central scheme
- Applicable-as-of date: 2026-11-11
- Proposed rule-set version: gold draft schema version `1` (`hand_drafted`)
- Input file/source: `data/schemes/rule_gold_drafts/apy.json`
- Review date: 2026-11-11
- Reviewer model/provider: not recorded
- Skill/prompt version: `review-scheme-evidence` playbook
- Independent second-model review: not performed
- Human policy decision: pending

## Source register

| Source ID | Publisher and title | Official scheme-specific source? | URL | Retrieved on | Publication/effective date | Location (page/heading/clause) | Limitations |
|---|---|---|---|---|---|---|---|
| APY-2023 | Department of Financial Services, Ministry of Finance, Government of India, “Atal Pension Yojana (APY) - Details of the Scheme” | Yes; official APY scheme detail PDF hosted on Jansuraksha | https://jansuraksha.gov.in/Files/APY/ENGLISH/APY.pdf | 2026-11-11 | PDF metadata creation/modification date: 2023-11-30; tax exclusion stated as effective from 2022-10-01 | Page 2, section 3; page 3, section 5.2 | No revision number or consolidated-through date is printed in the PDF. Metadata is not itself a government-issued effective date. |
| APY-2026-CONT | Department of Financial Services, Ministry of Finance, Government of India, APY continuation announcement | Official government announcement, but not a scheme eligibility instrument | https://financialservices.gov.in/sites/default/files/2026-01/DFS-website.pdf | 2026-11-11 | PDF metadata creation/modification date: 2026-01-21 | Page 1 | Announces continuation and funding support through FY 2030-31; it does not restate or amend entry eligibility. Its silence on eligibility is not proof that no separate amendment exists. |
| APY-PFRDA-TRAINING | Pension Fund Regulatory and Development Authority, “APY Training Material” | Official regulator resource; not a primary eligibility instrument | https://www.pfrda.org.in/w/financial-literacy/training/training-material/apy-training-material | 2026-11-11 | PFRDA sitemap last-modified date: 2025-06-11 | APY Training Material page | The page lists training presentations in multiple languages, not a dated eligibility circular or consolidated scheme rule. Used only as a check for newer official explanatory material. |

Downloaded-source SHA-256 values for audit:

- `APY-2023`: `3b7291f47c9e17dc3378745e0fb45100b3119deb699d9cf5cfc353b6390ef939`
- `APY-2026-CONT`: `e1b660cde2d7f0eb68c2863d22fdd81963b2d7171d72e175761abaa5f7912b65`

## Rule-by-rule findings

| Rule ID | Proposed claim (field/operator/value/scope) | Evidence status | Exact source quote | Source ID and precise location | Analysis, gaps, or conflict | Suggested change (not applied) |
|---|---|---|---|---|---|---|
| APY-IN-R01 | Joining age `gte 18 years` | `supported` | “The minimum age of joining APY is 18 years and maximum age is 40 years.” | APY-2023, p. 2, section 3 | Directly supports the lower joining-age boundary. The source does not specify an age-calculation convention beyond age at joining. | None for the gold eligibility claim. Confirm the age-calculation convention before app implementation. |
| APY-IN-R02 | Joining age `lte 40 years` | `supported` | “The minimum age of joining APY is 18 years and maximum age is 40 years.” | APY-2023, p. 2, section 3 | Directly supports the upper joining-age boundary. | None for the gold eligibility claim. |
| APY-IN-R03 | Applicant is a citizen of India (`eq true`) | `supported` | “APY is open to all citizens of India who have a savings bank account.” | APY-2023, p. 2, section 3 | Directly supports the citizenship condition for joining. | None for the gold eligibility claim. |
| APY-IN-R04 | Applicant has a savings bank account (`eq true`) | `supported` | “APY is open to all citizens of India who have a savings bank account.” | APY-2023, p. 2, section 3 | Directly supports the account condition; the quoted clause does not further specify account type or provider. | Do not narrow the claim to a particular bank or account subtype without separate official evidence. |
| APY-IN-R05 | Applicant is or has been an income-tax payer (`eq true`) is excluded from joining | `supported` | “From 1st October, 2022, any citizen who is or has been an income-tax payer, is not eligible to join APY.” | APY-2023, p. 2, section 3 | Directly supports the exclusion from joining from the stated date. The gold field meaning must retain “has been,” not only current payer status. | Keep the scheme-specific “is or has been” time scope; do not reduce it to current-year tax status. |

## Questions requiring a person

| Question | Why the source does not settle it | Suggested reviewer |
|---|---|---|
| Is the 2023 scheme detail PDF still the latest detailed APY eligibility instrument, with no later eligibility amendment or circular? | The 2026 DFS announcement is a continuation/funding notice, not an eligibility instrument; the PDF has no revision or consolidated-through date. The official PFRDA training page is not a substitute for checking all applicable circulars. | APY domain/policy reviewer |
| Is the current rule package intentionally limited to joining eligibility, excluding account servicing after enrollment? | APY-2023 section 5.2 states: “In case a subscriber, who joined on or after 1st October, 2022, is subsequently found to have been an income-tax payer on or before the date of application, the APY account shall be closed and the accumulated pension wealth till date would be given to the subscriber.” This is a post-enrollment action, not an entry-eligibility test, and is absent from the five-rule gold draft. | APY domain/policy reviewer and technical owner |

## Provisional development tests

These are suggestions for a **development** test set. Have a human label the
expected result before tuning. Do not place protected held-out cases here.

| Case ID | Synthetic facts | Provisional expected result | Rule/source being tested | Human label/reviewer |
|---|---|---|---|---|
| APY-AGE-17 | Age at joining 17; Indian citizen; savings bank account; not an income-tax payer | `not_eligible` — provisional | APY-IN-R01; APY-2023 p. 2, section 3 | Pending |
| APY-AGE-18 | Age at joining 18; Indian citizen; savings bank account; never an income-tax payer | `eligible` — provisional | APY-IN-R01/R03/R04/R05; APY-2023 p. 2, section 3 | Pending |
| APY-AGE-40 | Age at joining 40; Indian citizen; savings bank account; never an income-tax payer | `eligible` — provisional | APY-IN-R02/R03/R04/R05; APY-2023 p. 2, section 3 | Pending |
| APY-AGE-41 | Age at joining 41; Indian citizen; savings bank account; never an income-tax payer | `not_eligible` — provisional | APY-IN-R02; APY-2023 p. 2, section 3 | Pending |
| APY-TAX-EVER | Eligible age; Indian citizen; savings bank account; previously paid income tax, even if not currently a payer | `not_eligible` — provisional | APY-IN-R05; APY-2023 p. 2, section 3 | Pending |
| APY-UNKNOWN | Missing or unknown age, citizenship, account, or tax-history answer | `cant_tell` — provisional | APY-IN-R01-R05; APY-2023 p. 2, section 3 | Pending |

## Overall disposition

Disposition: `ready_for_human_review`

**Decision for this review:** Use APY-2023 as the latest detailed official
eligibility source found in the official sources reviewed. Treat APY-2026-CONT
as a continuation and funding update only; it provides no basis to change the
five joining-eligibility rules. The five proposed claims are directly
supported by APY-2023. This is the most defensible source set found as of
2026-11-11, not a guarantee that no later or separately published amendment
exists. On 2026-11-11, Roy-developer approved this limited source set for
synthetic mock use while acknowledging that later circulars were not
independently ruled out.

The review is limited to entry eligibility. Section 5.2's post-enrollment
account-closure condition is outside the activated joining-only package.
`src/rules/packages/apy_in.v1.json` is active for synthetic mock use only; no
government enrollment or integration is performed. APY-specific fact
definitions are in the registry, but question and privacy reviews remain
pending. The shared gold-only candidate meanings remain separate from app
intake approval.

## Human sign-off

- Policy/domain reviewer: Roy-developer (identity supplied by the user; role was entered as “assumed role1” and is not independently verified)
- Decision: `approved` for the five entry-eligibility rules in a synthetic mock package only
- Conditions or corrections: Approval acknowledges that later eligibility circulars were not independently ruled out. The package does not cover post-enrollment account servicing. Privacy-purpose/retention, Hindi/Marathi question review, and broader technical data-flow review remain pending.
- Date: 2026-11-11

Approval applies only to the listed scheme, jurisdiction, source versions,
and rule-set version. It does not approve any other scheme or decide any
individual's eligibility.
