# Candidate Reflexion lessons: inclusion clauses (drafts for human review)

Status for every item below: `draft_pending_reviewer_approval`.
Nothing here is approved, frozen, exported or committed. The playbook file
`data/schemes/playbooks/1.0.0.json` is unchanged. Written by hand from the
source text; no model or OpenRouter call was made.

Lesson fields follow the existing exclusion lesson in the playbook
(`instruction`, `when_to_apply`, `tags`). `tags` is `inclusion_clause` for all
three, matching `topic_tags` on the dev cases. No `lesson_id` is assigned here;
approval assigns it.

Clause text is the `source_text` in each approved package. It is identical to
`official_eligibility_text` in the same package. `allowed_fact_ids` is derived
in code as the sorted set of rule fields (`gold_cases.py`, `scheme_rules.py`).

---

## Draft 1: IGNWPS-MH-ELIGIBILITY-01

- **Source clause id:** IGNWPS-MH-ELIGIBILITY-01 (dev split `check`)
- **Exact quote:** "A widow in age group of 40 to 79 years whose family falls under Below Poverty Line is eligible under this Scheme."
- **allowed_fact_ids:** age, bpl_card_shown, is_widow
- **status:** draft_pending_reviewer_approval
- **tags:** inclusion_clause

**instruction:** When a clause gives an age range written as "X to Y years", write two separate rules: an inclusive lower bound (gte X) and an inclusive upper bound (lte Y). Do not write the range as one rule. Map a "family falls under Below Poverty Line" condition to the BPL card fact (`bpl_card_shown`), not to a list-membership fact.

**when_to_apply:** Any inclusion clause that combines a category (for example, a widow), an age range, and a BPL condition on the family.

**Pattern to watch:** Two bounds from one range. A family-level BPL condition is a card-shown fact here.

**Check against approved package (`src/rules/packages/ignwps_mh.v1.json`):** Matches. AGE-MIN-01 is `age gte 40`. AGE-MAX-01 is `age lte 79`. WIDOW-01 is `is_widow eq true`. BPL-01 is `bpl_card_shown eq true`, with `if_not_met: need_more_information`. The lesson should not teach that `need_more_information` wording.

**Evidence note:** The package sets `age_boundaries_inclusive: true` and `bpl_confirmation: government_bpl_card_shown`. This is the one approved package that uses the card-shown BPL fact.

---

## Draft 2: IGNOAPS-MH-ELIGIBILITY-01

- **Source clause id:** IGNOAPS-MH-ELIGIBILITY-01 (dev split `check`)
- **Exact quote:** "Eligible elderly individuals aged 65 and above, whose names are on the Below Poverty Line (BPL) list, receive monthly financial assistance under the Indira Gandhi National Old Age Pension Scheme."
- **allowed_fact_ids:** age, name_on_bpl_list
- **status:** draft_pending_reviewer_approval
- **tags:** inclusion_clause

**instruction:** When a clause says "aged N and above", write one inclusive lower-bound rule (gte N) and no upper bound. When a clause says a person's "names are on the ... list", map the condition to the list-membership fact (`name_on_bpl_list`, eq true), not to a card-shown fact. The two BPL facts are different and must not be used interchangeably.

**when_to_apply:** Any inclusion clause that states an "and above" age threshold together with a condition that the person's name appears on a list.

**Pattern to watch:** "and above" is a single gte with no lte. "names are on the list" is a list-membership fact, which is not the card-shown fact used in Draft 1.

**Check against approved package (`src/rules/packages/ignoaps_mh.v1.json`):** Matches. AGE-MIN-01 is `age gte 65`. BPL-LIST-01 is `name_on_bpl_list eq true`. No upper-bound rule is present, which is correct.

**Evidence note:** The package's `unresolved_checks` lists a conflict: the central NSAP guideline uses 60, while the Maharashtra page uses 65. The approved package uses 65. The lesson must teach the mapping only and must not state that 65 is the correct threshold for every scheme.

---

## Draft 3: IGNDPS-MH-ELIGIBILITY-01

- **Source clause id:** IGNDPS-MH-ELIGIBILITY-01 (dev split `null`, not assigned)
- **Exact quote:** "A Disable person in the age group of 18 to 79 years is eligible under this Scheme."
- **allowed_fact_ids:** age, has_disability
- **status:** draft_pending_reviewer_approval
- **tags:** inclusion_clause

**instruction:** When a clause gives an age range written as "X to Y years", write two inclusive bounds: gte X and lte Y. When a clause states that a person must have a disability (or is a "disable person"), map it to a `has_disability` fact with eq true. Do not map it to an age or document fact.

**when_to_apply:** Any inclusion clause that combines a disability condition and an age range.

**Pattern to watch:** Two bounds from one range. A condition about the person's status maps to a status fact (`has_disability eq true`).

**Check against approved package (`src/rules/packages/igndps_mh.v1.json`):** Rules match the clause. AGE-GTE is `age gte 18`. AGE-LTE is `age lte 79`. HAS_DISABILITY-EQ is `has_disability eq true`. **Conflict to fix in the package, not in this draft:** the package's `reasons.eligible` text reads "aged 65 or above on the application date, and the applicant's name is on the BPL list". That text was copied from IGNOAPS and does not describe this scheme's rules.

**Evidence note:** The package has `reviewer_name` "project owner (mock portal; approval recorded from request, no named domain reviewer)". The dev file has `split: null`, and `learn` refuses null split. This draft must not be used as a learn source unless the reviewer assigns a split.

---

## Decisions Roy-developer must make

1. Approve, reject or edit each of the three drafts. None is approved.
2. Choose the lesson wording for the age-range pattern. Draft 1 and Draft 3 both use it, and the wording should be the same for both.
3. Decide whether the BPL mapping rule (family-BPL means card-shown; names-on-list means list-membership) should be a separate lesson, since Draft 1 and Draft 2 each cover one half of it.
4. Confirm that the IGNDPS clause may be used as an inclusion source. Its dev split is `null`, which `learn` refuses. Choose `learn` or `check` for it.
5. Ask the IGNDPS package owner to correct the `reasons.eligible` text, which is copied from IGNOAPS. This is a package fix, not a lesson decision.
6. Confirm the IGNOAPS threshold conflict (60 versus 65) is handled outside the lesson, because the lesson must not settle it.
7. Decide whether an empty or missing lesson_id is acceptable for drafts, or whether IDs are assigned at approval as for the existing exclusion lesson.
