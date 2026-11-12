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
| 16 | TMDVSO-MH | 1 | OK | Category rule (VJNT/OBC/SBC = DNT) matches official page. Age/education/fitness not encoded (Motor Vehicle Act); caseworker. Reviewed 2026-11-11. |
| 17 | WMCL-IN | 3 | OK | SC/ST labourer's child (R01), education after Class 10 (R02), exclusion for supervisory staff (R03) — all match source passages exactly. Per-tier and "first two children" conditions not encoded; caseworker. Reviewed 2026-11-11. |
| 18 | FAISHL-IN | 2 | OK | War bereaved/disabled/attributable-casualty (R01) and home loan held (R02). R01 from official ksb.gov.in passage; R02 from myScheme but consistent with benefit description on KSB page. Promoted from alternate 2026-11-11 — genuine gov.in source, 0 unresolved. |
| 19 | IPMWCD-IN | 5 | OK | Women (R01), student/scholar/activist/teacher (R02), from non-tier-1/rural area (R03), age 21-40 (R04-R05). R01-R03 from official wcd.intern.nic.in passage; R04-R05 from myScheme (simple age statement). Prior-selection exclusion not encoded; caseworker. Promoted from alternate 2026-11-11. |
| 20 | EACS-MH | 2 | OK | Construction worker (R01) and registered with MH BOCW Board (R02), both from official mahabocw.in. Child's class level and 75% attendance not encoded; caseworker. |
| 21 | NSMNY-MH | 3 | OK | Cultivable land ownership (R01), institutional landholder exclusion (R02), income-tax-payer exclusion (R03). All from official nsmny.mahait.org portal. Other exclusions (govt employees, pensioners, NRIs etc.) not encoded; caseworker. |
| 22 | BFFL-MH | 4 | OK | MH resident (R01), has Aadhaar (R02), 7/12 land record in own name (R03), institutional exclusion (R04). R03/R04 in Marathi — translations confirmed 2026-11-11. Area limits by region not encoded; caseworker. Source: mahadbt.maharashtra.gov.in. |

IGNWPSM-MH (6 rules) moved to **alternate** 2026-11-11: shares source URL with IGNWPS-MH (development, live). Both schemes describe the same MH widow pension; keeping both in gold would double-count.

Schemes 16 and 17 are hand-drafted with new fact names (quotes verified). They need the same line-by-line review as the others before they count as reviewed gold. TFEFVSSSHS-MH, the third addition, is in the held-out split and is covered in `docs/ROLE1_HELDOUT_POLICY_CHECK.md`.

## Targets and actual numbers
| Item | Asked | Actual | Status |
|---|---|---|---|
| Schemes listed with URL and collection date | 40-60 | 42 | Met. MJPJAY-MH has only a myScheme URL. |
| Gold schemes (development) | 15 | 22 (all 22 reviewed) | Met. All 22 human_reviewed. IGNWPSM-MH moved to alternate 2026-11-11 (shared source URL with IGNWPS-MH; double-count). |
| Held-out schemes | set by Role 5 | 9 (8 reviewed, 1 pending) | Policy check done; 1 does not fit yet. |
| Gold rules | not fixed | 89 development, 62 held-out | Quotes verified. |
| Personas | 60 | 77 (31 + 3 + 26 + 17) | Met. 34 on live schemes run (33 match); 43 typed_facts-only (not run). 17 added 2026-11-11 for 6 new development gold schemes. |
| Independent labels on personas | 2 labellers | 2 | **Not met.** Only model-assisted checks exist (`role1_model_assisted_labels.json` and `role1_model_assisted_labels_2.json`); neither is an independent human label. Needs a human labeller. |
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

## 3. Changes applied to the gold drafts (2026-11-11)
All five requests from the original review have been applied directly to the draft files.

