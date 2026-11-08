# Rule-extraction Reflexion: code walkthrough

This guide explains the current development-only implementation in
`src\rule_extraction_reflexion`. Read it beside the code, one section at a time.
Function names are used instead of line numbers so the guide stays useful when
lines move.

**What is implemented:** extraction, comparison, pending lessons with evidence,
an explicit review permission check, approved-lesson retrieval, frozen playbooks,
and basic evaluation over caller-supplied cases.

**What is not implemented:** an authenticated review screen/API, automatic
rule activation, or full capstone E1-E4 experiments. This guide does not claim that
Phase 5 as a whole is complete.

**New to Reflexion?** Read "Start here" below first: it explains the whole loop
end to end with the commands and the first real experiment. Sections 1-16 then
explain the code one function at a time.

**Bringing a new scheme into the app?** Go to "From official PDF to live app,
end to end". It covers every step, and shows going live both by hand and with
the `onboard` command.

## Start here: the Reflexion loop end to end (team guide)

### Words used in this guide

| Word | Meaning | Example |
|---|---|---|
| Clause | One piece of official scheme text | "All Persons who paid Income Tax in last assessment year." |
| Fact | One thing the app asks about a person or family, defined in `src/rules/fact_registry.json` | `income_tax_paid_last_assessment_year` (yes/no), `age` (number, years) |
| Rule | One condition on one fact, written so it describes who **qualifies** | `income_tax_paid_last_assessment_year eq false` |
| Operator | How the fact is compared: `eq` equals, `gte` at least, `lte` at most | `age gte 40`, `age lte 79` |
| Answer key | The approved rules in a rule package; the model never sees them while extracting | `src/rules/packages/pmkisan_in.v1.json` |
| Lesson | A short instruction the model writes after a mistake; a person must approve it | "When a clause says a group is not eligible, set that fact to false" |
| Playbook | A sealed, numbered set of approved lessons | `1.0.0` |
| Topic tag | A label on a clause; lessons are found again by matching tags | `exclusion_clause`, `inclusion_clause` |
| Split | Whether a clause may be learned from (`learn`) or is only measured (`check`) | set per clause in the cases file |

### What it is, in one picture

Reflexion helps a model **read official scheme text into rules** better over
time. It never decides anyone's eligibility and never changes an approved rule
package; people approve everything.

```text
 approved clause ──► model writes rules ──► compare with the APPROVED rules
                                                  │
                         same ◄───────────────────┴──────────► different
                         (nothing to learn)                     │
                                                                ▼
                                          model writes a LESSON (pending)
                                                                │
                                          a team member approves / rejects
                                                                │
                                          approved lessons are FROZEN into a
                                          numbered PLAYBOOK (e.g. 1.0.0)
                                                                │
 next time: the model reads a clause WITH the matching lessons ◄┘
```

A **lesson** is a short instruction such as "When a clause says a group is not
eligible, set that fact to false, not true". A **playbook** is a sealed,
versioned set of approved lessons. Lessons are matched to clauses by **topic
tags** (for example `exclusion_clause`).

### Who does what

| Role | Does |
|---|---|
| Rule reviewer (human) | Approves the scheme's rule package (existing `review-scheme-evidence` process). Those approved rules are the answer key. |
| Any team member listed as a reviewer | Approves or rejects each proposed lesson. A model can never approve its own lesson. |
| Model (`openai/gpt-4o-mini` via OpenRouter, project key) | Writes rules from clause text; writes lesson text when it was wrong. |
| Code (`src/rule_extraction_reflexion`) | Checks the model's rules, compares them with the answer key, adds tags to lessons, stores and seals everything. |

### The files involved

| File | What it holds | In git? |
|---|---|---|
| `src/rules/packages/*.json` | Approved rules with each clause's exact text (the answer key) | Yes |
| `src/rules/fact_registry.json` | The facts a rule may use, with types and units | Yes |
| `data/schemes/rule_extraction_cases_dev.json` | Which clauses Reflexion uses, their topic tags, their split (`learn`/`check`), list-heading context, and who may review | Yes |
| `src/rule_extraction_reflexion/scheme_rules.py` | The on-demand commands | Yes |
| `src/rule_extraction_reflexion/onboarding.py` | The logic behind `onboard`; the app never imports it | Yes |
| `src/rule_extraction_reflexion/` | The package the commands call | Yes |
| `data/runtime/reflexion_lessons.sqlite3` | Each person's own lessons, review decisions and frozen playbooks. Created automatically | No (git-ignored) |
| `data/schemes/playbooks/*.json` | Frozen playbooks shared with the team. Copied into the local database the first time they are used | Yes |
| `data/runtime/reflexion_reports/*.json` | One report per `evaluate` run | No (git-ignored) |
| `data/schemes/rule_extraction_sources/*.json` | Official text of a **new** scheme (no approved rules yet), for `extract`; its `onboarding` block holds the search passages | Yes |
| `data/schemes/reflexion_packages/*.json` | Approved packages waiting to go into the app; `onboard` moves them. Empty when every scheme is live | Yes |
| `data/runtime/reflexion_drafts/*.json` | Model drafts from `extract`; never policy | No (git-ignored) |

How the files work together:

```text
 src/rules/packages/*.json            data/schemes/rule_extraction_cases_dev.json
 (clause text + approved rules)       (which clauses, tags, split, headings, reviewers)
              \                                   /
               \                                 /
                v                               v
            src/rule_extraction_reflexion/scheme_rules.py  ->  build_cases()  ->  one case per clause
                                                 |
               +---------------------------------+------------------------------+
               |                                                                |
     evaluate -> evaluate_cases()                         learn -> run_reflexion_case()
     (measure; nothing stored)                            (extract -> compare -> lesson)
               |                                                                |
               v                                                                v
 data/runtime/reflexion_reports/*.json          data/runtime/reflexion_lessons.sqlite3
                                                  pending lessons -> reviews -> playbook
                                                                |
                         freeze -> playbook 1.0.0 --------------+
                                                                |
             evaluate --playbook 1.0.0: matching lessons are added to the model's prompt
```

### The steps, end to end

All commands run from the repository root in PowerShell and start with
`.\.venv\Scripts\python.exe -m src.rule_extraction_reflexion.scheme_rules`. Paid commands print their
cost and send nothing until `--yes` is added.

| # | Step | Command | Paid? |
|---|---|---|---|
| 1 | **List the clauses.** One entry per approved clause in the cases file, with `topic_tags`. If the clause is an item in a list (such as "All Institutional Land holders."), set its `context` to the names of the headings it sits under; the heading text itself is stored once in the file's `contexts` block, copied word for word from the source, so the model sees what a reader sees. | edit `rule_extraction_cases_dev.json` | Free |
| 2 | **Measure the starting point (baseline).** The model reads every clause, no lessons. Nothing is learned or stored. Run several times because answers vary. | `evaluate --runs 3 --yes` | Yes |
| 3 | **Split the clauses.** Mark each clause `learn` (lessons may come from it) or `check` (only measured, never learned from). Choose by hand, using the baseline, so both groups contain the kind of mistake being studied. Decide before step 4. | edit `"split"` in the cases file | Free |
| 4 | **Learn.** For each `learn` clause the model writes rules; if they differ from the answer key it writes one lesson, saved as pending. | `learn --yes` | Yes |
| 5 | **Review.** Read each pending lesson. Approve a clear, general one; reject vague ones and duplicates, with a reason. | `lessons`, then `review <id> --approve` or `--reject --reviewer <github-login from authorized_reviewers> --reason "..."` | Free |
| 6 | **Freeze and share.** Seal the approved lessons into a numbered playbook, then export it to a file and commit that file, so the team uses the same lessons. A version can be frozen only once; changes need a new version. To add to an existing playbook, use `--base`, or the new version keeps only the lessons approved in your own database. | `freeze 1.0.0`, then `export-playbook 1.0.0`, then commit `data/schemes/playbooks/1.0.0.json`. Later: `freeze 1.1.0 --base 1.0.0` | Free |
| 7 | **Measure again on the check clauses**, with the playbook, and compare with their baseline from step 2. Because these clauses were never learned from, an improvement shows the lesson transfers. | `evaluate --split check --playbook 1.0.0 --runs 3 --yes` | Yes |
| 8 | **Record the result** here (section "First experiment" below shows the format). | edit this guide | Free |

Rules that keep the test honest:

- **Never change the answer key to create mistakes.** A wrong answer key marks
  correct model answers as wrong and teaches false lessons. Mistakes must come
  from the model.
- **Measuring does not use a clause up; learning does.** `evaluate` can be
  re-run on any clause. Never move a clause from `learn` to `check` after
  `learn` has run on it.
- **Only listed reviewers** (`authorized_reviewers`, GitHub logins) can
  approve or reject, and each lesson can be reviewed once.
- **Lessons cannot be edited.** If a lesson is unclear, reject it and improve
  how lessons are written (the reflection prompt), then run `learn` again.

> **Do not use `scripts\reflexion_demo_real.py` for real runs.** It builds the
> prompts itself instead of calling the package, so it skips the package's
> checks on the model's rules and it hid the tag crash (P3, section 15). Use
> `src/rule_extraction_reflexion/scheme_rules.py`, whose commands call the package functions directly.

### What the model is compared on

Only what can be read from the clause: the fact, the comparison (`eq`, `gte`,
`lte`), the value, the unit and the clause. Rules are paired by meaning
(clause + fact + comparison), not by rule ID, because the model never sees the
approved IDs. Reviewer policy that the text does not state (such as IGNWPS's
"no BPL card shown means ask for the card") is not compared (reviewer decision,
section 15). Section 8 has a before/after picture of this.

Who sees what:

