# Role 1 gold set review (development schemes)

**Status:** SIGNED OFF by Nidhi Kaushik (Role 1) on 2026-11-11 after her review, with the section 2 decisions accepted.
**Reviewed material:** Priyanka's original 15 development gold schemes at commit `b6fe75d` (branch `b_passages_data`). TMDVSO-MH and WMCL-IN reviewed by Nidhi 2026-11-11 (hand-drafted). FAISHL-IN, IPMWCD-IN, EACS-MH, NSMNY-MH, BFFL-MH reviewed by Nidhi 2026-11-11 (promoted from alternates). Files: `data/schemes/rule_gold_drafts/`, `data/schemes/rule_gold_selection.json`, `docs/RULE_GOLD_SET_SELECTION.md`.
**Checked so far (automated):** for the original 15 development schemes at `b6fe75d`, every rule's `source_passage_id` exists and its `source_quote` appears verbatim in that passage (0 failures across 85 rules). TMDVSO-MH and WMCL-IN (4 rules) were hand-drafted and spot-checked. The 4 schemes added by Nidhi (FAISHL-IN, IPMWCD-IN, EACS-MH, NSMNY-MH, BFFL-MH) were not run through the automated grounding checker — they should be re-run before final evaluation. The 9 original held-out schemes were checked; one quote (PSGS-DIP-IN-R03) differs only in whitespace. IGNDPS-IN, IGNWPS-IN, NSAP-IGNOAPS-IN are now alternate and were not re-checked. Total development rules: ~92; held-out: ~62.
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
| 18 | FAISHL-IN | 2 | OK | Both rules from official ksb.gov.in. R02 re-anchored to FAISHL-IN-BENEFIT-01 (same KSB page): home-loan condition is implicit in the benefit description ("interest on loan taken from banks for construction of house"). Confirmed 2026-11-12 by Nidhi Kaushik. |
| 19 | IPMWCD-IN | 5 | OK | All 5 rules from official wcd.intern.nic.in. R04-R05 age range (21-40) confirmed on the same portal by Nidhi Kaushik 2026-11-12. |
| 20 | EACS-MH | 2 | OK | Construction worker (R01) and registered with MH BOCW Board (R02), both from official mahabocw.in. Child's class level and 75% attendance not encoded; caseworker. |
| 21 | NSMNY-MH | 3 | OK | Cultivable land ownership (R01), institutional landholder exclusion (R02), income-tax-payer exclusion (R03). All from official nsmny.mahait.org portal. Other exclusions (govt employees, pensioners, NRIs etc.) not encoded; caseworker. |
| 22 | BFFL-MH | 4 | OK | MH resident (R01), has Aadhaar (R02), 7/12 land record in own name (R03), institutional exclusion (R04). R03/R04 in Marathi — translations confirmed 2026-11-11. Area limits by region not encoded; caseworker. Source: mahadbt.maharashtra.gov.in. |

IGNWPSM-MH (6 rules) moved to **alternate** 2026-11-11: shares source URL with IGNWPS-MH (development, live). Both schemes describe the same MH widow pension; keeping both in gold would double-count.

Schemes 16 and 17 are hand-drafted with new fact names (quotes verified). They need the same line-by-line review as the others before they count as reviewed gold. TFEFVSSSHS-MH, the third addition, is in the held-out split and is covered in `docs/ROLE1_HELDOUT_POLICY_CHECK.md`.

## Targets and actual numbers
| Item | Asked | Actual | Status |
|---|---|---|---|
| Schemes listed with URL and collection date | 40-60 | 42 | Met. All 42 now have an official URL. |
| Gold schemes (development) | 15 | 19 (all 19 reviewed) | Met. All 19 human_reviewed. IGNWPSM-MH moved to alternate (double-count). IGNDPS-IN, IGNWPS-IN, NSAP-IGNOAPS-IN moved to alternate 2026-11-12 (UMANG-only URLs violate POLICY.md §3; MH state counterparts cover same populations in development). |
| Held-out schemes | set by Role 5 | 9 (reviewed) | 9 original. Policy check done; 1 does not fit yet. |
| Gold rules | not fixed | ~92 development, ~62 held-out | ~92 dev: original 85 + TMDVSO(1) + WMCL(3) + FAISHL(2) + IPMWCD(5) + EACS(2) + NSMNY(3) + BFFL(4) − 3 moved to alternate (13). ~62 held-out: original 62 (IGNDPS, IGNWPS, NSAP-IGNOAPS now alternate). Grounding check run on original 15 only; new additions need re-run. |
| Personas | 60 | 82 (34 dev-live + 39 gold-only dev + 9 alternate) | Met. 34 on live schemes run (33 match); 39 typed_facts-only gold-only (not run); 9 alternate (not scored). |
| Independent labels on personas | 2 labellers | 1 (partial) | **Not met.** Labelled by Nidhi Kaushik, with model assistance and review, on `role1_label_sheet_nidhi.json` (73 of 73 development personas). Independent second labeller pending, so no Cohen's kappa yet. Model-assisted checks (`role1_model_assisted_labels.json` for 82 personas and `role1_model_assisted_labels_2.json` for 82) are not independent human labels. |
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
- **FAISHL-IN R02:** Resolved 2026-11-12 — re-anchored to FAISHL-IN-BENEFIT-01 from official ksb.gov.in. Home-loan condition is implicit in the benefit description ("interest on loan taken from banks for construction of house"); source flag cleared.
- **IPMWCD-IN R04-R05:** Resolved 2026-11-12 — wcd.intern.nic.in confirmed as official WCD internship portal by Nidhi Kaushik. Age range 21-40 is on the same portal as R01-R03; source flag cleared.
- **IGNDPS-IN, IGNWPS-IN, NSAP-IGNOAPS-IN:** moved to alternate 2026-11-12. UMANG-only URLs violate POLICY.md §3. Their MH state counterparts (IGNDPSM-MH, IGNWPS-MH, IGNOAPS-MH) remain in development and cover the same populations. These three can be restored to development once official NSAP/MoRD URLs are confirmed.
- **PMJJBY-IN, PMSBY-IN:** `jansuraksha.in` confirmed as official Jan Suraksha portal by Nidhi Kaushik 2026-11-12. No action needed.
  Confirmed 2026-11-12 by Nidhi Kaushik: jansuraksha.in is the official Jan Suraksha portal. PMJJBY-IN and PMSBY-IN sources are valid.
