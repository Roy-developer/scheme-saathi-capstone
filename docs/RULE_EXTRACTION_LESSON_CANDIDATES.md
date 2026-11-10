# Candidate lessons for the rule extractor

Playbook file: `data/schemes/rule_extractor_playbook.json` (now `2.0.0-draft`, not frozen).
Version 1.0.0 (frozen) is kept at `data/schemes/rule_extracted/playbook_frozen_2026-11-10.json`.
Only `approved` lessons reach the prompt; only a person may approve or reject.

## Round 1 (reviewed) - from 5 development schemes
| ID | Status | Lesson (short) |
|---|---|---|
| LESSON-001 | approved | One sentence with a person type and an age range: write a rule for the person type too |
| LESSON-002 | approved | Long lists: quote a short exact phrase per category |
| LESSON-003 | approved | Use a field only if the clause states that condition |
| LESSON-004 | rejected | Cut-off date / land records ("too specific to a single scheme") |

## Round 2 (pending) - from v2 baseline runs 1-3 on the 15 development schemes
Held-out errors were not read. "Runs" counts how often the error appeared in 3 runs.

| ID | Error seen (development) | Runs | Lesson (short) | My view |
|---|---|---|---|---|
| LESSON-005 | PMSBY, PMJJBY: rules discarded for a repeated rule_id (the passage ID was reused) | 3/3 | Give every rule its own rule_id | General, approve. Biggest single cause of low PMSBY/PMJJBY scores |
| LESSON-006 | Made-up field names discarded: `receives_other_pension`, `is_disabled`, `student_in_class_11_or_12` | 4 times | Copy field names exactly; leave a condition out if nothing fits | General, approve |
| LESSON-007 | PMSBY "18 to 70" written as `lt 70`; PMJJBY used cover-end age 55 instead of entry age 50 | 3/3 | Age range end is included; the maximum is the joining age | General, approve. Follows the owner's inclusive-age decision |
| LESSON-008 | IGNOAPS-MH, IGNDPSM-MH: pension clause mapped to `is_covered_under_other_social_security_scheme` | 3/3 | Pension condition -> `is_receiving_other_pension` | Narrow but seen in 2 schemes; your call |
| LESSON-009 | PRE-DIS, POST-DIS, IGNDPSM: `has_disability` missing when the clause gives a disability percentage | 3/3 | Write the yes/no condition and the number rule | Partly a gold convention (gold writes both); candidate to reject if you think the percentage rule is enough |
| LESSON-010 | NFBSM: the deceased breadwinner's age 18-59 put on the applicant's `age` | 3/3 | Use the field for the person the age describes | Overlaps approved LESSON-003, which did not fix this in v2; candidate to reject as a duplicate, or approve as more specific |

## Errors that are not lessons
- **Scorer limitation:** PRE-DIS wrote `family_members_receiving_scholarship lt 3`; gold is `lte 2`. For whole
  numbers these mean the same, but the scorer counts them as different. Fixing this is a scorer change, not a lesson.
- **Possible gold gap:** APY `consents_to_auto_debit` extracted in 2/3 runs. The passage says contributions are
  made by auto-debit; whether that is an eligibility condition is a gold decision.
- **Still failing after approved lessons:** IGNWPS `is_widow` (LESSON-001) and PM-KISAN long-paragraph quotes
  (LESSON-002) still fail in v2. Those lessons were not in the v2 baseline prompt, so this is expected;
  the playbook run will show whether they work.
