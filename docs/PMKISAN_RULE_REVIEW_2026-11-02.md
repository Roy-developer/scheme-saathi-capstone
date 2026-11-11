# Scheme evidence review: PM-KISAN

> **Draft evidence review only. Not policy approval or an eligibility
> decision. Any future implementation must be limited to a synthetic mock
> unless current official rules and the intended use are separately reviewed.**
>
> **Amended 2026-11-09:** the reviewer approved the rules for the synthetic mock
> only. See the amendment at the end of this document.

## Review identity

- Scheme: Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)
- Scheme ID: `PM-KISAN-IN`
- Jurisdiction: India
- Applicable-as-of date requested: 2026-11-02
- Proposed rule-set version: `0.1.0-draft`
- Input evidence: `data/schemes/passages/pm_kisan_passages.json`; proposed executable rules do not yet exist
- Review date: 2026-11-02
- Review method: direct inspection of the official portal and linked official operational-guidelines PDF
- Independent second-model review: performed 2026-11-02; reviewer/provider identity unavailable; findings summarized below
- Human policy decision: use the 2020 guideline as the source baseline for a synthetic mock draft only; approval of individual rules remains pending
- Draft artifact: `data/schemes/rule_drafts/pmkisan_in.v0.1.0-draft.json` (not loaded by the runtime)

## Source register

