"""Code-only interview simulation: question count and en/hi/mr verdict parity.

A persona's typed facts act as the hidden profile card. The simulated citizen
replies in the chosen language using the same words the real parser accepts,
and each reply is parsed by the production ``parse_registered_answer``.
No model is called, so runs are free and repeatable.

Strategies:
    planned - production ``pick_next_registered_fact``: ask only about an
              input needed by a still-undecided rule, stop once settled.
    fixed   - ask every required fact in package order (the questionnaire
              baseline for E4), stop only when all are answered.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from eval.harness.runner import persona_input
from eval.schema import PersonaEvaluationSet
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactState, HouseholdProfile
from src.workflow.question_picker import pick_next_registered_fact
from src.workflow.questions import (
    LOCALIZED_NO_WORDS, LOCALIZED_UNKNOWN_WORDS, LOCALIZED_YES_WORDS,
    parse_registered_answer,
)

LOCALES = ("en", "hi", "mr")
STRATEGIES = ("planned", "fixed")


def _reply(definition: Any, state: FactState | None, locale: str) -> str:
    """Write the citizen's reply in ``locale`` from the hidden card."""

    if state is None or state.status != "known":
        words = LOCALIZED_UNKNOWN_WORDS.get(locale)
        return sorted(words)[0] if words else "don't know"
    value = state.value
    if definition.value_type == "boolean":
        words = (LOCALIZED_YES_WORDS if value else LOCALIZED_NO_WORDS).get(locale)
        return sorted(words)[0] if words else ("yes" if value else "no")
    if definition.value_type == "date":
        return value.isoformat()
    if definition.value_type == "choice":
        return definition.choice_labels.get(locale, {}).get(value, str(value))
    return str(value)


def interview(persona, package, provider, locale: str, strategy: str) -> dict[str, Any]:
    """Run one simulated conversation and return its code-decided outcome."""

    registry = provider.registry
    card = persona_input(persona, registry)
    store = HouseholdProfile(registry_version=registry.registry_version, facts={})
    skipped: set[str] = set()
    asked: list[str] = []
    fixed_queue = list(package.required_facts)
    while True:
        if strategy == "planned":
            fact_id = pick_next_registered_fact(
                store, package, registry, frozenset(skipped),
            )
        else:
            fact_id = next((f for f in fixed_queue if f not in asked), None)
        if fact_id is None or fact_id in asked:
            break
        asked.append(fact_id)
        definition = registry.get(fact_id)
        parsed = parse_registered_answer(
            definition, _reply(definition, card.facts.get(fact_id), locale), locale,
        )
        if parsed.kind == "value":
            store.facts[fact_id] = FactState(
                status="known", value=parsed.value,
                definition_version=definition.version, provenance="user_reported",
            )
        else:
            skipped.add(fact_id)
            store.facts[fact_id] = FactState(
                status="unknown", definition_version=definition.version,
            )
    verdict = evaluate_mock_eligibility(store, package, registry=registry)
    return {
        "result": verdict.result, "questions": len(asked),
        "missing_fields": sorted(verdict.missing_fields),
    }


def run_interview_ablation(
    evaluation_set: PersonaEvaluationSet,
    provider: RulePackageProvider | None = None,
) -> dict[str, Any]:
    """Measure questions per conversation and cross-language verdict parity."""

    provider = provider or RulePackageProvider()
    cases: list[dict[str, Any]] = []
    totals: dict[str, list[int]] = defaultdict(list)
    parity_breaks = 0
    wrong_vs_expected = 0
    for persona in evaluation_set.personas:
        for scheme_id, expected in persona.expected_by_scheme.items():
            package = provider.packages.get(scheme_id)
            if package is None:
                continue
            row: dict[str, Any] = {
                "persona_id": persona.persona_id, "scheme_id": scheme_id,
                "expected": expected.result, "runs": {},
            }
            for strategy in STRATEGIES:
                results = {
                    loc: interview(persona, package, provider, loc, strategy)
                    for loc in LOCALES
                }
                verdicts = {loc: r["result"] for loc, r in results.items()}
                counts = {loc: r["questions"] for loc, r in results.items()}
                parity = len(set(verdicts.values())) == 1 and len(
                    {tuple(r["missing_fields"]) for r in results.values()}) == 1
                if not parity:
                    parity_breaks += 1
                if verdicts["en"] != expected.result:
                    wrong_vs_expected += 1
                totals[strategy].append(counts["en"])
                row["runs"][strategy] = {
                    "verdicts": verdicts, "questions": counts, "parity": parity,
                }
            cases.append(row)
    n = len(cases)
    return {
        "dataset_version": evaluation_set.dataset_version,
        "split": evaluation_set.split,
        "case_count": n,
        "parity_breaks": parity_breaks,
        "verdicts_differing_from_expected": wrong_vs_expected,
        "mean_questions": {
            s: (sum(v) / len(v) if v else 0.0) for s, v in totals.items()
        },
        "cases": cases,
    }
