# Scheme ingestion: from source to a live rule package

This describes how a new welfare scheme becomes a rule package the app loads.
It reflects the code as of 2026-11-12. The app's loader is
`src/rules/data_provider.py`; the onboarding tool is
`src/rule_extraction_reflexion/onboarding.py`.

Eligibility is decided only by the deterministic rule engine. The LLM may help
draft rules, but a draft is never approved or used at runtime.

## Where things live

| Item | Location |
|---|---|
| Source and clauses (with search passages) | `data/schemes/rule_extraction_sources/<scheme>.json` |
| Staged package (not loaded by the app) | `data/schemes/reflexion_packages/<scheme>.v*.json` |
| Live package (loaded at startup) | `src/rules/packages/<scheme>.v<N>.json` |
| Bundle manifest | `src/rules/bundle_registry.json` |
| Fact registry | `src/rules/fact_registry.json` |
| Search passages | `data/schemes/passages/<scheme>_passages.json` |
| Reflexion test cases | `data/schemes/rule_extraction_cases_dev.json` |
| Human review reports | `docs/<SCHEME>_RULE_REVIEW_<YYYY-MM-DD>.md` |

## Steps

1. **Write the source file.** Create `rule_extraction_sources/<scheme>.json`
   with the official clause text, the approved rules and their
   `source_clause_id`s, the test cases, and an `onboarding` block containing
   search passages. The package's official text must match the source text, or
   onboarding refuses.

2. **Register any new facts first.** Every fact the case file lists must exist in
   `src/rules/fact_registry.json`, or `extract` stops with a `KeyError`.
   If you change an existing fact's definition, bump `registry_version` and
   update every bundle's `registry_version` first. The planner refuses
   onboarding when definitions change under an unchanged version, using
   `src/rules/fact_registry_snapshot.json`. Add each
   fact with its question text in English, Hindi and Marathi, its privacy policy,
   and its review fields. Mark reviews `pending` until they are done.

3. **Draft the rules (uses the free key, `OPENROUTER_API_KEY_FREE` in `.env`).** Run
   `python -m src.rule_extraction_reflexion.scheme_rules extract <source> --playbook <version> --yes`.
   Drafts are staged in `reflexion_packages/`. Quotes that aren't found in the
   passage are dropped. Drafts are not approved by this step.

4. **Human review of the rules.** Check each rule against the official source
   using the `review-scheme-evidence` skill, which writes a report from
   `REVIEW_TEMPLATE.md`. The report stays `human_decision: pending` until a named
   domain reviewer signs off. A model's `supported` result is not approval.

5. **Write the rule package.** Each rule needs a registered field, a compatible
   operator and value, the correct unit, and a `source_clause_id`. The loader
   checks these in `_validate_rule` (`src/rules/data_provider.py`).

6. **Dry-run the onboarding (free).** Run
   `python -m src.rule_extraction_reflexion.scheme_rules onboard <SCHEME-ID>`
   without `--yes`. The planner refuses if:
   - the scheme is already in the bundle registry;
   - the staged package's `approval_status` is not `approved_for_mock_portal`;
   - the staged package or its source file is missing;
   - the official text doesn't match the source;
   - the onboarding block or its passages are missing;
   - a live package with the same file name already exists.

   Otherwise it builds the bundle entry, the passages file and the case updates.
   It cites the scheme's source on its facts and re-pins the registry hash
   across all bundles. It then runs the real loader on a temporary copy with
   those changes, and writes nothing if that fails.

7. **Apply the onboarding.** Run the same command with `--yes`. This moves the
   package into `src/rules/packages/`, adds the bundle as `approved`, writes the
   passages file, updates the Reflexion cases, and updates the registry hash.

8. **Complete the follow-ups the planner lists.** These are not automatic:
   - Add `data/schemes/document_checklists/<scheme>.json` and
     `data/schemes/mock_forms/<scheme>.json`.
   - Review passages still marked `pending_review`.
   - Get native-speaker review of questions and privacy review of each fact.
   - Re-check search thresholds, since passages changed (paid).
   - Walk through eligible, not-eligible and don't-know cases in the running app.

9. **Add tests.** Each new package needs tests for `eligible`,
   `not_eligible` and `need_more_information`.

10. **Run the checks.** Run `compileall -q src` and `pytest -q` locally, without
   real network or LLM calls. Then run the `validate-scheme-saathi` skill, which
   runs the checks in GitHub Actions on the exact pushed commit.

11. **Record and deploy.** Add a row to `docs/CONTRIBUTIONS.md`. Deploy only when
    asked, using the `deploy-scheme-saathi` skill with `-DryRun` first.

## Rules to keep

- Don't change `src/rules/packages/*.json` or passage review statuses without
  source evidence and human sign-off (AGENTS.md).
- Never read `data/heldout/`, and don't tune code against held-out cases.
- Use synthetic personas only.
- `extract` and `evaluate` make paid model calls. `onboard` does not.

## Open question

`data/schemes/rule_drafts/*.v0.1.0-draft.json` appears to be the older,
pre-Reflexion path. Check whether anything still uses it before following it.