| Information | Extraction call (model) | Reflection call (model, only after a mistake) | Code |
|---|---|---|---|
| Clause text (plus its headings) | Yes | Yes | Yes |
| Allowed facts: ID and type (yes/no, number with unit, choice codes), never the meaning text | Yes | No | Yes |
| Approved lessons matching the clause's tags | Yes | No | Yes |
| Approved rules (answer key) and their IDs | **No** | Yes, to explain the mistake | Yes |
| The model's own rules and the differences | No | Yes | Yes |

### First experiment (2026-11-07)

Nine approved clauses: PM-KISAN's landholding definition (section 3) and its
seven exclusions (section 4.1), and IGNWPS's single eligibility clause.

**1. Baseline, clause line only: 6/27 exact.** Both "who qualifies" clauses were
right in every run. Six PM-KISAN exclusions came back as `eq true` in all 18
runs: for "All Institutional Land holders." the model wrote
`institutional_landholder eq true`, while the approved rule is `eq false`
(rules describe who **qualifies**). The seventh, the pension clause, was
rejected in all 3 runs because the model's answer was not a valid yes/no rule.

**2. Why:** each exclusion was shown without its heading. In the official PDF
(page 2) the items sit under "4.1 The following categories of beneficiaries of
higher economic status shall not be eligible for benefit under the scheme:"
and, for 4.1(b), "Farmer families in which one or more of its members belong to
following categories :". Both headings were added as `context` in the cases
file.

**3. Baseline with headings: 8/27 exact.** Seeing "shall not be eligible"
barely helped, so this is a genuine misreading, not missing text. That made it
a fair mistake to learn from.

**4. Split (by hand, after step 3):**

| Split | Clauses |
|---|---|
| learn (4) | 4.1(a) institutional land, 4.1(b)(i)-(ii) office holders, 4.1(b)(iii) government employees, 4.1(c) NRI |
| check (5) | 4.1(b)(iv) pension, 4.1(b)(v) income tax, 4.1(b)(vi) professionals, PM-KISAN section 3, IGNWPS |

**5. First lessons were too vague.** All four read like "Ensure that the
eligibility criteria ... is accurately reflected", some naming one group (NRIs,
government employees). All four were rejected. The reflection prompt was then
changed (`REFLECTION_SYSTEM_PROMPT` in `reflexion.py`) to state that rules
describe who qualifies, to ask for the mistake and the correct way to write it,
to describe when to apply it by wording rather than by scheme, and to name no
scheme or group. Its style example is about ranges, so it does not give away
the exclusion answer.

**6. Second lessons were clear and general.** One was approved (reviewer
`Roy-developer`) and three rejected as duplicates:

> "When a clause specifies categories of individuals who are ineligible, ensure
> the rule reflects that these individuals are not qualified by setting the
> value to false, rather than true." (tag `exclusion_clause`)

**7. Frozen as playbook 1.0.0** (1 lesson, hash `a60303d5...`).

**8. Check clauses, before and after the lesson (3 runs each):**

| Check clause | Without playbook | With playbook 1.0.0 |
|---|---|---|
| PM-KISAN section 3 (who qualifies) | 3/3 | 3/3 |
| IGNWPS (who qualifies) | 3/3 | 3/3 |
| 4.1(b)(vi) professionals | 2/3 | 3/3 |
| 4.1(b)(iv) pension | 0/3 (rejected) | 1/3 |
| 4.1(b)(v) income tax | 0/3 | 0/3 |
| **Total** | **8/15** | **10/15** |

At this point the gain was small. Income tax was still wrong, and pension was
mostly rejected.

**9. Why pension was rejected.** The script was changed to print the model's
full answer for rejections. The model had written
`pension_at_least_10000_excluding_stated_grades gte 10000` with unit `Rs`: a
number rule for a yes/no fact. It had been given only fact names, not their
types. All 13 fact definitions were then approved by the reviewer
(`Roy-developer`), and the model is now told each fact's type (yes/no, number
with unit), never its meaning text.

**10. Check clauses again, with fact types (3 runs each):**

| Check clause | Before types (with playbook) | Types, no playbook | Types + playbook 1.0.0 |
|---|---|---|---|
| PM-KISAN section 3 (who qualifies) | 3/3 | 3/3 | 3/3 |
| IGNWPS (who qualifies) | 3/3 | 3/3 | 3/3 |
| 4.1(b)(vi) professionals | 3/3 | 3/3 | 3/3 |
| 4.1(b)(iv) pension | 1/3 (rest rejected) | 0/3 (`eq true`, no longer rejected) | **3/3** |
| 4.1(b)(v) income tax | 0/3 | 0/3 | **3/3** |
| **Total** | **10/15** | **9/15** | **15/15** |

**What this shows:** two different fixes did two different jobs. Showing fact
types fixed the **shape** of the answer (pension stopped being rejected). The
one reviewed lesson fixed the **meaning** (excluded groups written as `false`),
taking the check clauses from **9/15 to 15/15**, on clauses it was never
learned from, without breaking the "who qualifies" clauses.
**Limits:** 3 runs per clause, two schemes, one model (`gpt-4o-mini`). Total
cost of all real calls that day: about 2 US cents.

### From official PDF to live app, end to end (worked example: IGNOAPS)

This is the full process for a scheme with **no approved rules yet**: get the
official text, let the model draft the rules, review and measure them, then
put the scheme in the app. Steps 0 to 12 happen outside the app. Steps 13 to 18
take it live, and step 14 can be done by hand or with one command.

IGNOAPS (Indira Gandhi National Old Age Pension Scheme, Maharashtra) went
through this on 2026-11-07/08 and is the first scheme whose rules a model
drafted. Its official source was a government web page. A PDF follows the same
steps; PM-KISAN's list headings came from its official PDF.

Run everything from the repository root, after activating the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

**Memory aid: Find → Fit → Draft → Check → Approve → Measure → Go live.**

| Phase | Steps | In one line |
|---|---|---|
| **Find** | 0 choose, 1 official text, 2 source file | Pick the scheme and copy its official eligibility words exactly |
| **Fit** | 3 facts match?, 3b new fact | Every condition needs a fact that means exactly the same thing |
| **Draft** | 4 extract, 5 reviewer decisions | The model writes the rules; the reviewer adds policy the text does not state |
| **Check** | 6 evidence review, 7 second review, 7b conflicts | Two independent reviews against the sources; the reviewer resolves conflicts |
| **Approve** | 8 sign-off, 9 rule package | A person signs; the package waits outside the app, hash recorded |
| **Measure** | 10 cases file, 11 evaluate, 12 record | The scheme joins learn/check, is measured, and the result is written down |
| **Go live** | 13 app approval, 14 put in the app, 15 checklist and form, 16 walk through, 17 search re-check, 18 reviews and commit | A person approves it for the app; the files go in; people check the result |

```text
 download PDF / open official page
        │
 0 choose scheme ─► 1 official text ─► 2 source file ─► 3 facts fit? ──no──► 3b new fact
                                                            │ yes              (reviewed)
                                                            ▼                     │
                       4 extract (model draft, with playbook) ◄───────────────────┘
                                                            │
                       5 reviewer decisions (policy the text does not state)
                                                            │
                       6 evidence review ─► 7 independent second review ─► conflicts?
                                                            │                 (reviewer decides)
                       8 human sign-off ◄───────────────────┘
                                                            │
                       9 rule package in data/schemes/reflexion_packages/ + hash
                                                            │
                      10 add to cases file ─► 11 evaluate ─► 12 record
                                                            │
                      13 App approval line in the review document
                                                            │
                      14 put it in the app:   by hand   OR   onboard --yes
                                                            │
                      15 checklist and form ─► 16 walk through ─► 17 search re-check ─► 18 reviews, commit
```

