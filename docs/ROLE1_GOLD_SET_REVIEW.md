# Role 1 gold set review (development schemes)

**Status:** SIGNED OFF by Nidhi Kaushik (Role 1) on 2026-11-11 after her review, with the section 2 decisions accepted.
**Reviewed material:** the gold drafts, copied from the source clone at commit `b6fe75d` (branch `b_passages_data`, "script for scheme onboarding"). Files: `data/schemes/rule_gold_drafts/`, `data/schemes/rule_gold_selection.json`, `docs/RULE_GOLD_SET_SELECTION.md`.
**Checked so far (automated):** for all 17 development schemes, every rule's `source_passage_id` exists and its `source_quote` appears verbatim in that passage (0 failures across 89 rules: 85 in the original 15, 4 in the 2 added later). The 9 held-out schemes were checked the same way; one quote (PSGS-DIP-IN-R03) differs from its passage only in whitespace.
**Not yet checked (needs the reviewer):** whether each rule's field, operator and value correctly express its quote, and the source pages themselves. The first-pass verdicts below come from reading each quote against its rule.

## 1. Per-scheme result

| # | Scheme | Rules | First-pass verdict | Why / change needed |
|---|---|---|---|---|
| 1 | IGNWPS-IN | 5 | OK | Age 40-79, widow, BPL, remarriage exclusion all match their quotes. |
| 2 | IGNWPS-MH | 4 | OK | Matches the quote. Same rules as the live package. |
| 3 | NSAP-IGNOAPS-IN | 3 | OK | Citizen, BPL, age >= 60. |
| 4 | IGNOAPS-MH | 4 | OK, with a gap | Age >= 65 (differs from central 60), state resident, no other pension. The live package only checks age and BPL list, so R03/R04 are not live yet. |
| 5 | PM-KISAN-IN | 10 | Change needed | See flagged rules R09 and R10. Fact names also differ from the live package (`family_has_*` vs live facts). |
| 6 | IGNDPSM-MH | 6 | OK | Age 18-79, 80% disability, no other pension. |
| 7 | IGNDPS-IN | 5 | OK, confirm | 80% inclusive is a project-owner decision (2026-11-10); one passage says "more than 80%". |
| 8 | FADSE-MH | 7 | OK | Age 18-50, income strictly below Rs 1,00,000, 40% disability. |
| 9 | FASETDP-MH | 5 | OK | Matches the quotes. |
| 10 | NFBSM-MH | 5 | OK | Breadwinner age 18-59, BPL, resident, family member. |
| 11 | APY-IN | 5 | OK | Age 18-40, citizen, savings account; income-tax-payer exclusion. |
| 12 | PMSBY-IN | 5 | OK | Age 18-70, account, consent; institutional exclusion. |
| 13 | PMJJBY-IN | 5 | OK, confirm R03 | See flagged rule R03. Cover ending at 55 is not encoded (listed in the file). |
| 14 | PRE-DIS-IN | 8 | Change needed | See flagged rule R07. |
| 15 | POST-DIS-IN | 8 | Change needed | R05 and R07, below. |
| 16 | TMDVSO-MH | 1 | New, pending review | Only the category rule is encoded. Age, education and fitness follow the Motor Vehicle Act with no figures, so they go to a caseworker. |
| 17 | WMCL-IN | 3 | New, pending review | SC/ST labourer's child, education after Class 10, exclusion for supervisory staff. The "first two surviving children" limit and per-benefit conditions are not encoded. |

Schemes 16 and 17 are hand-drafted with new fact names (quotes verified). They need the same line-by-line review as the others before they count as reviewed gold. TFEFVSSSHS-MH, the third addition, is in the held-out split and is covered in `docs/ROLE1_HELDOUT_POLICY_CHECK.md`.