| Source ID | Publisher and title | Official scheme-specific source? | URL | Retrieved on | Publication/effective date | Location | Limitations |
|---|---|---|---|---|---|---|---|
| S1 | Government of India, Ministry of Agriculture & Farmers Welfare, *PM-KISAN Scheme Operational Guidelines* | Yes | [Official PDF](https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalGuidelines(English).pdf) | 2026-11-02 | Cover says “Revised as on 29.03.2020” | pp. 2–3, sections 1–5; p. 6, section 6.1 | Official but dated 2020. The source does not establish that all criteria remain current in 2026. Section 5.2 includes a 2019 cutoff and a five-year period, so current treatment requires newer confirmation. |
| S2 | PM-KISAN official portal, homepage | Yes | [pmkisan.gov.in](https://pmkisan.gov.in/) | 2026-11-02 | Page displayed a 24th installment release on 2026-10-30 | Homepage notices | Confirms current scheme operation and an eKYC notice, but does not publish the complete current eligibility criteria or resolve the 2020 guideline's cutoff clauses. |

S1 states:

> “A landholder farmer’s family is defined as ‘a family comprising of husband,
> wife and minor children who owns cultivable land as per land records of the
> concerned State/UT’.”

It also states:

> “All Institutional Land holders”

are excluded, and lists further exclusions for farmer families, including
specified public office holders, government employees and pensioners, income
tax payers, and practicing professionals.

The official portal currently states:

> “eKYC is MANDATORY for PMKISAN Registered Farmers.”

This is an operational condition for registered farmers, not evidence that
eKYC alone establishes initial eligibility.

## Rule-by-rule findings

| Rule ID | Proposed claim (field/operator/value/scope) | Evidence status | Exact source quote | Source ID and precise location | Analysis, gaps, or conflict | Suggested change (not applied) |
|---|---|---|---|---|---|---|
| `PMKISAN-LAND-FAMILY-01` | Applicant belongs to a farmer family comprising husband, wife, and minor children, with cultivable land in State/UT land records | `partially_supported` | “a family comprising of husband, wife and minor children who owns cultivable land as per land records of the concerned State/UT” | S1, p. 2, section 3 | Supports the stated family and land-record basis in the 2020 guideline. Currentness, family-member interpretation, land-record exceptions, and the 2019 cutoff's present treatment remain unresolved. | Do not implement as a current eligibility test until the current landholding/cutoff policy is confirmed. |
| `PMKISAN-INSTITUTIONAL-LAND-01` | Institutional landholders are excluded | `partially_supported` | “All Institutional Land holders” | S1, p. 2, section 4.1(a) | Directly stated in the dated guideline, but currentness has not been established. | Preserve as a candidate exclusion pending current-source confirmation. |
| `PMKISAN-OFFICE-HOLDER-01` | A farmer family is excluded if a member is a former or present constitutional post holder, specified minister, legislator, municipal-corporation mayor, or district-panchayat chairperson | `partially_supported` | “Former and present holders of constitutional posts” | S1, p. 2, section 4.1(b)(i)–(ii) | The listed categories are supported by the 2020 source. Definitions, edge cases, and currentness require review. | Do not infer the broad meaning of “constitutional posts”; encode only a reviewer-approved closed list if still current. |
| `PMKISAN-GOV-EMPLOYEE-01` | A farmer family is excluded for specified serving or retired government/PSE/autonomous-institution/local-body employees, with stated MTS/Class IV/Group D exceptions | `partially_supported` | “All serving or retired officers and employees of Central / State Government Ministries / Offices / Departments” | S1, pp. 2–3, section 4.1(b)(iii) | The full clause has several employer and employee-category conditions and explicit exceptions. A simple “government employee” yes/no question would be too broad. | Confirm exact current scope and exceptions; model unknown status separately. |
| `PMKISAN-PENSION-01` | A farmer family is excluded if a member receives monthly pension of ₹10,000 or more, subject to the stated employee-category exception | `partially_supported` | “All superannuated / retired pensioners whose monthly pension is Rs.10,000/- or more” | S1, p. 3, section 4.1(b)(iv) | Threshold and exceptions are in the dated source. Clarify what pension types count and verify currentness. | Ask reviewer to confirm the pension measure and scope before implementation. |
| `PMKISAN-INCOME-TAX-01` | A farmer family is excluded if a member paid income tax in the last assessment year | `partially_supported` | “All Persons who paid Income Tax in last assessment year.” | S1, p. 3, section 4.1(b)(v) | The clause is direct but dated. The applicable assessment-year interpretation should be explicit for any mock test. | Confirm current wording and the intended mock reference year. |
| `PMKISAN-PROFESSIONAL-01` | A farmer family is excluded if a member is a registered doctor, engineer, lawyer, chartered accountant, or architect who practices the profession | `partially_supported` | “Professionals like Doctors, Engineers, Lawyers, Chartered Accountants, and Architects registered with Professional bodies and carrying out profession” | S1, p. 3, section 4.1(b)(vi) | Both registration and active practice matter in the source; profession alone is insufficient. Currentness and definitions need confirmation. | Keep these conditions separate; do not reduce to a profession-only checkbox. |
| `PMKISAN-NRI-01` | NRI farmer families are excluded when uploaded as new beneficiaries | `partially_supported` | “all land holding farmers’ families who are Non-resident Indians (NRIs) … shall be excluded” | S1, p. 3, section 4.1(c) | The clause is explicitly scoped to new beneficiaries. Currentness and interaction with already registered beneficiaries need confirmation. | Preserve the “new beneficiaries” scope if confirmed; do not apply it more broadly. |
| `PMKISAN-LAND-CUTOFF-01` | Eligibility uses a landholding cutoff date and later ownership changes have specified exceptions | `insufficient_evidence` for a 2026 rule | “The cut-off date for determination of eligibility … shall be 01.02.2019” | S1, p. 3, section 5.2 | The same clause says no changes thereafter would be considered for the next five years. That period has elapsed. The available sources do not show what rule replaced or extended it, so it must not be encoded as current. | Obtain a current official circular/guideline that resolves land transfers, inheritance, and cutoff treatment before deciding eligibility. |
| `PMKISAN-EKYC-01` | eKYC is mandatory for registered farmers | `partially_supported` | “eKYC is MANDATORY for PMKISAN Registered Farmers.” | S2, official portal homepage notice, retrieved 2026-11-02 | Current notice supports an operational requirement for registered farmers; it does not establish applicant eligibility, land ownership, or a full eKYC decision workflow. | Treat as a separate servicing/verification step, not an eligibility rule, unless the reviewer defines a bounded mock scenario. |

## Questions requiring a person or newer official evidence

| Question | Why the source does not settle it | Suggested reviewer |
|---|---|---|
| What current official rule governs landholding cutoff and transfers in 2026? | S1 is revised 2020 and its five-year cutoff period has elapsed. | Policy/domain reviewer; obtain current Ministry/PM-KISAN circular |
| Does the 2020 farmer-family definition and every listed exclusion remain unchanged? | The homepage confirms operation, not current eligibility rules. | Policy/domain reviewer |
| How should an intake form ask about the whole farmer family and its members without collecting excessive personal data? | Exclusions are family-level and involve several other members' public-service, pension, tax, and professional status. | Product and privacy reviewers |
| Which facts can a synthetic applicant self-report, and which must remain “needs official verification”? | The guideline assigns identification to State/UT governments using records and declarations; the app cannot query those records. | Policy/domain and technical reviewers |
| Should eKYC be represented at all in eligibility, or as a separate registered-beneficiary servicing step? | Current homepage notice is specifically about registered farmers. | Policy/domain reviewer |

## Provisional development tests

These are not executable acceptance tests and have no final labels. They must
be revised after a current rule baseline is confirmed and the reviewer labels
the expected outcomes.

| Case ID | Synthetic facts | Provisional expected result | Rule/source being tested | Human label/reviewer |
|---|---|---|---|---|
| `DEV-PMKISAN-LAND-RECORD` | Farmer family reports cultivable land recorded by the State/UT | `cant_tell` until official record and current cutoff policy are verified | S1 section 3 / section 5 | Pending |
| `DEV-PMKISAN-INSTITUTIONAL` | Land is held by an institution | `not_eligible` under the 2020 text; current policy confirmation required | S1 section 4.1(a) | Pending |
| `DEV-PMKISAN-INCOME-TAX` | One family member paid income tax in the applicable assessment year | `not_eligible` under the 2020 text; current policy and year interpretation required | S1 section 4.1(b)(v) | Pending |
| `DEV-PMKISAN-UNKNOWN-EXCLUSION` | Family-member exclusion facts are unknown | `cant_tell`; do not infer eligible | S1 section 4.1(b) | Pending |
| `DEV-PMKISAN-NRI-NEW` | New beneficiary is an NRI farmer family | `not_eligible` under the 2020 text; current policy confirmation required | S1 section 4.1(c) | Pending |

## Overall disposition

**Disposition: `changes_required`**

The dated official guideline provides a useful candidate rule set, but the
current 2026 eligibility baseline is not established, especially for the
expired landholding cutoff. The report and draft artifact record the source and gaps, not approval to
decide eligibility. A separate assessment-only endpoint may flag potential
non-qualification under the dated text or request official verification. It
cannot return an eligible result. The draft remains outside the runtime rule
package registry.

The current deterministic schema is also widow-specific: its request fields
and rule types cover widow status, age, and BPL-card confirmation. PM-KISAN
uses a separate assessment request schema and dated-rule screen. It does not
make or store a government eligibility determination.

## Human sign-off

- Policy/domain reviewer: pending
- Decision: `pending`
- Baseline decision recorded: 2020 guidelines may be used for a synthetic mock draft only; this does not approve each rule or establish current policy
- Conditions or corrections: resolve the landholding cutoff and the questions above before enabling any definitive eligibility decision
- Date: pending

Any later approval must name the exact PM-KISAN rule-set version and remain
limited to the stated mock scope. It must not be presented as a government
determination or an individual farmer's verified eligibility.

## Independent second-model review

An independent model reviewed the official 2020 guidelines and live PM-KISAN
portal without reading the first review report. Its provider/model identity was
not available, and no paid API call was made.

The second review found the farmer-family definition and listed exclusions
largely **supported by the wording of the 2020 guideline**, while flagging
undefined terms, open-ended categories, exceptions, and moving time references
that need careful modeling. It independently identified the 2019 landholding
cutoff and its five-year period as **insufficient evidence for a current
2026 rule**. It also noted that the guideline assigns beneficiary
identification to State/UT governments, so self-reported answers cannot verify
real eligibility.

The independent review's recommendation was that a restricted synthetic draft
may be kept only if the unresolved cutoff remains blocking and the package
cannot return an eligible decision. This agrees with the current draft's
disabled runtime state. It did **not** recommend enabling a production or
individual eligibility decision. The model review is supporting analysis only;
it is not human approval, legal advice, or proof of policy currentness.

Limitations: the second reviewer did not find a newer consolidated official
guideline and did not exhaustively crawl for later amendments or review every
source passage. Thus, its agreement does not resolve the currentness gap.

## Amendment 2026-11-09: approved for the synthetic mock

The review and sign-off above are kept as written. This amendment records the
reviewer's later decision.

- **Decision:** `Roy-developer` approved all eight rules in
  `src/rules/packages/pmkisan_in.v1.json`, package version `1.0.0`, status
  `approved_for_mock_portal`, for the synthetic mock portal only:
  `PMKISAN-LAND-FAMILY-01`, `PMKISAN-INSTITUTIONAL-LAND-01`,
  `PMKISAN-OFFICE-HOLDER-01`, `PMKISAN-GOV-EMPLOYEE-01`, `PMKISAN-PENSION-01`,
  `PMKISAN-INCOME-TAX-01`, `PMKISAN-PROFESSIONAL-01` and `PMKISAN-NRI-01`.
- **Baseline:** the operational guidelines revised on 2020-03-29.
- **Earlier condition not met:** this review asked that the landholding cutoff
  be resolved before any definitive eligibility decision, and the independent
  review recommended that the package not return an eligible result. The
  reviewer decided to approve the mock without resolving the cutoff and to keep
  the "Appears eligible" result with its notice. The disposition above remains
  `changes_required` for any use beyond the synthetic mock.
- **Still open:** the current landholding cutoff and transfer rules, whether the
  2020 definition and exclusions remain current, and State/UT verification of
  records. The app lists the unresolved checks with each result.
- **Not included in the rules:** `PMKISAN-LAND-CUTOFF-01` and `PMKISAN-EKYC-01`.
- **Still pending:** human labels for the provisional development tests, native-
  speaker review of the questions, and privacy review of the family-member facts.
- **Update 2026-11-09:** `Roy-developer` set the question and privacy status of all
  registered facts to approved for the synthetic mock. No separate native-speaker
  or privacy review was performed.
- **What changed in the package:** only `approval_status`, `reviewer_name` and
  `reviewed_at`. No rule, required fact or source changed.
- **Package SHA-256:** `fb59df9f7420b29d33f5a41d938cdd00f688db742e62cd989f11a948b11137a1` (previously `3e7b14c676a21a878ef5c11a0e2d2fd8e202ff50c40318299d9d644ab20cb4a7`).
- App approval: `PM-KISAN-IN` approved by `Roy-developer` on 2026-11-09 for package SHA-256 `fb59df9f7420b29d33f5a41d938cdd00f688db742e62cd989f11a948b11137a1`

**Document checklist (2026-11-09):** the demo checklist was replaced by version
`v2`, built from word-for-word text in the 2020 operational guidelines (sections
3, 6.1 and 6.2 and the essential farmer attributes) and approved at the
reviewer's instruction. It records what the guidelines say; land records are
the State's records and not a paper the applicant submits. Hindi and Marathi
labels have had no native-speaker review. The guidelines are dated 2020, and
current portal or eKYC requirements were not established.

This approval does not establish current policy and is not a government
determination or an individual farmer's verified eligibility.