| # | Step | How | IGNOAPS (what actually happened) | Cost |
|---|---|---|---|---|
| 0 | **Choose the scheme** | Pick from `docs/SCHEME_CATALOGUE_AND_DELIVERY_PLAN.md` ("Proposed 15-scheme gold set"). Prefer one whose conditions use facts already in `src/rules/fact_registry.json`. | CEN-002 IGNOAPS: expected facts age and BPL, both apparently in the registry | Free |
| 1 | **Download the official source and copy its text word for word** | Download the PDF from the scheme's government site, or open its official page. Note the URL, date and page or section. Check it is official: a government domain, a letter or notification number and date, and no chatbot text or word-processor metadata. Copy the exact eligibility wording, including any heading a list item sits under. The project has no PDF reader, so copy from a PDF viewer; for a scanned PDF, type or OCR the text and compare it with the page by eye. A web reader that summarises may cut long sentences, so read the page's raw text. Separate eligibility from benefit amounts and application steps. The reviewer confirms the text. | SJSA Maharashtra page (last updated 29.04.2025): "Eligible elderly individuals aged 65 and above, whose names are on the Below Poverty Line (BPL) list, receive monthly financial assistance under the Indira Gandhi National Old Age Pension Scheme." The age bands (65-79, 80+) only set amounts. Confirmed by the reviewer. A PDF offered as the central guideline turned out to be AI-written (log row 29). | Free |
| 2 | **Write the source file** | `data/schemes/rule_extraction_sources/<scheme>.json`: scheme ID, source (publisher, URL, retrieved, page date), and one case per clause with `text`, `location`, `allowed_fact_ids`, `topic_tags` (declared in the cases file). No answer key. If a clause is a list item, put its heading first in `text`, word for word, because `extract` reads only `text`. | `ignoaps_mh.json`, one clause `IGNOAPS-MH-ELIGIBILITY-01`, tag `inclusion_clause` | Free |
| 3 | **Check each condition has a fact that means the same thing** | Compare the wording with each candidate fact's meaning in the registry. A close-but-different fact makes the rule say something the text does not. | The first draft used `bpl_card_shown` ("Can you show a government BPL card?"), the only BPL fact. The text says "names are on the ... BPL list" and mentions no card. | Free |
| 3b | **If no fact fits, add one (reviewed)** | Add a registry entry: meaning, `value_type`, `scope`, `unit`, questions in en/hi/mr (optional help text), privacy block; leave reviews `pending`. Have an independent model check it; the human reviewer approves the **definition**. Questions wait for a native-speaker check, privacy for a privacy review. Re-pin the registry hash: get it with `(Get-FileHash src/rules/fact_registry.json -Algorithm SHA256).Hash.ToLower()` and replace the old value everywhere in `src/rules/bundle_registry.json` and `src/rules/data_provider.py`; run the tests. No command does this step yet. | Reviewer chose (Option B) a new fact `name_on_bpl_list` (yes/no, person): "no" means not eligible, "don't know" stays unknown. Independent check: approve all parts. Definition approved by `Roy-developer`; help text "If you are not sure, answer 'don't know'" added in all three languages; questions and privacy still pending. IGNWPS keeps its card-based fact. | Free |
| 4 | **Draft the rules with the model** | `python -m src.rule_extraction_reflexion.scheme_rules extract <source file> --playbook 1.0.0 --yes`. Calls `extract_rules` with no answer key: all package checks run; lessons with matching tags go into the prompt. Saved as a draft, never policy. | `age gte 65 years; name_on_bpl_list eq true`; lessons used: 0 (inclusion clause; the only lesson is about exclusions). Saved in `data/runtime/reflexion_drafts/`. | 1 call |
| 5 | **Reviewer decisions on what the text does not say** | Age measured on which date, inclusive boundaries, what an unknown or missing answer means. These are policy, never extracted. Record them in the source file's `reviewer_decisions`. | Age on the application date; 65 included; BPL "no" means not eligible, "don't know" stays unknown | Free |
| 6 | **Evidence review** | Follow `.github/skills/review-scheme-evidence/SKILL.md` and its template: source register, rule-by-rule findings with exact quotes, questions for a person, provisional development tests, disposition. Save as `docs/<SCHEME>_RULE_REVIEW_<date>.md`; sign-off stays pending. | `docs/IGNOAPS_MH_RULE_REVIEW_2026-11-08.md`: both rules `supported`; disposition `ready_for_human_review` | Free |
| 7 | **Independent second-model review** | A different model reviews the same evidence **without** seeing the first review. Record agreements and disagreements; the human resolves them. Look for conflicting official sources (for a state scheme, the central guideline). Unofficial documents (no letter number or date, made in a word processor, AI-written) are not evidence; if the reviewer chooses to consider one, record its limitations. | Second review agreed with both rules but said `changes_required`: it saw only part of the sentence (resolved: the full text was already captured) and could not open the central NSAP guidelines (their links on nsap.dord.gov.in are script placeholders). A provided central summary (an AI-written Google Docs file) said **60 and above**; the reviewer chose to consider it and it was recorded as source S2 with its limitations. | Free |
| 7b | **Resolve conflicts** | The reviewer decides each conflict; record both sources, the decision and the reasoning; keep it open if it needs a better source. | **65** (Maharashtra page governs the Maharashtra implementation); 60 recorded as `conflicting_sources`, open. Citizenship and "no other pension" (central summary only) not made rules; open questions. | Free |
| 8 | **Human sign-off** | Record reviewer, decision, conditions and date in the review document. A model can recommend but never approves. | Approved by `Roy-developer`, 2026-11-08, first as a Reflexion answer key, then for the app as a mock scheme (amendment in the review document) | Free |
| 9 | **Write the rule package** | Start from the rules in the draft (`data/runtime/reflexion_drafts/`). Add the approved rule IDs, each rule's `source_text` and `source_location` (word for word from the source file), `required_facts` (age needs `date_of_birth` and `application_date`), `age_as_of`, reasons, `notice`, `unresolved_checks`. The app shows `notice` and the reasons to users, so write them for users. Store it in `data/schemes/reflexion_packages/`, **not** `src/rules/packages/`: the app loads every file there and refuses one without a bundle entry. Check it with `python -c "import pathlib; from src.rules.models import RulePackage; RulePackage.model_validate_json(pathlib.Path('<file>').read_bytes()); print('ok')"`. Record its hash with `(Get-FileHash <file> -Algorithm SHA256).Hash.ToLower()`. | IGNOAPS sat in `data/schemes/reflexion_packages/` as an answer key, then moved to `src/rules/packages/ignoaps_mh.v1.json` when it went live | Free |
| 10 | **Add to the cases file** | One entry per clause in `data/schemes/rule_extraction_cases_dev.json` with `package`, `package_dir` (`data/schemes/reflexion_packages`), `package_sha256` (the script refuses a changed file), `topic_tags`, `context` (`[]` if the heading is already in the text) and a manual `split`. Use `check` if the model already reads it correctly (nothing to learn) or to keep it as a fair demo clause; `learn` only for real mistakes. | `check`: the model's draft matched the approved rules exactly | Free |
| 11 | **Measure** | `python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --playbook 1.0.0 --runs 3 --yes`. If the model makes real mistakes on `learn` clauses, run `learn`, `review` and `freeze` (see "The steps, end to end"), then measure again. | **18/18 exact** on the six check clauses (the earlier five 15/15, IGNOAPS 3/3) | 1 call per clause per run |
| 12 | **Record** | Update this guide and the review document; note open questions. | This section; review document sign-off | Free |
| 13 | **Approve for the app** | A separate decision from step 8. The reviewer, listed in `authorized_reviewers`, has this line added to the review document: ``App approval: `<SCHEME>` approved by `<login>` on <YYYY-MM-DD> for package SHA-256 `<hash>` ``. Any later edit to the package needs a new line. | Approved by `Roy-developer`, 2026-11-08 (amendment in the review document) | Free |
| 14 | **Put it in the app** | By hand or with `onboard`: both are shown below. | Done by hand first; `onboard` was then built and recreates the same files byte for byte | Free |
| 15 | **Write the document checklist and mock form** | `data/schemes/document_checklists/<SCHEME>.json` and `data/schemes/mock_forms/<SCHEME>.json`, marked `demo_only` until reviewed. A person writes these; `onboard` only reports them if missing. | Demo-only files with three checklist items and two form fields | Free |
| 16 | **Restart and walk through it** | Start `python -m uvicorn src.api.app:app --reload --port 8000` and `python -m streamlit run src/ui/app.py` in separate terminals. In the browser: search for the scheme, then try eligible, not eligible and "I don't know". Automated tests did not catch the two bugs this found. | Date picker refused old birth dates; an internal note reached users (log rows 35 and 36). The "No" answer, checklist and draft are not yet checked in a browser. | Normal app model calls |
| 17 | **Re-check the search thresholds** | `python scripts/calibrate_search_fallback.py --record signals.json`, then `--analyse signals.json`. Needed whenever passages change. | Not done yet for IGNOAPS | A few cents |
| 18 | **Finish the reviews and commit** | Native speakers review the questions, a privacy reviewer checks new facts, and someone reviews the remaining passages. Commit when ready; nothing here deploys by itself. | Questions, privacy and three passages are still pending | Free |

Total model cost for IGNOAPS: about 20 calls, well under 1 US cent.

**Step 14: by hand or with the command**

Both ways start from the same three inputs:

| Input | Where |
|---|---|
| The approved package | `data/schemes/reflexion_packages/` |
| An `onboarding` block in the source file, listing the search passages | `data/schemes/rule_extraction_sources/<scheme>.json` |
| The `App approval:` line from step 13 | `docs/<SCHEME>_RULE_REVIEW_<date>.md` |

The `onboarding` block looks like this (one entry per section of the official
page; `review_status` is set for each passage):

```json
"onboarding": {
  "scheme_name": "Indira Gandhi National Old Age Pension Scheme",
  "jurisdiction": "IN-MH",
  "source_id": "SRC-IGNOAPS-MH-001",
  "publication_date": null,
  "passages": [
    {
      "passage_id": "IGNOAPS-MH-ELIGIBILITY-01",
      "section": "eligibility",
      "text": "Eligible elderly individuals aged 65 and above, ...",
      "locator": "Scheme page; Eligibility Criteria section",
      "review_status": "reviewed"
    }
  ]
}
```

*Automated.* First see every change, then apply it:

```powershell
python -m src.rule_extraction_reflexion.scheme_rules onboard IGNOAPS-MH         # shows every change, writes nothing
python -m src.rule_extraction_reflexion.scheme_rules onboard IGNOAPS-MH --yes   # writes the changes, then runs the tests
```

Add `--skip-tests` to leave out the test run. The command works out every
change in memory and runs the app's real loader on a temporary copy before it
writes anything.

*By hand.* These are the same steps the command performs:

| # | Job | By hand | `onboard` |
|---|---|---|---|
| a | Check the approvals | Confirm the `App approval:` line names the package's current hash and a listed reviewer, `approval_status` is `approved_for_mock_portal`, every fact has `definition_review_status: approved`, and each rule's `source_text` matches the source file | Refuses if any is missing |
| b | Move the package | `Move-Item data/schemes/reflexion_packages/<file> src/rules/packages/` | Same |
| c | Cite the source on each fact | In `src/rules/fact_registry.json`, add the package's `source_url` to `source_refs` on every fact the scheme uses (required facts, rule facts, and what derived facts are built from) | Same |
| d | Re-pin the registry hash | Only if c changed the file. Run `(Get-FileHash src/rules/fact_registry.json -Algorithm SHA256).Hash.ToLower()` and replace the old value in every bundle in `bundle_registry.json` and in `_LEGACY_PILOT_BINDINGS` in `data_provider.py` | Same |
| e | Add the bundle | Add an entry to `src/rules/bundle_registry.json`: `scheme_id`, `bundle_version`, `activation_state: approved`, `package_file`, `package_version`, `package_sha256`, `registry_version`, `registry_sha256`, sorted `fact_ids`, `legacy_profile_mapping` (each required fact with a `legacy_profile_field`), sorted `source_clause_ids`, and null `checklist_version` and `mock_form_version` | Same |
| f | Add the search passages | Add one entry per passage to `data/schemes/passages.json`, with the source details from the package | Same, from the `onboarding` block |
| g | Update the Reflexion case | In the cases file, remove `package_dir` from the scheme's entries | Same; adds an entry if there is none and reminds you to choose a split |
| h | Check that it loads | `python -c "from src.rules.data_provider import RulePackageProvider as P; print(sorted(P().bundles))"` | Done on a copy, before writing |
| i | Run the tests | `python -m pytest -q` | Done after writing |