- **MJPJAY-MH, TFEFVS-MH, NSAP pages:** re-checked 2026-11-11 and still not resolved. The MJPJAY health-department site and nsap.nic.in are unreachable from here. MahaDBT and the social-justice department home pages load, but neither shows these schemes, so no URL was added.
- **FASETDP-MH age limit (deferred):** the third-party site jsrr.in reports an age range of 14 to 80. The official passages captured for the scheme have no age rule; the myScheme page's eligibility point 3 was not captured. No age rule was added. Persona R1-GOLD-022 is labelled need_more_information because age is not in its facts. Once point 3 is checked on the official page and confirms an age range, add the passage, an age rule and a persona age.

- **PRE-DIS-IN income limit (source not official):** the gold rule uses family income <= Rs 2,50,000. A private (non-official) page gives Rs 2,00,000. Decision 2026-11-12 (Nidhi Kaushik): keep Rs 2,50,000. No official link is available, so this is recorded as unverified against an official page. The personas near the limit (R1-GOLD-016, income 250,001) are labelled not eligible under either figure, so the labels do not depend on it. Re-check on the official page if one becomes available.

## 4. Persona check against the live engine
The 82 personas have two model-assisted label sets: `eval/development/role1_model_assisted_labels.json` and `eval/development/role1_model_assisted_labels_2.json`. Both were produced by AI sessions. They are consistency checks, not independent human labels, so no kappa can be computed from them yet.
Persona files (2026-11-12): `eval/development/personas_v1.json` holds the 34 personas for the three live schemes, so Role 5's harness runs cleanly. `eval/development/gold_scheme_personas_v1.json` holds the 39 gold-only personas. `eval/alternates/personas_alternate_v1.json` holds the 9 alternate personas (3 IGNWPSM-MH + 6 for IGNDPS-IN, IGNWPS-IN, NSAP-IGNOAPS-IN), which are not scored.

The first model-assisted check found 3 personas (R1-GOLD-013, 015, 018) where an exclusion fact was left unset. Those facts are now set to false. After that fix all original 60 labels match expected verdicts; the 17 new personas (R1-GOLD-027–043) were added to both label files and match.

Of the 77 development personas, 34 expected verdicts concern the 3 live schemes (IGNWPS-MH, IGNOAPS-MH, PM-KISAN-IN). Running through the rule engine: **33 match** (IGNWPS-DEV-007 is a wording difference only: `cant_tell` vs `need_more_information`). The remaining 43 personas cover gold-only schemes and need a human independent label.

## 5. Label decisions (Nidhi Kaushik, 2026-11-12)
Judgment calls made while labelling `role1_label_sheet_nidhi.json`:
- **IGNOAPS-MH age:** the Maharashtra threshold of 65 overrides the central 60 (POLICY.md section 2). R1-IGNOAPS-003 (age 60) and IGNOAPS-DEV-001 (age 64) are labelled not eligible. The central-only scheme NSAP-IGNOAPS-IN keeps 60.
- **Two-per-family limit (PRE-DIS, POST-DIS):** the limit of 2 includes the applicant, so a family where 3 members already receive the scholarship is not eligible (R1-GOLD-020, R1-GOLD-026).
- **FAISHL-IN home loan:** a home loan is required, as the official eligibility text states. R1-GOLD-028 (no home loan) is not eligible. The Rs 1,00,000 cap applies to the loan amount considered for subsidy, not to eligibility.

## 6. Sign-off (reviewer completes)
| Field | Value |
|---|---|
| Reviewer | Nidhi Kaushik |
| Date | 2026-11-12 |
| Commit reviewed | `9feef4e` |
| Decision on flagged rules (section 2) | Proposed decisions accepted; section 3 requests go to the gold-set owner |
| Overall | Accepted for all 19 development schemes. All 19 human_reviewed in rule_gold_selection.json and their draft files. IGNWPSM-MH moved to alternate (double-count). IGNDPS-IN, IGNWPS-IN, NSAP-IGNOAPS-IN moved to alternate 2026-11-12 (UMANG-only policy violation resolved). |
