# E3 approval request drafts (2026-11-13)

Status: drafts only. Nothing here has been sent, posted or submitted.

---

## Draft 1: Approve the E3 freeze pins

**To:** Role 5 (independent evaluation owner)
**Decision needed:** Confirm each proposed pin, or propose changes, before the E3 freeze is applied.

Hi Role 5, please review the E3 freeze proposal (docs/e3_freeze_proposal_2026-11-13.md).

Proposed pins:
- Model: `nvidia/nemotron-3.5-lightning:free` (extraction model, default in `scheme_rules.py`; not the chat model)
- Playbook: 1.0.0, content hash `a60303d5...1401`, file SHA-256 `cb1b56b2...45c1c`
- Case file: `data/schemes/rule_extraction_cases_dev.json`, SHA-256 `6bfac007...d0d0`
- Split: `split == "check"`, 6 cases: PMKISAN-GUIDELINES-2020-3, PMKISAN-GUIDELINES-2020-4.1(b)(iv), (v), (vi), IGNWPS-MH-ELIGIBILITY-01, IGNOAPS-MH-ELIGIBILITY-01

Stale manifest entries to change: `playbook.path` and `playbook.sha256` (point at a different file), and `model.chat_model` needs a separate extraction block. The `prompts` block has no E3 extraction entry.

Open decision: the extraction prompt (`EXTRACTION_SYSTEM_PROMPT`) has no version or hash today. Please choose the identifier (proposed `extraction.system.v1`) and the hash method.

Nothing is applied yet. The manifest is unchanged and no held-out data was touched.

---

## Draft 2: Approve budget and go-ahead for E3 paid runs

**To:** Project owner (budget approver)
**Decision needed:** An explicit budget figure and an explicit go-ahead for the E3 paid runs.

Hi, we are asking for approval to run the E3 comparison.

- Scope: 6 check cases, 3 repeats, before and after playbook 1.0.0 (2 arms).
- Calls: 6 x 3 x 2 = 36 model calls. If a 1.1.0 arm is added later, 54 in total.
- Cost: the per-call price is not in the repo, so the real cost is unknown. The free-key route may be the one used. We need to confirm the actual cost before running.
- Reference: the manifest records a recommended cap of $20 (`paid_budget_cap_usd`), approved by the project lead on 2026-11-12. Please confirm or set the figure.

Please reply with a budget figure and an explicit go-ahead. Runs have not started, and no model calls have been made.

---

## Draft 3: Review three inclusion-clause lesson drafts

**To:** Roy-developer (lesson approver)
**Decision needed:** Approve, reject or edit each of the three drafts in docs/lesson_drafts_inclusion_2026-11-13.md.

Hi Roy, please review the three draft inclusion-clause lessons (IGNWPS-MH-ELIGIBILITY-01, IGNOAPS-MH-ELIGIBILITY-01, IGNDPS-MH-ELIGIBILITY-01). All are `draft_pending_reviewer_approval`, and none is approved.

Please decide:
1. Approve, reject or edit each draft.
2. Use the same wording for the age-range pattern in Drafts 1 and 3.
3. Whether the BPL mapping rule (card-shown vs. names-on-list) becomes a separate lesson.
4. Whether IGNDPS may be an inclusion source. Its dev split is `null`, which `learn` refuses, so choose `learn` or `check`.
5. Whether the IGNOAPS threshold conflict (60 vs. 65) is handled outside the lesson.
6. Whether drafts take an empty lesson_id until approval.

Also note: the IGNDPS package `reasons.eligible` text is copied from IGNOAPS and needs a package fix. This is separate from the lesson decision.

---

Nothing above has been sent. Each request must be sent by its owner or by the project owner.