By hand, take care with these points:

- Pinned files are hashed byte for byte. An editor that reformats a file or
  changes its line endings changes the hash.
- Do step d after the last edit to `fact_registry.json`.
- Step h fails with a message naming what is wrong. That is how a missed step
  shows up (log row 34).

`onboard` refuses, and writes nothing, when:

- the app-approval line is missing, is for different package bytes, or names
  someone outside `authorized_reviewers`;
- the package is not human-approved, or a fact definition is not approved;
- a rule does not quote the source file's text word for word;
- the app's loader would refuse the result, including for another scheme.

The line in step 13 is needed because a package's `approved_for_mock_portal`
label cannot show app approval: packages used only as Reflexion answer keys
carry it too.

`onboard` does not write checklists or forms, choose a `learn` or `check`
split, or review anything; it lists those under "Still for people". If tests
fail after `--yes`, the files stay written, because a new scheme can break
tests that hard-code the number of schemes or passages. It never commits.

**A teammate on a fresh clone** needs no database: `extract --playbook 1.0.0`
reads `data/schemes/playbooks/1.0.0.json`, checks its hash and copies it into
their own local database. The run is refused if the file was altered, or if
their local `1.0.0` holds different lessons.

**All the commands in order**

```powershell
python -m src.rule_extraction_reflexion.scheme_rules extract data/schemes/rule_extraction_sources/<scheme>.json --playbook 1.0.0 --yes   # step 4, paid
python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check --playbook 1.0.0 --runs 3 --yes                              # step 11, paid
python -m src.rule_extraction_reflexion.scheme_rules onboard <SCHEME>                                                                    # step 14, preview
python -m src.rule_extraction_reflexion.scheme_rules onboard <SCHEME> --yes                                                              # step 14, apply
python -m uvicorn src.api.app:app --reload --port 8000                                    # step 16
python -m streamlit run src/ui/app.py                                                     # step 16
python scripts/calibrate_search_fallback.py --record signals.json                         # step 17, paid
python scripts/calibrate_search_fallback.py --analyse signals.json                        # step 17
```

**IGNOAPS files at a glance**

| File | Role |
|---|---|
| `data/schemes/rule_extraction_sources/ignoaps_mh.json` | Official text, source, allowed facts, reviewer decisions |
| `src/rules/fact_registry.json` (`name_on_bpl_list`) | The new fact |
| `data/runtime/reflexion_drafts/ignoaps-mh_*.json` | Model drafts (git-ignored, not policy) |
| `docs/IGNOAPS_MH_RULE_REVIEW_2026-11-08.md` | Evidence review, second review, conflicts, decisions, sign-off |
| `src/rules/packages/ignoaps_mh.v1.json` | Approved rule package, live in the app and used as the answer key |
| `src/rules/bundle_registry.json` | The IGNOAPS bundle (`approved`) with its hashes |
| `data/schemes/passages.json` | Four IGNOAPS search passages |
| `data/schemes/document_checklists/IGNOAPS-MH.json`, `data/schemes/mock_forms/IGNOAPS-MH.json` | Demo-only checklist and mock form |
| `data/schemes/rule_extraction_cases_dev.json` | IGNOAPS entry with hash and split `check` |

**Who does what for a new scheme**

| Who | Steps |
|---|---|
| Reviewer (a person; `Roy-developer` for IGNOAPS) | Confirms the official text (1), approves a new fact's definition (3b), makes policy decisions (5), resolves conflicts (7b), signs off (8), chooses the split (10), approves for the app (13) |
| A team member | Writes the source file (2) and package (9), writes the checklist and form (15), walks through the app (16) |
| Extraction model | Drafts the rules (4) |
| A second, independent model | Checks a new fact (3b) and the evidence (7) without seeing the first review |
| Code (`scheme_rules.py`, the package) | Checks the draft, stores drafts, verifies the hash, measures, puts the scheme in the app (4, 9-11, 14) |

**Three things to remember**

1. **Official text, word for word.** The source must be official and the reviewer
   confirms the exact wording before the model sees it.
2. **A rule is only as good as its fact.** If a fact does not mean exactly what
   the text says (BPL card versus BPL list), fix the fact first, with a review.
3. **The model drafts; people approve.** Two reviews and a human sign-off come
   before anything becomes an answer key, and the app is not touched until a
   person approves it for the app (step 13).

### Experience log: what went wrong while building it, and how it was fixed

The package was first written and tested offline with synthetic data. Using it
on real schemes with a real model exposed the problems below, in the order they
were found (2026-11-07). Code-level details and guard tests are in section 15.

```text
 review the code ─► first real run ─► fix the package ─► make schemes uniform ─► run on demand
        │                │                  │                     │                    │
   demo bypassed     P1, P2, P3          P1, P3, P4,          IGNWPS text,         scheme_rules.py,
   the package       found               units, policy        units, hash          cases file
                                                                                       │
             experiment ◄──────────────────────────────────────────────────────────────┘
   baseline 6/27 ─► headings added 8/27 ─► vague lessons ─► prompt fixed ─► 1 lesson ─► 8/15 → 10/15
```

| # | What happened | Why | How it was fixed | Where / guard |
|---|---|---|---|---|
| 1 | The real-call demo looked like it worked, but it never ran the package's checks | It rebuilt the prompts and the model call itself instead of calling `extract_rules` / `propose_lesson`, and added its own tag instruction to the prompt | New rule: a demo or check script calls the package's own functions, only swapping the model. `src/rule_extraction_reflexion/scheme_rules.py` follows it | Warning box above; section 13 |
| 2 | Offline tests passed, but only on one made-up case (`exam_ratio`) | Fakes only test answers someone thought to write | Real runs find behaviour; each real failure is then copied into an offline (fake-model) test, so it is checked for free on every test run | Section 15 tests |
| 3 | A correct rule counted as two errors (P1) | Rules were matched by ID; the model never sees the approved IDs and invented `rule1` | Match by meaning (clause + fact + operator); code sets the rule ID | Section 8 diagram |
| 4 | That false difference produced a useless lesson (P2) | Followed from 3 | Fixed by 3 | — |
| 5 | The lesson step crashed on a tag like `rule-extraction` (P3) | The model chose tags; the format was never stated to it | The model writes only the lesson text; code adds the tags | Section 9 |
| 6 | An approved lesson might never be used again (P4) | Model-chosen tags need not match the tags people put on cases; the old tests typed the same tag on both sides, which hid this | Lessons take the case's tags; every case needs a tag; a test follows a lesson into the next case's prompt | Section 11 |
| 7 | The same mistake could be stored many times | A lesson's ID is a hash that included the model's random rule names | Fixed by 3: the same rule now gets the same ID every run | Section 7 |
| 8 | IGNWPS had no clause text on its rules, PM-KISAN did | The schemes were reviewed three days apart in different formats; IGNWPS kept its one sentence at package level | Reviewer-approved amendment copied the text and location onto each rule; a test now requires this for every package | Section 15, IGNWPS row |
| 9 | Editing the package first inserted the new fields twice | A two-step text replacement matched its own output | The app's strict loader refused the file; the original was restored and the edit redone in one pass. Pinned package files must keep their exact bytes (Windows line endings), because the hash covers every byte | Section 15, IGNWPS row |
| 10 | IGNWPS age rules could never match the model's correct answer | They had no unit and were accepted only through a special legacy exception; the model correctly writes `years` | Reviewer-approved: age rules now say `"unit": "years"` | Section 15, Units row |
| 11 | A correct pension rule would have been rejected | The extractor demanded the registry unit on every rule, but the pension fact is yes/no while its question names an amount (unit `INR`) | Units are checked for number facts only, as the app's loader does; a test runs every approved clause through the checks | Section 7 |
| 12 | The model could not know the IGNWPS "no BPL card shown: ask for the card" behaviour | That is reviewer policy, not in the official sentence | Reviewer decision (Option B): `if_not_met` and `missing_field_label` are not compared | Section 8 table |
| 13 | Early runs were in throwaway scripts outside the project, so nobody else could repeat them | They were prototypes | Built `src/rule_extraction_reflexion/scheme_rules.py` and the cases file in the project; paid commands need `--yes` | Section 13 |
| 14 | Idea: put deliberate mistakes into an approved rule to have something to learn | — | Rejected: a wrong answer key marks correct answers wrong and teaches false lessons. Mistakes must come from the model | Rules above |
| 15 | Worry: learning on every approved clause leaves nothing to show the team | Learning "uses up" a clause; measuring does not | Split clauses into `learn` and `check` before learning; check clauses stay valid for demos | Step 3 |
| 16 | Baseline 6/27: every exclusion wrong | The clause text was a list item without its "shall not be eligible" heading | Read the official PDF (page 2) and added the headings as `contexts`; result 8/27, a genuine misreading worth learning from | First experiment |
| 17 | First lessons were vague ("Ensure ... accurately reflected") and named single groups | The reflection prompt only asked for "a general correction" | Prompt now states the rule convention and asks for an actionable, general lesson, with a neutral example so it does not give away the answer | Section 9 |
| 18 | Four new lessons said the same thing | Each learn clause produced its own lesson | Approve the clearest one, reject the rest as duplicates (at most three matching lessons are added to a prompt) | Step 5 |
| 19 | Reviewer identity | Only one person was listed, by display name | Any team member can review, by GitHub login; earlier decisions keep the name they were recorded under, because reviews cannot be changed | Cases file |
| 20 | A test started failing after the split was set | It assumed no clause had the `learn` split in the real cases file | The test now uses its own temporary cases file; the script reads the cases file path at run time | `tests/test_scheme_rules.py` |
| 21 | Running the script with the project's `.venv` failed on LangChain imports | The `.venv` predated the new dependencies | `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` | Section 14 |
| 22 | Demo output crashed on Windows with `UnicodeEncodeError` | The console could not print an arrow character | Set `$env:PYTHONIOENCODING="utf-8"` before running the demos | — |
| 23 | Pension was rejected in almost every run, and the error did not show why | The validation library shortens the model's answer in its message; the model, given only fact names, wrote a number rule (`gte 10000`) for a yes/no fact | The script prints the model's full answer for rejections (`rejection_detail`); fact definitions were approved and the model is now told each fact's type | Section 5; `test_model_is_told_each_allowed_fact_type_but_not_its_meaning`, `test_rejected_answer_report_shows_exactly_what_the_model_wrote` |
| 24 | After the types fix, the score with the playbook was 15/15; was that the types or the lesson? | Two things had changed at once | A control run with types but no playbook gave 9/15, so the lesson accounts for the rise from 9 to 15 | First experiment, step 10 |

