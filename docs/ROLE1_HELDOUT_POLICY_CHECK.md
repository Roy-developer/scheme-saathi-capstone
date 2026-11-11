# Held-out schemes: fit against the policy note

**Status:** SIGNED OFF by Nidhi Kaushik (Role 1) on 2026-11-11 after her review. Policy: `docs/POLICY.md`. We only read these schemes. We do not edit, run or tune against them.
**Held-out list (9):** from `docs/RULE_GOLD_SET_SELECTION.md` (8 at `b6fe75d`, plus TFEFVSSSHS-MH added in v0.3.0 as a family member of TFEFVS-MH). The rule extractor's author also picked the first 8, so this check is the independent look the roles plan asks for.

Test: (a) every source is official, or has an official URL alongside discovery sources (policy section 3); (b) nothing in the scheme requires Saathi to do what policy section 1 forbids; (c) unresolved or conflicting items route to a caseworker (section 2).

| Scheme | Fit | Reason |
|---|---|---|
| AABYM-MH | Fits, with a note | Official source is a Nashik district page (`nashik.gov.in`), not the state department. The district page is government, but a state department URL would be better. |
| PMKMDY-IN | Fits | Official `pmkisan.gov.in` operational guidelines. The "or PM-KISAN account" alternative is not encoded, so a savings-account answer of "no" must go to a caseworker. |
| PRE-ST-IN | Fits | Official `scholarships.gov.in` guidelines. The orphan income waiver is not encoded, so those cases go to a caseworker. |
| TCE-SC-IN | Fits | Official `scholarships.gov.in` guidelines. Slot limits and merit ranking are selection rules, so Saathi must not promise a place. |
| PG-IGSSGC-IN | Fits | Official `scholarships.gov.in` guidelines. Institution-level exclusions are not encoded, so verification goes to a human. |
| PMAY-U-IN | Fits | Official `pmaymis.gov.in` manual. States may redefine the EWS limit, so the income category goes to a caseworker. |
| PSGS-DIP-IN | Fits | Official `scholarships.gov.in` guidelines. |
| TFEFVS-MH | Does not fit yet | The only source is UMANG, which the policy treats as discovery only. It needs an official Maharashtra department URL. The file also flags an unclear Government of India scholarship condition and an unusual Rs 1,00,000 lower income bound. |
| TFEFVSSSHS-MH | Fits, with a note | Official DoSJE page (`dosje.gov.in`) is the main source, with myScheme as discovery. Rules are hand-drafted and pending human review. "No limit of age or income" is not a rule. Added to this split because it is the same family as TFEFVS-MH; Role 5 must confirm. |

**Result:** 8 fit (3 with caveats), 1 does not fit until an official source is added.
**Sign-off:** reviewer Nidhi Kaushik (Role 1), date 2026-11-11. Decision: 8 of 9 fit (3 with caveats). TFEFVS-MH does not fit until an official Maharashtra department URL is added; Role 5 is told to treat it as pending.
