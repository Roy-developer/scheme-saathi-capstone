# Rule gold set (revised 2026-11-10, v0.2.0)

Machine-readable list: `data/schemes/rule_gold_selection.json`. 23 schemes: 15 development, 8 held-out.

## Why the split changed
The first E3 run (docs/EXPERIMENT_E3_RULE_EXTRACTION_2026-11-10.md) used 10 held-out schemes. Their errors
were then read to explain the result. The guide says cases looked at after a held-out run become development
cases, so those 10 were **relabelled development**, and a **fresh held-out set of 8** was built. The fresh 8
have not been run or inspected.

## Development (15) - lessons may be learned from these
| Family | Schemes |
|---|---|
| Widow pension | IGNWPS-IN, IGNWPS-MH |
| Old-age pension | NSAP-IGNOAPS-IN, IGNOAPS-MH |
| Farmer support | PM-KISAN-IN |
| Disability pension | IGNDPSM-MH, IGNDPS-IN |
| Disability self-employment / training | FADSE-MH, FASETDP-MH |
| Family benefit | NFBSM-MH |
| Contributory pension | APY-IN |
| Insurance | PMSBY-IN, PMJJBY-IN |
| Disability scholarship | PRE-DIS-IN, POST-DIS-IN |

All 15 are `human_reviewed`.

## Held-out (8) - measure only, never learn from
| Scheme | Rules | What it adds |
|---|---|---|
| AABYM-MH | 7 | Landless rural labourers; rural residence; other-insurance exclusion |
| PMKMDY-IN | 14 | Land size in hectares; social-security and high-status exclusions on the person |
| PRE-ST-IN | 7 | Scheduled Tribe status; recognised school |
| TCE-SC-IN | 6 | Scheduled Caste status; first-year student; sibling limit |
| PG-IGSSGC-IN | 7 | Only girl child; regular PG; distance-mode and professional-course exclusions |
| PMAY-U-IN | 5 | Urban residence; owns pucca house; earlier housing benefit |
| PSGS-DIP-IN | 7 | AICTE diploma admission; exam-gap years; failure/drop-out |
| TFEFVS-MH | 5 | VJNT category; income band; number of failures |

These 8 were marked `human_reviewed` on 2026-11-10 after the project owner reviewed them.

Chosen by structure and coverage (rules expressible as AND conditions, new benefit types), not by the
lesson errors seen in E3. Not used because they need OR or rural/urban conditional logic the schema cannot
express: NSIGSE, RASSNB, PMUY2, SBSSPS. Alternates: EPS, IPMWCD, FAISHL.

## Added in v0.3.0 (pending human review)
Hand-drafted from the passages, with every quote checked against the passage text. They use new fact names and leave out conditions the vocabulary cannot express (listed in each file's `unresolved`).

| Scheme | Split | Rules | Note |
|---|---|---|---|
| TMDVSO-MH | development | 1 | Only the category rule is encoded; age, education and fitness follow the Motor Vehicle Act with no figures. |
| WMCL-IN | development | 3 | SC/ST labourer's child, education after Class 10, exclusion for supervisory staff. |
| TFEFVSSSHS-MH | held-out | 4 | Same family as held-out TFEFVS-MH, so it goes to the same split. Role 5 must confirm. |

Totals: 26 schemes, 17 development and 9 held-out.

## Field vocabulary
26 fields were added to `FIELD_TYPES` in `src/rules/extraction.py` for the held-out schemes (14 more were
added earlier for the development schemes). The extractor prompt lists these fields, so **every earlier
score was measured with a different prompt**: re-run the baseline before comparing anything.

## Still open (listed in each file)
- Flagged for a person: PM-KISAN R09/R10, PRE-DIS/POST-DIS R07, PMJJBY R03, AABYM R04, PMKMDY R05,
  PRE-ST R02, PG-IGSSGC R04, TFEFVS R01/R02.
- Not encoded: PM-KISAN succession/transfer rules, PMJJBY cover end at 55, PRE-ST orphan waiver,
  PMKMDY "or PM-KISAN account", TFEFVS Government of India scholarship condition, institution/slot rules.
- No OR logic: every rule is ANDed.