| 25 | The first new-scheme draft used a fact that did not match the text | The only BPL fact was card-based (`bpl_card_shown`); IGNOAPS's text says "names are on the BPL list" | Reviewer added a matching fact, `name_on_bpl_list`, reviewed by an independent model and approved by the reviewer | New-scheme step 3b |
| 26 | Approving all fact definitions might have changed app behaviour | Unknown at the time | Checked: the status is a label (only reviewer and date are required); approving changes the registry fingerprint, so saved mock-portal approvals ask to be confirmed again after deployment | Fact registry |
| 27 | A web reader cut the official eligibility sentence short | Its summariser limits quote length | Read the page's raw text and quote the full sentence | New-scheme step 1 |
| 28 | The central NSAP guidelines could not be opened | Their download links on nsap.dord.gov.in are script placeholders | Recorded as a source limitation; the age question stays open | New-scheme step 7 |
| 29 | A provided "central guideline" PDF was an AI-written summary (ends with a chatbot reply; Google Docs metadata) | Unofficial documents circulate under official-looking names | Not treated as official; the reviewer chose to consider its content and it was recorded as source S2 with its limitations | New-scheme step 7 |
| 30 | The Maharashtra page (65) and the central summary (60) disagree on age | State and central sources differ | Reviewer decided 65 for IGNOAPS-MH; 60 kept as an open `conflicting_sources` question | Review document |
| 31 | Saving the IGNOAPS package with the live packages would have broken the app | The app loads every file in `src/rules/packages/` and requires a bundle for each | Stored it in `data/schemes/reflexion_packages/`, pinned its hash in the cases file; the script reads `package_dir`. Superseded when IGNOAPS went live (row 33) | New-scheme step 9 |
| 32 | Two tests failed after IGNOAPS was added | They hard-coded 9 cases and 27 calls | Tests now count the cases instead | `tests/test_scheme_rules.py` |
| 33 | A third scheme had no legitimate way into the app | A bundle could only be `legacy_compatibility` (the two pinned pilots) or `development_only` (tests) | Added an `approved` state, which requires a human-approved package and approved definitions for every fact in the bundle | `_validate_bundle` in `src/rules/data_provider.py`; `tests/test_fact_registry.py` |
| 34 | The loader refused the first IGNOAPS bundle | The facts did not cite the scheme's source, and date of birth and application date needed a shared-answer mapping | Added the source URLs and `legacy_profile_mapping`, then re-pinned the registry hash | New-scheme step 14 |
| 35 | Older applicants could not enter their date of birth | `st.date_input` allows only ten years either side of today by default | Set an explicit range, 1900 to 2100 | `tests/test_ui_app.py::test_registered_date_question_accepts_an_old_date_of_birth` |
| 36 | Users saw an internal note about the answer key | The app shows the package's `notice` as written | Reworded it for users and re-pinned the hash; a test blocks internal wording | `tests/test_ignoaps_eligibility.py::test_ignoaps_notice_is_written_for_users` |
| 37 | Three wording problems on the result screen: the reason named the date of birth even when given, the internal name `name_on_bpl_list` was listed, and the chat showed "skip" | The reason was written for one case; the screen printed fact IDs; the chat stored the button's code | Neutral reason (hash re-pinned); missing facts now appear as their question in the person's language; the chat shows "I don't know" | `test_missing_fact_is_shown_as_its_question_not_its_internal_name`, `test_dont_know_appears_in_the_chat_as_the_person_chose_it` |
| 38 | 34 test errors appeared after browser testing | A portal server left running on port 8765 was still in use | Stop all local servers before running the test suite | — |
| 39 | Going live took edits to six files by hand, and a missed step only showed up as a loader error | The steps were mechanical but nothing automated them | Built `scheme_rules.py onboard`; a test undoes IGNOAPS on a copy and requires the command to recreate the hand-made files byte for byte | `tests/test_scheme_onboarding.py` |
| 40 | A teammate could not use `--playbook 1.0.0` | Playbooks lived only in a git-ignored database on one laptop, so a fresh clone stopped with "Unknown playbook version" | Playbooks are exported to `data/schemes/playbooks/` and copied into the local database on first use; the hash check refuses an altered file; `freeze --base` keeps lessons approved elsewhere | `tests/test_scheme_rules.py` |
### Known open issues

- **Rejected answers cannot teach.** An answer that fails the package's checks
  stops before comparison, so no lesson is proposed from it. Pension was fixed
  by giving the model fact types instead; letting the reflection step learn
  from rejections is not built.
- **Small sample:** 3 runs per clause, three schemes, one model; the 9/15 to
  15/15 (and 18/18 with IGNOAPS) result should be confirmed with more runs and
  more schemes, including a new scheme with exclusion clauses.
- **Lessons are local; playbooks are shared.**
  `data/runtime/reflexion_lessons.sqlite3` is git-ignored, so pending lessons
  and review history stay on one machine. Frozen playbooks are shared through
  `data/schemes/playbooks/`.
- **Structured-output method:** the extractor uses the library default
  (`json_schema`), which only some OpenRouter models support; intake uses
  `json_mode`. Switching models may need this decided.
- **New-scheme drafts are not yet in the evidence-review format.** `extract`
  writes typed rules; the existing PM-KISAN draft uses plain-language claims.
- **IGNOAPS open questions:** central age 60 versus Maharashtra 65,
  citizenship, and non-receipt of other pensions (official central guideline
  not obtained); Hindi/Marathi wording of `name_on_bpl_list` awaits a native
  speaker, and its privacy review is pending. IGNOAPS is live as a mock scheme
  only.
- **IGNOAPS checks not done in a browser:** the "No" answer (automated tests
  only), the document checklist and the application draft.
- **Search thresholds** were calibrated on 13 passages; there are now 17, so
  they should be re-checked.
- **IGNWPS still lists `government_bpl_card`** on its result screen, because
  that label is not a registered fact.

## 1. What problem does this solve?

Use this synthetic source clause throughout the guide:

> The synthetic exam ratio must be at least 0.6.

The expected rule is:

```python
Rule(
    rule_id="synthetic-ratio-minimum",
    field="exam_ratio",
    operator="gte",
    value=0.6,
    unit="ratio",
    source_clause_id="synthetic-clause-1",
)
```

`gte` means greater than or equal to. `eq` means equal to; `lte` means less
than or equal to.

Suppose the model extracts `0.7`. Python detects that the `value` differs.
The model can then propose a lesson such as "Copy the exact threshold from the
source." A human must review that lesson before later extractions can use it.

This does **not** train the model or change its weights. It stores reviewed
guidance and includes matching guidance in later prompts. It also does not
decide whether a person is eligible: eligibility remains in the rule engine.

```text
One development attempt:
source + allowed facts + optional approved lessons
    -> extraction -> Python checks -> comparison with reference rules
    -> if different: propose one lesson -> save as pending

Separate review and reuse:
pending lesson + evidence -> authorized human review
    -> freeze approved lessons -> retrieve by tag for a later attempt

Separate measurement:
supplied cases + optional frozen playbook -> extraction + comparison -> report
```

There is no automatic retry of the failed extraction.

## 2. Code-reading order

All source files below are inside `src\rule_extraction_reflexion`.

| Read | File / function | Responsibility |
|---|---|---|
| 1 | `models.py` | Defines the shapes of cases, proposals, reviews and reports |
| 2 | `reflexion.py`: `run_reflexion_case()` | Shows the main sequence |
| 3 | `extractor.py`: `extract_rules()` | Prepares model input |
| 4 | `extractor.py`: `invoke_structured_output()` | Makes the model call |
| 5 | `extractor.py`: validation helpers | Checks proposed facts, values and evidence links |
| 6 | `extraction_checker.py`: `compare_rules()` | Compares proposals with reference answers |
| 7 | `reflexion.py`: `propose_lesson()` | Proposes guidance after a mismatch |
| 8 | `lesson_store.py` | Saves proposals and separate human decisions |
| 9 | `playbook.py` | Freezes, verifies and retrieves approved guidance |
| 10 | `evaluation.py` | Scores supplied cases without learning |
| 11 | `src/rule_extraction_reflexion/scheme_rules.py` | Builds cases from the cases file and packages, and runs the commands |
| 12 | `src/rule_extraction_reflexion/onboarding.py` | Works out, checks and writes the changes that put an approved scheme in the app |

The shared `Rule` model is in `src\rules\models.py`; fact definitions and
`FactRegistry` are in `src\rules\facts.py`.

## 3. Understand the data models

Open `models.py`.

