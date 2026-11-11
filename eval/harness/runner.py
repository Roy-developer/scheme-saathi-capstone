"""Code-first eligibility evaluation over development personas."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from eval.schema import EvalPersona, PersonaEvaluationSet, profile_from_mapping
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactRegistry, FactState, HouseholdProfile
from src.rules.models import RulePackage


def load_persona_evaluation_set(
    path: Path,
    *,
    allow_held_out: bool = False,
) -> PersonaEvaluationSet:
    """Load and validate a persona set.

    By default only unprotected development sets are accepted. Role-5-only
    held-out scoring passes ``allow_held_out=True`` from a controlled script.
    """

    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        evaluation_set = PersonaEvaluationSet.model_validate(data)
    except ValidationError as error:
        raise ValueError(f"Invalid persona evaluation set: {error}") from error

    if evaluation_set.split == "held_out" or evaluation_set.protected:
        if not allow_held_out:
            raise ValueError(
                "This in-repo harness only accepts unprotected development persona "
                "sets by default. Held-out cases must stay outside the application "
                "image; use scripts/evaluate_eligibility_held_out.py from a "
                "Role-5-only environment."
            )
        if evaluation_set.split != "held_out" or not evaluation_set.protected:
            raise ValueError(
                "Held-out sets must have split='held_out' and protected=true."
            )
    elif evaluation_set.split != "development" or evaluation_set.protected:
        raise ValueError(
            "Development sets must have split='development' and protected=false."
        )
    return evaluation_set


def _packages_by_id(
    provider: RulePackageProvider | None = None,
) -> dict[str, RulePackage]:
    active = provider or RulePackageProvider()
    return dict(active.packages)


def _coerce_fact_value(fact_id: str, value: object) -> object:
    """Coerce JSON values into registry-friendly Python types."""

    if fact_id in {"date_of_birth", "application_date"} and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def typed_fact_store(
    typed_facts: Mapping[str, Any],
    registry: FactRegistry,
) -> HouseholdProfile:
    """Build a registry fact store; JSON null means unknown."""

    facts: dict[str, FactState] = {}
    for fact_id, value in typed_facts.items():
        definition = registry.get(fact_id)
        if value is None:
            facts[fact_id] = FactState(
                status="unknown",
                definition_version=definition.version,
            )
        else:
            facts[fact_id] = FactState(
                status="known",
                value=_coerce_fact_value(fact_id, value),
                definition_version=definition.version,
                provenance="user_reported",
            )
    return HouseholdProfile(
        registry_version=registry.registry_version,
        facts=facts,
    ).validate_against(registry)


def persona_input(
    persona: EvalPersona,
    registry: FactRegistry,
) -> HouseholdProfile:
    """Build validated registered facts from the persona's input mapping."""

    if persona.typed_facts is not None:
        return typed_fact_store(persona.typed_facts, registry)
    if persona.profile is None:
        raise ValueError(f"Persona {persona.persona_id!r} has no profile")
    return profile_from_mapping(persona.profile, registry)


def evaluate_persona_set(
    evaluation_set: PersonaEvaluationSet,
    packages: Mapping[str, RulePackage] | None = None,
    *,
    scheme_ids: set[str] | None = None,
    provider: RulePackageProvider | None = None,
) -> dict[str, Any]:
    """Score each persona against expected verdicts using the rule engine."""

    active_provider = provider or RulePackageProvider()
    active_packages = (
        dict(packages) if packages is not None else dict(active_provider.packages)
    )
    registry = active_provider.registry
    per_persona: list[dict[str, Any]] = []
    correct = 0
    total = 0
    by_scheme: dict[str, Counter[str]] = defaultdict(Counter)
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    missing_field_mismatches = 0

    for persona in evaluation_set.personas:
        persona_detail: dict[str, Any] = {
            "persona_id": persona.persona_id,
            "boundary_family": persona.boundary_family,
            "schemes": {},
        }
        facts = persona_input(persona, registry)
        for scheme_id, expected in persona.expected_by_scheme.items():
            if scheme_ids is not None and scheme_id not in scheme_ids:
                continue
            package = active_packages.get(scheme_id)
            if package is None:
                persona_detail["schemes"][scheme_id] = {
                    "status": "error",
                    "error": f"Unknown scheme package {scheme_id!r}",
                }
                continue

            actual = evaluate_mock_eligibility(
                facts, package, registry=registry,
            )
            total += 1
            result_match = actual.result == expected.result
            expected_missing = list(expected.missing_fields)
            actual_missing = list(actual.missing_fields)
            missing_match = sorted(actual_missing) == sorted(expected_missing)
            if not missing_match:
                missing_field_mismatches += 1

            rules_match: bool | None = None
            if expected.deciding_rule_ids is not None:
                rules_match = (
                    list(actual.deciding_rule_ids) == list(expected.deciding_rule_ids)
                )

            case_ok = result_match and missing_match and (
                rules_match is None or rules_match
            )
            if case_ok:
                correct += 1
                by_scheme[scheme_id]["correct"] += 1
            else:
                by_scheme[scheme_id]["incorrect"] += 1
            by_scheme[scheme_id]["total"] += 1
            confusion[scheme_id][f"{expected.result}->{actual.result}"] += 1

            persona_detail["schemes"][scheme_id] = {
                "status": "pass" if case_ok else "fail",
                "expected_result": expected.result,
                "actual_result": actual.result,
                "result_match": result_match,
                "expected_missing_fields": expected_missing,
                "actual_missing_fields": actual_missing,
                "missing_fields_match": missing_match,
                "expected_deciding_rule_ids": (
                    list(expected.deciding_rule_ids)
                    if expected.deciding_rule_ids is not None
                    else None
                ),
                "actual_deciding_rule_ids": list(actual.deciding_rule_ids),
                "deciding_rules_match": rules_match,
            }
        per_persona.append(persona_detail)

    accuracy = (correct / total) if total else 0.0
    return {
        "dataset_version": evaluation_set.dataset_version,
        "split": evaluation_set.split,
        "protected": evaluation_set.protected,
        "persona_count": len(evaluation_set.personas),
        "case_count": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": round(accuracy, 4),
        "missing_field_mismatches": missing_field_mismatches,
        "by_scheme": {
            scheme_id: {
                "total": counts["total"],
                "correct": counts["correct"],
                "incorrect": counts["incorrect"],
                "accuracy": round(
                    counts["correct"] / counts["total"], 4
                )
                if counts["total"]
                else 0.0,
                "confusion": dict(confusion[scheme_id]),
            }
            for scheme_id, counts in sorted(by_scheme.items())
        },
        "per_persona": per_persona,
    }


def write_report(report: Mapping[str, Any], output_path: Path) -> None:
    """Write a JSON evaluation report."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
