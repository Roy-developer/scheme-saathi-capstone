# APY-IN fact intake review

> **Draft only. The APY facts remain approved for gold evaluation only.
> This review does not approve applicant intake, localization, privacy, or
> production use.**

## Review identity

- Scheme: Atal Pension Yojana (`APY-IN`)
- Review date: 2026-11-11
- Eligibility evidence review: `docs/APY-IN_RULE_REVIEW_2026-11-11.md`
- Candidate definitions: `data/schemes/rule_gold_fact_review_queue.json`
- App fact registry: `src/rules/fact_registry.json`
- Scope: the three APY-scoped app facts derived from the gold-only candidate
  meanings
- Overall status: `active_synthetic_mock_only`; privacy and question review pending

The generic candidate meanings and questions remain in the gold-review queue.
APY-specific definitions have been added to the active registry with approved
meanings and pending question/privacy review. Roy-developer authorized their
use in a synthetic mock bundle while those reviews remain pending; this does
not approve real applicant intake.

## Candidate-by-candidate review

| Candidate fact | Source-backed scope | Existing candidate questions (EN / HI / MR) | Intake/privacy assessment | Recommendation |
|---|---|---|---|---|
| `apy_is_citizen_of_india` | Boolean about the applicant as a person. APY's source requires a citizen of India. | “Are you a citizen of India?” / “क्या आप भारत के नागरिक हैं?” / “तुम्ही भारताचे नागरिक आहात का?” | The app definition is marked sensitive, while privacy approval remains pending. Do not request identity-document numbers or proof of citizenship for this Boolean check. | Keep only if the question is necessary for APY. Have a native speaker and privacy reviewer confirm all three versions. Keep unknown/refused distinct from “no.” |
| `apy_has_savings_bank_account` | Boolean about whether the applicant has the APY-required savings bank account. | “Do you have a savings bank account?” / “क्या आपका बचत बैंक खाता है?” / “तुमचे बचत बँक खाते आहे का?” | Marked sensitive. The yes/no answer is narrower than collecting an account number, bank name, statement, or proof. Its meaning must not be generalized to schemes with different account conditions. | Retain the APY-specific meaning. Do not collect account identifiers or documents for eligibility screening. Native-speaker review is pending. |
| `apy_is_or_has_been_income_tax_payer` | Boolean for the APY-specific “is or has been” income-tax-payer exclusion, scoped to the applicant and APY joining rule. | “Are you, or have you ever been, an income tax payer?” / “क्या आप आयकर दाता हैं, या कभी रहे हैं?” / “तुम्ही आयकर भरता का, किंवा कधी भरत होता का?” | Marked sensitive. “Ever” must not be reduced to the last assessment year, and “income-tax payer” should not accidentally be interpreted as merely having filed a return. It is APY-specific to avoid mixing schemes with different lookbacks. | Keep the APY-scoped fact. Have a policy reviewer and native speakers validate the meaning before real use. Do not request PAN, return copies, tax identifiers, or income documents for this Boolean screening question. |

## Required intake safeguards

- Collect only the minimum yes/no answers needed for APY joining eligibility.
- Keep “unknown” or declined answers distinct from `false`; an unanswered
  sensitive question must not silently become an exclusion.
- Do not collect or log account numbers, PAN, tax-return details, bank names,
  or identity-document numbers for these Boolean checks.
- Limit these answers to the APY purpose. Do not reuse the tax answer for
  schemes whose lookback differs.
- For APY structured intake, initial free-text descriptions are skipped when
  required facts are sensitive, and invalid answers to sensitive questions are
  not sent to the answer interpreter or echoed. Broader data-flow, storage,
  retention, and general search-query review remains pending.
- Define and approve the privacy purpose, consent language, retention period,
  deletion behavior, and sensitivity classification for each fact.
- Obtain human policy review and native-speaker review of the English, Hindi,
  and Marathi questions. The candidate translations are not approved.

## Disposition

**Active for synthetic mock use only**, as explicitly authorized by
Roy-developer on 2026-11-11. The package uses APY-scoped facts; the exact
questions and privacy metadata remain pending. Do not enter real applicant
data. Native-speaker, privacy-purpose/retention, and broader data-flow reviews
are required before any real applicant intake or production use.

## Human review

- APY policy/domain reviewer: Roy-developer (user-provided; role entered as “assumed role1”)
- Privacy reviewer: pending
- Hindi/Marathi native-speaker review: pending
- Technical data-flow review: pending, with APY structured-answer safeguards implemented and focused tests passing
- Date and decisions: mock-only activation authorized 2026-11-11; other reviews pending