| Model | Plain-English meaning |
|---|---|
| `SourceClause` | Selected source text, an ID and an optional location |
| `RuleExtractionCase` | One case: clauses, allowed fact IDs, reference rules and at least one topic tag |
| `RuleExtractionOutput` | The model's proposed rules (their IDs are replaced; see section 7) |
| `LessonText` | What the reflection model writes: an instruction and when it applies, nothing else |
| `LessonProposal` | That text plus tags, which code copies from the case's `topic_tags` |
| `RuleDifference` | A rule ID and the names of its differences |
| `PendingLesson` | A proposal saved with source, reference rules, proposed rules and differences |
| `LessonReview` | A separate approved/rejected human decision with reviewer and reason |
| `ApprovedLesson` | Reviewed guidance copied into a playbook |
| `PlaybookSnapshot` | A version, approved lessons and a content hash |
| `EvaluationCaseResult` | One case's match result and differences |
| `PlaybookEvaluation` | Aggregate results and the optional playbook version/hash |

`ReflexionResult`, defined in `reflexion.py`, contains proposed rules,
differences and an optional pending lesson.

### Why `StrictModel` matters

```python
model_config = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
)
```

- `extra="forbid"` rejects undeclared fields. A lesson proposal cannot add
  its own `status="approved"`.
- `frozen=True` blocks normal attribute reassignment after creation.
- `str_strip_whitespace=True` removes leading/trailing whitespace from string
  fields where Pydantic applies that setting.

```python
status: Literal["pending"] = "pending"
```

This accepts only `"pending"` on a `PendingLesson`. Approval does not change
that object's status; it creates a separate `LessonReview`.

These are data safeguards, **not permission checks**. Frozen models also do not
make every nested collection immutable: `ReflexionResult.differences` is still
a dictionary containing lists. Stored lesson evidence uses tuples instead.
Direct Store writes and `model_copy(update=...)` are not prevented by freezing.

The validators also reject duplicate clause IDs, blank/duplicate allowed fact
IDs, invalid/duplicate tags and a case without topic tags. Duplicate *rules*
are checked by meaning during validation (section 7), not by model-chosen ID.

`LessonText` is the one exception to `extra="forbid"`: it uses
`extra="ignore"`, so a field the model adds on its own (such as `tags`, or
even `status`) is dropped instead of failing the lesson. Nothing it drops can
reach a stored record, because code builds the `LessonProposal` from only the
two text fields and the case's tags.

## 4. Follow `run_reflexion_case()`

Open `reflexion.py` and find this function.

```python
proposed_rules = await extract_rules(
    model, case, registry, playbook=playbook,
)
differences = compare_rules(case.expected_rules, proposed_rules)
```

The model proposes; Python compares. `await` waits for an asynchronous operation
without blocking the event loop.

```python
if not differences:
    return ReflexionResult(
        proposed_rules=proposed_rules,
        differences={},
    )
```

No differences means the attempt ends without a reflection call or lesson.

Otherwise it calls `propose_lesson()` and `save_pending_lesson()`, then returns
the proposal result and saved pending record.

There are at most two structured model invocations in this function: extraction
and, on mismatch, reflection. This is not a shared monetary/token budget, nor a
guarantee about provider-level retries. Validation/model exceptions propagate;
invalid extraction output is not converted into a pending lesson.

## 5. Prepare the extraction prompt

Open `extractor.py`, function `extract_rules()`.

```python
allowed_facts = frozenset(case.allowed_fact_ids)
for fact_id in allowed_facts:
    registry.get(fact_id)
```

`frozenset` is a non-editable set. Each allowed ID must exist in the registry
before the model is called. "Allowed" means allowed for this case, not human
approval of a fact definition or policy.

```python
clauses_by_id = {clause.clause_id: clause for clause in case.clauses}
```

This dictionary lets Python find the selected source text by its ID.

If a playbook was supplied, `relevant_lessons()` selects matching approved
guidance. Otherwise guidance is empty.

The payload contains:

```text
allowed_facts (fact_id + type; unit for number facts; codes for choice facts)
source_clauses
approved_extractor_lessons (instruction + when_to_apply)
```

For the pension clause, for example, `allowed_facts` is
`[{"fact_id": "pension_at_least_10000_excluding_stated_grades", "type": "boolean"}]`.
`_fact_shape()` builds each entry. The system prompt also says how to write a
value of each type (a boolean fact takes true or false with `eq`).

**It does not contain `case.expected_rules`.** Giving the extractor those
answers would spoil the development check. Reference rules are used later
by the checker and reflection call.

The payload sends each fact's ID and type, not its meaning or question text.
Until 2026-11-07 it sent IDs only, and the model wrote `gte 10000` for the
yes/no pension fact (section 15). A yes/no fact's registry unit (the pension
fact's `INR`) is not sent, because it describes the question, not the rule.
Python still uses the full definitions to validate the output afterward.

## 6. Make the structured model call

Still in `extractor.py`, read `invoke_structured_output()`.

```python
runnable = model.with_structured_output(output_schema)
result = await runnable.ainvoke(
    [
        SystemMessage(content=system_text),
        HumanMessage(content=user_text),
    ]
)
```

`output_schema` is `RuleExtractionOutput` for extraction and `LessonProposal`
for reflection. It asks for a defined answer shape instead of a free-text essay.

The system message holds instructions. The human message holds JSON data.
`json.dumps()` converts the prepared dictionary into text.
`ensure_ascii=False` preserves non-ASCII characters; `sort_keys=True` gives
dictionary keys a consistent order.

If the integration returns an instance of the requested model, it is returned.
Otherwise `output_schema.model_validate(result)` validates and converts it.

**Correct shape is not correct policy.** Both `0.6` and `0.7` can be valid
numeric values. Source text is always untrusted input, even when selected by a
human. The prompt says not to follow instructions inside it; this alone does
not prove resistance to prompt injection.

## 7. Validate the proposed rules

Read `_validate_extracted_rules()` in `extractor.py`.

For every rule, it:

1. Replaces the model's rule ID with a meaning-based one,
   `"<source_clause_id>:<field>:<operator>"` (`meaning_rule_id()` in
   `extraction_checker.py`), and rejects two rules with the same meaning.
2. Rejects a field outside this case's allowed facts.
3. Loads that field's registry definition.
4. Rejects a source clause ID not supplied in this case.
5. Calls `_validate_rule_value()`.
6. Creates a new `Rule` with exact supplied source text and location.

```python
values = rule.model_dump(exclude={"rule_id", "source_text", "source_location"})
validated.append(Rule(
    **values,
    rule_id=rule_id,
    source_text=clause.text,
    source_location=clause.location,
))
```

`**values` passes dictionary entries as keyword arguments. We discard the
model's quote/location, rather than trusting model-written evidence, and its
rule ID, which it has to invent (it never sees the approved IDs). The same
rule therefore gets the same ID on every run, so the same mistake produces
the same lesson identity and is not stored twice.

`_validate_rule_value()` rejects display-only text facts, restricts booleans
to `eq` with a boolean, restricts choices to `eq`, calls
`FactDefinition.validate_value()` and, for number facts only, requires the
registered unit. As in the package loader (`rules/data_provider.py`), a yes/no
or choice rule carries no unit even when its question names an amount: the
PM-KISAN pension fact is yes/no but registered with unit `INR`. The existing
`Rule` model also performs its own validation; a yes/no fact given a number is
already rejected while the model's reply is read.

For our example, the unit must be `"ratio"`, not `"percent"`.
A value outside the registry's allowed range is rejected.

These checks do not prove the cited clause supports the rule. A wrong but
valid threshold can pass validation and then fail comparison.

If any check fails, `extract_rules` raises `ValueError` for the whole answer:
no rules are returned, nothing is compared and no lesson is proposed. For
example, reading "40 to 79" as two lower limits (`age gte 40`, `age gte 79`) is
rejected as two rules with the same meaning. `scheme_rules.py` reports such a
case as `rejected`.

## 8. Compare with the reference rules

Open `extraction_checker.py`.

Why rules are paired by meaning (problem P1, section 15):

```text
BEFORE (paired by rule ID)
  approved:  PMKISAN-LAND-FAMILY-01   landholding_family_in_state_records eq true
  model:     rule1                    landholding_family_in_state_records eq true   <- right answer, invented name
  result:    {"PMKISAN-LAND-FAMILY-01": ["missing"], "rule1": ["unexpected"]}
             -> a reflection call and a useless lesson about rule names

AFTER (paired by meaning)
  model's ID replaced by code:  PMKISAN-GUIDELINES-2020-3:landholding_family_in_state_records:eq
  both sides' key:              (PMKISAN-GUIDELINES-2020-3, landholding_family_in_state_records, eq)
  same key -> compare value, unit, clause -> all equal
  result:    {}  -> no reflection call, no lesson
```

`compare_rules()` pairs rules by **meaning**: `rule_meaning()` returns
`(source_clause_id, field, operator)`. The operator is part of the key because
one clause can hold two rules on one fact (IGNWPS: `age gte 40` and
`age lte 79`). Two rules with the same meaning in either input raise
`ValueError`.

It reports:

| Situation | Difference |
|---|---|
| No proposed rule has an expected rule's meaning | `["missing"]` under the approved ID |
| A proposed rule's meaning is not in the reference | `["unexpected"]` under the proposed ID |
| Same meaning, changed threshold | `["value"]` under the approved ID |
| Same meaning, wrong operator | One `missing` plus one `unexpected` (it is a different kind of rule) |
| Same meaning, no compared fields differ | No entry |

Compared fields are `field`, `operator`, `value`, `unit` and
`source_clause_id`: only what a model can read from the source clause.
`if_not_met` and `missing_field_label` are **not** compared (section 15).

| Rule field | Compared? | Why |
|---|---|---|
| `field`, `operator`, `source_clause_id` | Yes (they also form the pairing key) | Stated by the clause |
| `value`, `unit` | Yes | Stated by the clause |
| `if_not_met`, `missing_field_label` | No | Reviewer policy, e.g. IGNWPS "no BPL card shown: ask for the card" |
| `rule_id` | No (replaced by code) | The model never sees the approved IDs |
| `source_text`, `source_location` | No (replaced by code) | Always copied from the trusted clause |

