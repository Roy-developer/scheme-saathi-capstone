# Second Reviewer Plan — Role 1 Gold Set

**Prepared by:** Nidhi Kaushik (Role 1, Domain & Product Lead)  
**Date:** 2026-11-12  
**Branch:** `feature/nidhi-role1-review` (PR #25)

---

## What this is

Scheme Saathi is a multilingual welfare-scheme eligibility assistant (Group G05 capstone). Role 1 built the "gold set" — a curated list of 22 government schemes with machine-readable eligibility rules and boundary-condition test personas. These personas are used to measure whether the AI correctly determines eligibility.

To compute **Cohen's kappa** (inter-rater reliability), we need two people to independently label the same 79 personas *without seeing each other's answers or the expected verdicts first*. Nidhi has done the first label pass. You are the second.

---

## Your two tasks

### Task 1 — Independent labelling (primary, required for kappa)

**What:** Fill in a label sheet with your eligibility verdict for 79 personas across 22 schemes.  
**Why:** Kappa measures how much two independent labellers agree. If you read the gold rules or Nidhi's labels before labelling, the independence is broken and kappa becomes meaningless.

**Steps:**

1. **Read `docs/POLICY.md`** — especially sections 1 (eligibility model) and 2 (caseworker referral). This tells you what `eligible`, `not_eligible` and `need_more_information` mean.

2. **Read the official scheme sources** listed in `docs/SCHEME_LIST.md` (Official source URL column). These are the ground truth — `.gov.in` pages, official PDFs. Do not use UMANG or myScheme as your primary source.

3. **Do NOT open any of these files before you finish labelling:**
   - `eval/development/role1_label_sheet_nidhi.json` (Nidhi's labels)
   - `eval/development/role1_model_assisted_labels.json` (model labels)
   - `eval/development/role1_model_assisted_labels_2.json` (model labels)
   - `data/schemes/rule_gold_drafts/` (the gold rules — these are what's being tested)
   - Any `expected_by_scheme` fields in the persona files

4. **Work from the personas directly.** Each persona has a `description` and `typed_facts`. Those facts are everything the system knows about this person — treat absent facts as unknown (use `need_more_information` if a missing fact is required to decide).

   Persona files:
   - `eval/development/personas_v1.json` — 34 personas for the 3 live schemes (IGNWPS-MH, IGNOAPS-MH, PM-KISAN-IN)
   - `eval/development/gold_scheme_personas_v1.json` — 45 personas for the other 19 development gold schemes

5. **Create your own label file** — copy `eval/development/role1_label_sheet_nidhi.json` as a template, name it `eval/development/role1_label_sheet_<yourname>.json`, and fill in:
   - `"your_label (eligible / not_eligible / need_more_information)"` — one of the three values
   - `"your_reason (rule or source quote)"` — the rule or quote from the official source that drove your decision

6. Set the top-level `"labeller_id"` to your GitHub username and `"status"` to `"single_labeller_role1"`.

**Scope:** All 79 rows. Every scheme in the sheet has an official URL in `docs/SCHEME_LIST.md`.

---

### Task 2 — Native-speaker check on demo script (quick, ~30 min)

**What:** The demo script has Hindi and Marathi lines that need a native-speaker review.  
**File:** `docs/DEMO_SCRIPT.md` (or similar — check the docs/ folder)  
**Why:** The lines were drafted with translation tools and flagged for human verification before public demo.

**What to check:**
- Are the Hindi/Marathi sentences grammatically correct?
- Do they sound natural to a native speaker (not machine-translated)?
- Does the meaning match the English line next to it?

If a line is wrong, suggest a corrected version in your PR review comment or directly edit the file.

---

## Schemes and official sources (quick reference)

| Scheme | Level | Official URL |
|--------|-------|-------------|
| APY-IN | Central | https://jansuraksha.gov.in/Files/APY/ENGLISH/APY.pdf |
| BFFL-MH | State (MH) | https://mahadbt.maharashtra.gov.in/ |
| EACS-MH | State (MH) | https://mahabocw.in/ |
| FADSE-MH | State (MH) | https://depwd.maharashtra.gov.in/ |
| FAISHL-IN | Central | https://ksb.gov.in/interest-subsidy-on-home-loan.htm |
| FASETDP-MH | State (MH) | https://depwd.maharashtra.gov.in/ |
| IGNDPS-IN | Central | https://nsap.dord.gov.in/ |
| IGNDPSM-MH | State (MH) | https://sjsa.maharashtra.gov.in/ |
| IGNOAPS-MH | State (MH) | https://sjsa.maharashtra.gov.in/ |
| IGNWPS-IN | Central | https://nsap.dord.gov.in/ |
| IGNWPS-MH | State (MH) | https://sjsa.maharashtra.gov.in/ |
| IPMWCD-IN | Central | https://wcd.intern.nic.in/aboutproject |
| NFBSM-MH | State (MH) | https://sjsa.maharashtra.gov.in/ |
| NSAP-IGNOAPS-IN | Central | https://nsap.dord.gov.in/ |
| NSMNY-MH | State (MH) | https://nsmny.mahait.org/ |
| PM-KISAN-IN | Central | https://pmkisan.gov.in/ |
| PMJJBY-IN | Central | https://www.jansuraksha.in/pmjjbyScheme |
| PMSBY-IN | Central | https://www.jansuraksha.in/pmsbyScheme |
| POST-DIS-IN | Central | https://depwd.gov.in/en/scholarship-post-matric/ |
| PRE-DIS-IN | Central | https://depwd.gov.in/en/scholership-schemes-pre-matric/ |
| TMDVSO-MH | State (MH) | https://www.dosje.gov.in/ |
| WMCL-IN | Central | https://coffeeboard.gov.in/Schemes/MTF_LWM.pdf |

Full URLs are in `docs/SCHEME_LIST.md`.

---

## Key policy rules to know before labelling

From `docs/POLICY.md`:

- **State overrides central:** If a Maharashtra scheme sets age 65 for old-age pension, use 65 — not the central scheme's 60 (e.g. IGNOAPS-MH vs NSAP-IGNOAPS-IN are different schemes).
- **Missing facts = `need_more_information`:** If a required eligibility fact is absent from the persona's `typed_facts`, label `need_more_information` — do not assume.
- **Exclusion conditions:** Some rules are exclusions (`kind: exclusion`) — the scheme rejects applicants *if* the fact is true. Read carefully.
- **Caseworker referral:** Complex conditions the system can't express (OR logic, exceptions by region) are flagged as caseworker — don't try to evaluate them.

---

## After you finish

1. Commit your label file to a new branch and open a PR referencing PR #25.
2. Tag Nidhi Kaushik (`@NidhiShreeish`) to run the kappa calculation.
3. Add a comment on PR #25 with your `labeller_id` and the count of rows you labelled.

The kappa script lives at `eval/scripts/compute_kappa.py` (if it doesn't exist yet, Nidhi will write it once both label files are ready).

---

## Questions?

Open a GitHub issue or comment on PR #25. Tag `@NidhiShreeish`.