## Targets and actual numbers
| Item | Asked | Actual | Status |
|---|---|---|---|
| Schemes listed with URL and collection date | 40-60 | 42 | Met. MJPJAY-MH has only a myScheme URL. |
| Gold schemes (development) | 15 | 17 (15 reviewed, 2 pending) | Met. |
| Held-out schemes | set by Role 5 | 9 (8 reviewed, 1 pending) | Policy check done; 1 does not fit yet. |
| Gold rules | not fixed | 89 development, 62 held-out | Quotes verified. |
| Personas | 60 | 60 (31 + 3 + 26) | Met. 34 on live schemes run (33 match); 26 not run. |
| Independent labels on personas | 2 labellers | 1 | Open: your labelling. |
| Written policy | refusals, caseworker, official sources | `docs/POLICY.md` approved | Met. |
| Demo script | 3 languages | English, Hindi, Marathi key lines | Drafted; native-speaker check pending. |

## 2. Flagged rules: proposed decisions (reviewer must confirm)

| Rule | Issue | Proposed decision |
|---|---|---|
| PM-KISAN R09 (owned land on 2019-02-01) | Cut-off date with a succession exception that the schema can't express. | Exclude R09 from scoring and keep it listed as "not encoded", the same as the file's own note. |
| PM-KISAN R10 (name in land records) | The North-East and Jharkhand exception can't be expressed. | Keep R10 as a plain AND rule and list the exception as not encoded. |
| PRE-DIS R07 / POST-DIS R07 (at most 2 students per family) | It is unclear whether the count includes the applicant. | Define the fact as "other students in the family already receiving", with the limit kept at <= 2 including this student. Confirm against the source. |
| PMJJBY R03 (savings bank account) | The source says bank or Post Office account holder. | Keep; rename the intent to "has bank or post office account" when the fact vocabulary is next revised. |
| POST-DIS R05 (post-matric student) | The quote says "Class 11 or 12" but the note says it also covers diploma, degree and PG. | Change the quote or the rule so they agree; the wider definition looks right. |

Also noted, not part of the five flags:
- IGNOAPS-MH: central threshold 60 and state 65 conflict. The state rule (65) is right for the Maharashtra scheme, and the conflict is handled by caseworker referral (policy section 2).
- Many rules are `kind: exclusion` (for example IGNWPS-IN R05, APY R05, PMSBY R04, PRE-DIS R06/R08). They apply when the fact is true. That is not an error, but the exclusion facts must be asked as "does this apply" questions.
- My earlier statement that those rules "look inverted" was wrong; I had not read the `kind` field.

## 3. Requested changes to the gold drafts (do not edit the source files)
Requests:
1. **POST-DIS-IN-R05:** make the quote and the rule agree. The quote says "Class 11 or 12"; the note says diploma, degree and PG are also covered. Quote the passage that lists all levels, or narrow the rule.
2. **PM-KISAN-IN-R09 / R10:** add a `note` that the succession and North-East/Jharkhand exceptions are not encoded, and mark R09 `needs_human_review`.
3. **PRE-DIS-IN-R07 / POST-DIS-IN-R07:** state in the note whether the "2 students" limit includes the applicant.
4. **PMJJBY-IN-R03:** note that the source covers bank or Post Office account holders.
5. **IGNOAPS-MH:** state in the note that the state threshold (65) overrides the central one (60).

Open source gaps (I could not verify an official URL from here and will not guess one):
- **MJPJAY-MH:** only a myScheme page. Needs the state health department page.
- **TFEFVS-MH (held-out):** only a UMANG page. Needs a Social Justice department or DoSJE page, as TFEFVSSSHS-MH has.
- **TFEFVSSSHS-MH, TMDVSO-MH, WMCL-IN:** empty gold drafts; fill them or leave out of the gold set.

## 4. Persona check against the live engine
Of the 60 development personas, 34 expected verdicts concern the 3 live schemes (IGNWPS-MH, IGNOAPS-MH, PM-KISAN-IN). I ran these through the rule engine with typed facts: **33 match**. The one difference (IGNWPS-DEV-007) is wording only: the persona says `cant_tell`, the engine says `need_more_information`. The other 26 personas cover gold-only schemes with no live rule package, so their verdicts come from the draft gold rules and need your independent label.

## 5. Sign-off (reviewer completes)
| Field | Value |
|---|---|
| Reviewer | Nidhi Kaushik  |
| Date | 2026-11-11 |
| Commit reviewed | `b6fe75d` |
| Decision on flagged rules (section 2) | Proposed decisions accepted; section 3 requests go to the gold-set owner |
| Overall | Accepted for the 15 development schemes, with the section 3 changes outstanding |