For the synthetic wrong threshold:

```python
{"synthetic-ratio-minimum": ["value"]}
```

Source text/location are not compared here; validation already replaced them
with the trusted clause. "Exact match" in the report means matching meanings
and these compared fields, not byte-for-byte equality of every model field.

## 9. Propose a lesson

Return to `reflexion.py`, function `propose_lesson()`.

Its payload includes source clauses, reference rules, proposed rules and
detected differences. Reference answers are appropriate here because this
call is reviewing a completed development error, not taking the extraction test.

The model is asked for one `LessonText` (words only). Code then adds the
case's topic tags:

```python
text = await invoke_structured_output(model, LessonText, REFLECTION_SYSTEM_PROMPT, ...)
return LessonProposal(**text.model_dump(), tags=case.topic_tags)
```

For a case tagged `("age_boundary",)` the result is, for example:

```python
LessonProposal(
    instruction="Copy the exact numeric threshold from the source.",
    when_to_apply="Extracting a numeric minimum or maximum.",
    tags=("age_boundary",),
)
```

The model never chooses tags, so a lesson always carries exactly the tags that
later cases on the same topic use, and it cannot fail the tag format (section
15 explains the failures that led to this).

A human must check whether a lesson actually addresses the observed error.
The code does not judge lesson quality.

## 10. Save the pending lesson and review it

Open `lesson_store.py`.

LangGraph Store uses namespaces to separate records:

| Namespace | Content |
|---|---|
| `("rule_extraction_reflexion", "lessons")` | Pending proposals and evidence |
| `("rule_extraction_reflexion", "reviews")` | Separate review decisions |
| `("rule_extraction_reflexion", "playbooks")` | Frozen snapshots, handled in `playbook.py` |

`aget()` reads a record; `aput()` writes one. `asearch()` lists records.
They are asynchronous Store methods, not calls to an LLM.

### Stable identity

`lesson_identity()` serializes proposal and evidence in a consistent JSON form,
then computes SHA-256. The resulting string is the lesson ID.
`save_pending_lesson()` rejects an existing identical ID and stores the record.

`validate_pending_lesson()` recomputes the identity during review/freezing.
Changing the proposal or hashed evidence while keeping its ID causes rejection.
Creation time is not part of this hash.

A hash is a content check, not authentication or a digital signature.
Someone with direct Store write access can replace content and recompute hashes.
Also, the storage helper records supplied differences; it does not independently
recompute them from supplied rules. The main workflow obtains them from the checker.

### Where permission is checked

Find this exact block in `review_lesson()`:

```python
if not authorize_reviewer(reviewer_id):
    raise PermissionError("Reviewer is not authorized")
```

The caller must supply a trusted function that checks the reviewer. The package
does not authenticate the person. An arbitrary reviewer string is not proof of
identity. The simple lambdas in tests simulate this boundary only.

After permission succeeds, the function checks that the lesson exists, validates
its content, refuses an existing review and stores one decision with a reason.
Pending proposals remain pending records; the review is stored separately.

`InMemoryStore` lasts only for that process. `AsyncSqliteStore` can persist across
restarts when configured with a database path. The tests use temporary SQLite
paths, never the application's runtime database.

## 11. Freeze and reuse approved guidance

Open `playbook.py`.

`freeze_playbook(store, "1.0.0")`:

1. Refuses an already stored version.
2. Reads pending lessons in pages of 100, with a 500-lesson maximum.
3. Checks each lesson's identity and looks up its separate review.
4. Copies only approved lessons.
5. Sorts them by lesson ID.
6. Hashes version plus ordered lesson content and saves the snapshot.

Versions use numeric `major.minor.patch`, for example `"1.0.0"`.
Changes require a new version rather than overwriting the old one through this
function. An empty approved playbook is currently allowed.

`load_frozen_playbook()` checks the requested version and content hash.
`relevant_lessons()` verifies the hash and selects lessons sharing at least one
tag with the case. The default limit is three. Every case must have at least
one topic tag, and lessons inherit their case's tags, so a lesson is found by
any later case that shares a topic tag.

This is simple exact-tag retrieval, not vector search or semantic ranking.
Matching lessons retain snapshot order; they are not ranked by relevance.

**Concurrency boundary:** review/freezing use read-then-write checks, not an
atomic create-if-absent transaction. Concurrent writers could bypass the
single-review/single-version intention. Use this as a serial development
workflow; production multi-worker immutability is not established.

## 12. Evaluate without learning

Open `evaluation.py`, function `evaluate_cases()`.

It accepts a model, explicit cases, a registry and an optional frozen snapshot.
It rejects an empty list, more than 60 cases or duplicate case IDs, and verifies
any supplied snapshot before extraction.

For each case it extracts once and compares the result. It returns counts,
per-case differences and the optional playbook version/hash.
`model_call_count` is one extraction invocation per completed case in the report,
not provider HTTP-attempt or token accounting.

It does not propose lessons, write Store records or open evaluation files.
If extraction raises, the run raises instead of returning a partial failure report.

`python -m src.rule_extraction_reflexion.scheme_rules evaluate --split check [--playbook X]` runs this
before/after comparison on real clauses; the first result is in "Start here",
"First experiment". These calls cost money. The offline tests still prove only
the Python workflow, not model accuracy, latency, cost or full E1-E4 acceptance.
Never load `data\heldout` while developing.

## 13. How to run it safely now

There is no API endpoint or Streamlit screen for this package, and it is not
connected to the deployed app.

**On-demand runs on approved clauses: `src/rule_extraction_reflexion/scheme_rules.py`.** Each command
calls one package function; nothing re-implements prompts or checks. The
commands, in order, are in the steps table in "Start here". What each one calls:

| Command | Package function | Cost |
|---|---|---|
| `evaluate` | `evaluate_cases` (measures; never learns) | 1 call per case per run |
| `learn` | `run_reflexion_case` on `learn` clauses only | up to 2 calls per case |
| `lessons` | lists stored lessons and their reviews | free |
| `review` | `review_lesson` (`--reviewer` must be a GitHub login listed in `authorized_reviewers`) | free |
| `freeze <version> [--base <version>]` | `freeze_playbook`; `--base` keeps an earlier playbook's lessons | free |
| `export-playbook <version>` | `export_playbook`: writes the frozen playbook to `data/schemes/playbooks/` for git | free |
| `extract <source file> [--playbook 1.0.0] --yes` | `extract_rules` with no answer key: drafts rules for a **new** scheme | 1 call per clause |
| `onboard <SCHEME> [--yes] [--skip-tests]` | `plan_onboarding`, `apply_onboarding`: puts a human-approved scheme in the app | free |

Paid commands state their cost and send nothing until `--yes` is given; they
use the project's key and model from `.env` via `src/config.py`. Cases are
listed in `data/schemes/rule_extraction_cases_dev.json`: one entry per approved
clause, with topic tags and a split. Clause text, approved rules and allowed
facts are read from the rule package, so the file duplicates no policy.

- `learn` clauses may produce lessons. `check` clauses are only measured, never
  learned from, so they stay valid for before/after comparisons and demos.
  Measuring does not use a clause up; learning does. `learn` refuses to run
  until clauses are assigned the `learn` split.
- A clause that is an item in a list is shown after the headings it sits
  under in the source: its `context` names heading entries in the file's
  `contexts` block (copied word for word, with page and section). The first baseline (2026-11-07) showed why: PM-KISAN exclusion
  items such as "All Institutional Land holders." were given without the 4.1
  heading "... shall not be eligible ...", and the model wrote `eq true` in all
  18 runs on six such clauses. Headings are never compared or stored as evidence.
- Only reviewers listed in `authorized_reviewers` can approve or reject.
- Lessons, reviews and playbooks are kept in
  `data/runtime/reflexion_lessons.sqlite3`; evaluation reports in
  `data/runtime/reflexion_reports/`. Both are git-ignored.
- Offline tests: `tests/test_scheme_rules.py`.

The older standalone demo scripts (`scripts/reflexion_demo*.py`) are
walkthrough aids only. See the warning box in "Start here":
`reflexion_demo_real.py` rebuilds prompts itself instead of calling the
package, so use `scheme_rules.py` for real runs.

**Use the existing tests as runnable offline examples.** They execute the real
Python workflow with scripted model responses. No API key, server or paid call
is needed.

Run commands from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -x tests\test_reflexion_models.py tests\test_extraction_checker.py tests\test_rule_extraction_reflexion.py tests\test_scheme_rules.py
```

To follow just the failed extraction and pending lesson:

```powershell
.\.venv\Scripts\python.exe -m pytest -v -x tests\test_rule_extraction_reflexion.py -k test_reflexion_saves_model_lesson_as_pending
```

Read that test while running it:

1. It changes the synthetic threshold from `0.6` to `0.7`.
2. It installs a fake extraction response and fake lesson response.
3. It creates an `InMemoryStore`.
4. `asyncio.run(...)` executes `run_reflexion_case()`.
5. Assertions check the `["value"]` difference and pending lesson.

The scripted lesson in this test talks about `gte`, while the injected error
is the value. This test proves orchestration/storage, not lesson quality.

The fake helper replaces `invoke_structured_output` with `monkeypatch`.
Extraction is patched in `extractor`; reflection is patched in `reflexion`
because that module imported the function directly.
Tests pass `None` for the model only because this boundary is replaced.
Passing `None` without that replacement is not a usable model configuration.

There is also an older real-call demo. **It is not the way to run real
experiments** (it rebuilds the prompts itself; see the warning box in
"Start here"); it is described here only because it still exists:

```powershell
.\.venv\Scripts\python.exe scripts\reflexion_demo_real.py
```

**This script contacts OpenRouter and may incur charges. Do not run it as a
test.** It loads the project `.env` through `src.config`, refuses to use an
inherited API key if the project key is missing, and stores lessons in
`data\runtime\reflexion_demo.sqlite3` using `AsyncSqliteStore`. The database is
ignored by Git. The script's human-review prompt is a local demonstration,
not an authenticated review interface. A run uses a live model and synthetic
input, so it is still not evidence of model accuracy or production readiness.

If you approve the proposed lesson in the prompt, the script records the
separate review and then calls `freeze_reviewed_lessons()`. That function finds
the latest saved playbook version, creates the next patch version (`1.0.0`,
then `1.0.1`, and so on), freezes all currently approved lessons, and reloads
the snapshot to verify its hash. It prints the version, lesson count and hash.
Rejecting or skipping review does not add that proposal to a playbook.
The playbook is stored in the same SQLite database under its own Store
namespace; this is durable persistence, not a separate playbook file.

## 14. Test each part while reading

Use the same test file with a different `-k` selection:

```powershell
# Permission denial, approved/rejected filtering, tags and version reuse
.\.venv\Scripts\python.exe -m pytest -v -x tests\test_rule_extraction_reflexion.py -k test_only_authorized_approved_lessons_enter_frozen_playbook