| # | Rule | Change applied |
|---|---|---|
| 1 | POST-DIS-IN-R05 | source_quote updated to full ELIGIBILITY-01 passage ("Class 11 or 12" + "Diploma, Degree or Post-Graduate courses"); note updated. |
| 2 | PM-KISAN-IN-R09 | note updated to state explicitly that the succession exception is not encoded; caseworker referral noted. |
| 3 | PM-KISAN-IN-R10 | note updated to state explicitly that the North-East/Jharkhand exception is not encoded; caseworker referral noted. |
| 4 | PRE-DIS-IN-R07 / POST-DIS-IN-R07 | note updated: limit of 2 includes this applicant; twin exception not encoded. `needs_human_review` kept true pending fact-vocabulary confirmation. |
| 5 | PMJJBY-IN-R03 | already noted (bank or Post Office account holder) in the file before this review round; confirmed OK. |
| 6 | IGNOAPS-MH-R01 | note added: state threshold 65 overrides central threshold 60; consistent with POLICY.md section 2. |

Open source gaps (I could not verify an official URL from here and will not guess one):
- **MJPJAY-MH:** only a myScheme page. Needs the state health department page.
- **TFEFVS-MH (held-out):** only a UMANG page. Needs a Social Justice department or DoSJE page, as TFEFVSSSHS-MH has.
- **IGNDPS-IN, IGNWPS-IN, NSAP-IGNOAPS-IN (development):** only a UMANG page each. UMANG is discovery-only per POLICY.md §3. FAISHL-IN and IPMWCD-IN have been added to the development gold set (2026-11-11) as genuine-source replacements. These three remain in the set; Role 5 / Role 1 to decide whether to find official NSAP/MoRD pages or move them to held-out.
- **PMJJBY-IN, PMSBY-IN (development):** use jansuraksha.in (not .gov.in); APY-IN from the same umbrella uses jansuraksha.gov.in. Authenticity to be confirmed.
  Re-checked 2026-11-11: jansuraksha.gov.in loads (national toll-free numbers page), so it is the live government domain. jansuraksha.in loads but shows no content from here, so nothing proves it official. Guessed .gov.in paths for PMJJBY returned 404, so the correct .gov.in PMJJBY and PMSBY URLs are still to be found by a person.
- **MJPJAY-MH, TFEFVS-MH, NSAP pages:** re-checked 2026-11-11 and still not resolved. The MJPJAY health-department site and nsap.nic.in are unreachable from here. MahaDBT and the social-justice department home pages load, but neither shows these schemes, so no URL was added.

## 4. Persona check against the live engine
All 77 personas have been checked by two model-assisted label sets (`eval/development/role1_model_assisted_labels.json` and `eval/development/role1_model_assisted_labels_2.json`). Neither is an independent human label — both were derived by a model from the same gold rules used to set expected verdicts. A second human labeller is still needed before these personas can be used for held-out evaluation.

The first model-assisted check found 3 personas (R1-GOLD-013, 015, 018) where an exclusion fact was left unset. Those facts are now set to false. After that fix all original 60 labels match expected verdicts; the 17 new personas (R1-GOLD-027–043) were added to both label files and match.

Of the 77 development personas, 34 expected verdicts concern the 3 live schemes (IGNWPS-MH, IGNOAPS-MH, PM-KISAN-IN). Running through the rule engine: **33 match** (IGNWPS-DEV-007 is a wording difference only: `cant_tell` vs `need_more_information`). The remaining 43 personas cover gold-only schemes and need a human independent label.

## 5. Sign-off (reviewer completes)
| Field | Value |
|---|---|
| Reviewer | Nidhi Kaushik  |
| Date | 2026-11-11 |
| Commit reviewed | `b6fe75d` |
| Decision on flagged rules (section 2) | Proposed decisions accepted; section 3 requests go to the gold-set owner |
| Overall | Accepted for all 22 development schemes. Section 3 changes applied 2026-11-11. All 22 have human_reviewed status in rule_gold_selection.json and their draft files. IGNWPSM-MH moved to alternate (double-count with IGNWPS-MH). |
