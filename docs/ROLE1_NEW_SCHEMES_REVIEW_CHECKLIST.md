# Line-by-line review checklist: 8 pending development schemes

Generated 2026-11-11 from the draft rules and passage files. For each rule, read the source quote and the passage, decide whether the rule says what the source says, and tick the box. `Exact quote` is an automatic check only. It does not mean the rule is right.

Meaning of the columns: **Rule** is what the engine would check. Exclusion rules apply when the fact is true. When all boxes for a scheme are ticked, change its `review_status` to `human_reviewed` in its draft file and in `rule_gold_selection.json`.

## TMDVSO-MH (tmdvso.json, 1 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | TMDVSO-MH-R01 | eligibility | `belongs_to_vjnt_obc_or_sbc_category eq True` | yes | Eligible DNT/SBC/OBC community members | New fact. Official department page; the myScheme page (TMDVSO-MH-ELIGIBILITY-01) says the same. |

Not encoded (caseworker):
- Age, education and fitness are "as per the Motor Vehicle Act" with no figures on the page, so they are not encoded; route to a caseworker.
- Domicile of Maharashtra appears only in the documents list, not as an eligibility sentence.

## WMCL-IN (wmcl.json, 3 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | WMCL-IN-R01 | eligibility | `is_child_of_sc_st_coffee_labourer eq True` | yes | Children of SC / ST labourers working in coffee plantations and Licensed Coffee Curing Works | New composite fact (SC/ST child of a coffee plantation or curing-works labourer). |
| [ ] | WMCL-IN-R02 | eligibility | `is_pursuing_education_after_class_10 eq True` | yes | pursuing higher education after X Class | New fact. Stipend, incentive and financial-assistance tiers have different education conditions that are not encoded. |
| [ ] | WMCL-IN-R03 | exclusion | `is_child_of_estate_clerk_driver_supervisor_or_manager eq True` | yes | Children of Clerks, Drivers, Supervisors and Managers of Estate / Curing works are not entitled for these benefits. | Exclusion: applies when true. |

Not encoded (caseworker):
- Only the first two surviving children qualify (twins and multiple births allowed); not encoded.
- Release of money is subject to availability of funds (WMCL-IN-BENEFIT-02); not an eligibility rule.
- Per-benefit conditions (educational stipend, incentive award, financial assistance) differ; only common conditions are encoded.

## FAISHL-IN (faishl.json, 2 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | FAISHL-IN-R01 | eligibility | `is_war_bereaved_or_disabled_or_casualty eq True` | yes | This facility is applicable for War Bereaved, War Disabled and Attributable Peacetime casualties only. |  |
| [ ] | FAISHL-IN-R02 | eligibility | `has_home_loan eq True` | yes | The applicant must have taken a home loan from a bank, government/public sector undertaking, LIC, GIC, or HUDCO. |  |

Not encoded (caseworker):
- The Rs 1,00,000 loan limit caps the subsidy; it is a benefit limit, not an eligibility rule.

## IPMWCD-IN (ipmwcd.json, 5 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | IPMWCD-IN-R01 | eligibility | `is_woman eq True` | yes | The women students, scholars, social activists and teachers |  |
| [ ] | IPMWCD-IN-R02 | eligibility | `is_student_scholar_activist_or_teacher eq True` | yes | The women students, scholars, social activists and teachers |  |
| [ ] | IPMWCD-IN-R03 | eligibility | `is_from_rural_or_non_tier1_area eq True` | yes | from non-tier-I cities and rural parts of India |  |
| [ ] | IPMWCD-IN-R04 | eligibility | `age gte 21` | yes | The age of the applicant should be between 21 to 40 years. |  |
| [ ] | IPMWCD-IN-R05 | eligibility | `age lte 40` | yes | The age of the applicant should be between 21 to 40 years. |  |

## EACS-MH (eacs1t7a8t10.json, 2 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | EACS-MH-R01 | eligibility | `is_construction_worker eq True` | yes | The worker should be engaged in a building or other construction work. |  |
| [ ] | EACS-MH-R02 | eligibility | `is_registered_construction_worker eq True` | yes | The worker should be registered under the Maharashtra Building & Other Construction Workers Welfare Board. |  |

Not encoded (caseworker):
- The child's school class (1-7 or 8-10) and 75% attendance conditions are not encoded.

## NSMNY-MH (namo_shetkari_mahasanman_nidhi_yojana.json, 3 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | NSMNY-MH-R01 | eligibility | `owns_cultivable_land eq True` | yes | Cultivable land holding farmers families |  |
| [ ] | NSMNY-MH-R02 | exclusion | `is_institutional_landholder eq True` | yes | All Institutional Land holders |  |
| [ ] | NSMNY-MH-R03 | exclusion | `is_income_tax_payer eq True` | yes | All Persons who paid Income Tax in last assessment year. |  |

Not encoded (caseworker):
- The scheme follows PM-KISAN eligibility, including later central changes (NSMNY-MH-ELIGIBILITY-02, Marathi). Other exclusions (office holders, government employees, pensioners, professionals, NRIs) are not encoded here.

## IGNWPSM-MH (ignwpsm.json, 6 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | IGNWPSM-MH-R01 | eligibility | `age gte 40` | yes | A widow in age group of 40 to 79 years whose family falls under Below Poverty Line is eligible under this Scheme. |  |
| [ ] | IGNWPSM-MH-R02 | eligibility | `age lte 79` | yes | A widow in age group of 40 to 79 years whose family falls under Below Poverty Line is eligible under this Scheme. |  |
| [ ] | IGNWPSM-MH-R03 | eligibility | `is_below_poverty_line eq True` | yes | A widow in age group of 40 to 79 years whose family falls under Below Poverty Line is eligible under this Scheme. |  |
| [ ] | IGNWPSM-MH-R04 | eligibility | `is_resident_of_state eq True` | yes | The applicant should be a resident of Maharashtra. |  |
| [ ] | IGNWPSM-MH-R05 | eligibility | `is_widow eq True` | yes | The applicant should be a widow. |  |
| [ ] | IGNWPSM-MH-R06 | eligibility | `is_receiving_other_pension eq False` | yes | The applicant should not be receiving pension benefits under any social security scheme. |  |

## BFFL-MH (bhausaheb_fundkar.json, 4 rules, status pending_human_review)

| Done | Rule | Kind | Check | Exact quote | Source quote | Note |
|---|---|---|---|---|---|---|
| [ ] | BFFL-MH-R01 | eligibility | `is_resident_of_state eq True` | yes | The beneficiary should be a permanent resident of Maharashtra State |  |
| [ ] | BFFL-MH-R02 | eligibility | `has_aadhaar eq True` | yes | Farmer should have Aadhaar Card. |  |
| [ ] | BFFL-MH-R03 | eligibility | `owns_land_in_own_name eq True` | yes | शेतकऱ्यास स्वतःच्या नावावर ७/१२ असणे आवश्यक आहे. | Passage is in Marathi; joint-owner exception needs review. |
| [ ] | BFFL-MH-R04 | exclusion | `is_institutional_landholder eq True` | yes | संस्थात्मक लाभार्थांना देय नाही. | Passage is in Marathi. |

Not encoded (caseworker):
- Minimum and maximum plantation area differ by region (Konkan 0.10-10 ha, rest of Maharashtra 0.20-6 ha); needs a region fact.
- Joint owners need the other owners' consent; a tenant's name on 7/12 needs the tenant's consent.