# Save to temporary SQLite, close it and reload the frozen snapshot
.\.venv\Scripts\python.exe -m pytest -v -x tests\test_rule_extraction_reflexion.py -k test_approved_playbook_survives_sqlite_store_reopen

# Detect a changed proposal kept under its original lesson ID
.\.venv\Scripts\python.exe -m pytest -v -x tests\test_rule_extraction_reflexion.py -k test_tampered_pending_lesson_cannot_be_reviewed

# Basic supplied-case evaluation with a fake model
.\.venv\Scripts\python.exe -m pytest -v -x tests\test_rule_extraction_reflexion.py -k test_evaluation_uses_one_call_per_case_and_reports_exact_matches
```

| Test file | What to learn |
|---|---|
| `tests\test_reflexion_models.py` | Extra approval fields, pending-only status, blocked normal reassignment |
| `tests\test_extraction_checker.py` | Matching, changed, missing, extra and duplicate rules |
| `tests\test_rule_extraction_reflexion.py` | Extraction evidence checks, pending workflow, review, freezing, persistence and basic evaluation; every kind of model answer on the real PM-KISAN and IGNWPS rules; lesson tags and retrieval |
| `tests\test_scheme_onboarding.py` | `onboard` recreates the hand-made IGNOAPS files byte for byte; preview writes nothing; each refusal writes nothing; the load check catches a result the app would refuse |
| `tests\test_scheme_rules.py` | Cases built from packages, headings shown before list items, the `--yes` gate, learn refusing without a split, learn -> review -> freeze -> evaluate end to end with a fake model, full answers for rejections, and `extract` drafts for a new scheme |

Tests use only synthetic development fixtures. A passing mocked test demonstrates
the exercised Python behavior, not real model accuracy or human approval.
The SQLite reopen test reloads the frozen snapshot; it does not independently
assert every underlying proposal/review row after reopening.

If dependencies are missing, install the project's existing dev dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Do this only after a missing-dependency error, not every time.

For a source compile check and broader regression check after Python changes:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m pytest -q -x
```

You do not need to start uvicorn/Streamlit or call OpenRouter to read or test
this implementation. Do not substitute protected held-out files for the fixtures.

## 15. Fixes after the first real-model runs (2026-11-07)

The offline tests passed, but the first runs with a real model
(`openai/gpt-4o-mini` via OpenRouter, on real PM-KISAN and IGNWPS rules)
exposed problems that the synthetic tests could not. Each fix below has
offline tests that replay the real model output.

| # | Problem seen with the real model | Why it happened | Fix | Tests |
|---|---|---|---|---|
| P1 | A **correct** PM-KISAN rule was reported as two errors: `{"PMKISAN-LAND-FAMILY-01": ["missing"], "rule1": ["unexpected"]}` | Rules were compared by ID, and the model never sees the approved IDs (correctly), so it invented `rule1` | Pair rules by meaning `(clause, fact, operator)`; replace the model's ID with `clause:fact:operator` so the same rule has the same ID on every run | `test_correct_rule_with_a_made_up_name_has_no_differences`, `test_the_same_mistake_gets_the_same_ids_and_lesson_identity_every_run` and the other answer-kind tests |
| P2 | The false difference produced a useless lesson ("align with the approved reference rules ... when the rule IDs differ") | Followed from P1 | None needed: fixing P1 removes the false difference, so no reflection call is made | None of its own; covered by the P1 tests |
| P3 | The run crashed: the model's lesson tags included `rule-extraction`, and the hyphen fails `TAG_PATTERN` | The prompt never stated the tag format; the model wrote tags naturally | The model no longer writes tags (`LessonText`); extra fields it adds are dropped | `test_lesson_tags_are_the_case_tags_whatever_the_model_writes`, `test_reflection_prompt_does_not_ask_the_model_for_tags` |
| P4 | Even an approved lesson might never be used | Lesson tags (chosen by the model) and case `topic_tags` (chosen by a person) had no shared list, so they need not match; the earlier tests only matched because the same tag was typed on both sides | Code copies the case's `topic_tags` onto the lesson; a case must have at least one tag | `test_an_approved_lesson_reaches_the_next_case_with_the_same_topic`, `test_case_without_topic_tags_is_rejected` |
| Units | A correct PM-KISAN pension rule would have been rejected, and IGNWPS age rules could never match | The extractor demanded the registry unit on every rule, but the pension fact is yes/no while its question names an amount (registry unit `INR`). IGNWPS age rules had no unit at all; the app's package loader still accepted them through a special exception for old (legacy) packages, but the model correctly writes `years`, so the two could never be equal | Units are checked for number facts only, as in the package loader; IGNWPS age rules now carry `"years"` (reviewer-approved package amendment) | `test_every_approved_clause_passes_extraction_when_the_model_is_right`, `test_wrong_unit_is_rejected` |
| IGNWPS | IGNWPS rules had no clause text or location of their own, unlike PM-KISAN | The two schemes were reviewed three days apart in different formats; IGNWPS kept its single sentence only at package level (`source.official_eligibility_text`) | Reviewer-approved amendment: every IGNWPS rule gained `source_text`, `source_location` ("Eligibility Criteria section") and, for age, `"unit": "years"`. The package hash was re-pinned in `src/rules/bundle_registry.json` and `src/rules/data_provider.py`; recorded in "Amendment 2026-11-07" at the end of `docs/IGNWPS_MH_RULE_REVIEW_2026-10-30.md`. The first edit inserted the fields twice; the app's strict package loader refused the duplicate keys, so it was redone in one pass, keeping the file's exact line endings because the hash covers every byte | `test_every_packaged_rule_carries_its_exact_source_clause` (`tests/test_fact_registry.py`) |
| Lessons | The first real lessons were vague ("Ensure that the eligibility criteria ... is accurately reflected") and named one scheme's groups | The prompt only said "describe a general correction" | `REFLECTION_SYSTEM_PROMPT` now states that rules describe who qualifies and asks for the mistake plus the correct way to write it, when to apply it by wording, and no scheme or group names; its style example is about ranges so it does not give away the answer | `test_reflection_prompt_asks_for_an_actionable_general_lesson` |
| Types | The pension rule was rejected in almost every run; the model wrote `gte 10000` (unit `Rs`) for a yes/no fact | The model was given only fact IDs, so it could not know the fact is yes/no; the shortened validation message hid the answer | The payload now sends each fact's type (unit for number facts, codes for choice facts), never the meaning text (`_fact_shape`); the script prints the model's full answer for rejections | `test_model_is_told_each_allowed_fact_type_but_not_its_meaning`, `test_rejected_answer_report_shows_exactly_what_the_model_wrote` |

**Reviewer decision (Debadyuti Roy, 2026-11-07, Option B).** `if_not_met` and
`missing_field_label` are no longer compared. The IGNWPS BPL rule's "no card
shown means ask for the card" is reviewer policy about evidence, not a
condition in the official sentence, which mentions no card. Comparing it would
reward a model for guessing reviewer judgement and could teach a cross-scheme
lesson that is over-applied where a source intends strict exclusion. Recorded in
the IGNWPS review amendment (`docs/IGNWPS_MH_RULE_REVIEW_2026-10-30.md`) and
tested by `test_reviewer_policy_fields_are_not_compared` and
`test_reviewer_bpl_policy_is_not_expected_from_the_model`.

**Result at that point** (after these fixes, before the PM-KISAN exclusion
clauses were tried), same model, 3 runs per scheme:

| Case | Approved rules | Differences in all 3 runs |
|---|---|---|
| PM-KISAN clause `PMKISAN-GUIDELINES-2020-3` | 1 | none |
| IGNWPS clause `IGNWPS-MH-ELIGIBILITY-01` | 4 (widow, age >= 40 years, age <= 79 years, BPL card) | none |

With no extraction mistakes on these two clauses, no lessons were proposed
at that point. The exclusion clauses tried next did produce mistakes and
lessons; see "First experiment" in "Start here". A demo or check
script must call the package's own functions (`run_reflexion_case`,
`extract_rules`); rebuilding prompts in a script hid P3 and skipped the
validation in section 7.

## 16. What remains before production use?

The current implementation is a library for controlled development, not a fully
integrated production review workflow. Remaining work includes authenticated
review integration, concurrency-safe writes, governed model/token/spend limits,
and a larger before/after sample than 3 runs per clause. See "Known open issues" in "Start here".

Approving a lesson approves extractor guidance only. It never approves or
activates a government rule package. Human policy review remains separate.

For your first code-reading pass, follow:

```text
run_reflexion_case
  -> extract_rules
     -> invoke_structured_output
     -> _validate_extracted_rules
  -> compare_rules
  -> propose_lesson (only on mismatch)
  -> save_pending_lesson
```

Then read review, freezing and evaluation as separate paths.
