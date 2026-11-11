"""Deterministic eligibility engine shared by every synthetic mock scheme."""

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.rules.facts import FactRegistry, FactState, HouseholdProfile
from src.rules.models import Rule, RulePackage
from src.ui.models import StrictModel


class RuleEvidence(StrictModel):
    """Source citation for a rule used in the response."""

    rule_id: str
    source_clause_id: str
    source_url: str
    source_text: str
    source_location: str | None = None


class EligibilityResponse(StrictModel):
    """Deterministic mock result with reasons and source evidence."""

    scheme_id: str
    result: Literal["eligible", "not_eligible", "need_more_information"]
    reason: str
    age_on_application_date: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    deciding_rule_ids: list[str]
    evidence: list[RuleEvidence]
    notice: str | None = None
    unresolved_checks: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _default_registry() -> FactRegistry:
    """Load the packaged registry for legacy in-process evaluator callers."""

    path = Path(__file__).parents[1] / "rules" / "fact_registry.json"
    return FactRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))



def _rule_is_met(rule: Rule, value: object, registry: FactRegistry) -> bool:
    """Compare one known value using its registered type and supported operator."""

    definition = registry.get(rule.field)
    expected = definition.validate_value(rule.value)
    if rule.operator == "eq":
        return value == expected
    if rule.operator == "gt":
        return value > expected  # type: ignore[operator]
    if rule.operator == "gte":
        return value >= expected  # type: ignore[operator]
    if rule.operator == "lt":
        return value < expected  # type: ignore[operator]
    return value <= expected  # type: ignore[operator]


def evaluate_mock_eligibility(
    profile: HouseholdProfile,
    package: RulePackage,
    registry: FactRegistry | None = None,
) -> EligibilityResponse:
    """Evaluate every rule through the same registry-validated fact store.

    Verdict order: any failed rule gives ``not_eligible``; otherwise any
    unknown fact (or a rule marked ``need_more_information``) gives
    ``need_more_information``; otherwise ``eligible``.

    """

    active_registry = registry or _default_registry()
    store = profile.validate_against(active_registry)
    # Every rule ends up in one of three groups:
    #   passed     -> not stored; nothing to report
    #   failed     -> the person clearly does not qualify
    #   unresolved -> we cannot decide yet (unknown fact, or proof needed)
    failed_rules: list[Rule] = []
    unresolved_rules: list[Rule] = []
    # Names of facts or documents still needed, shown to the user.
    missing_fields: list[str] = []

    def add_missing(labels: list[str]) -> None:
        """Add labels to missing_fields once each, keeping their order."""

        for label in labels:
            if label not in missing_fields:
                missing_fields.append(label)

    # Step 1: check every rule and sort it into a group.
    for rule in package.rules:
        value = store.value(rule.field, active_registry)

        if value is None:
            # Case A: the fact is unknown, so we cannot check this rule yet.
            unresolved_rules.append(rule)
            # Report what to ask for. Use the rule's label if it has one;
            # otherwise list the raw facts that are still unknown. For age,
            # that is date_of_birth and/or application_date, not "age".
            add_missing(
                [rule.missing_field_label]
                if rule.missing_field_label
                else [
                    fact
                    for fact in store.missing_inputs(rule.field, active_registry)
                ]
            )
        elif not _rule_is_met(rule, value, active_registry):
            # Case B: the fact is known and the rule is not met.
            if rule.if_not_met == "not_eligible":
                # Normal rule: a "no" means the person does not qualify.
                failed_rules.append(rule)
            else:
                # Proof rule (e.g. BPL card not shown): ask for evidence
                # instead of rejecting the person.
                unresolved_rules.append(rule)
                add_missing([rule.missing_field_label or rule.field])
        # Case C: the fact is known and the rule is met -> passed.

    # Step 2: choose the verdict. The order matters.
    if failed_rules:
        # Any failed rule wins. More answers cannot change the outcome,
        # so clear the missing list to avoid asking pointless questions.
        result: Literal[
            "eligible", "not_eligible", "need_more_information"
        ] = "not_eligible"
        deciding_rules = failed_rules
        missing_fields = []
    elif unresolved_rules:
        # Nothing failed, but something is unknown or needs proof.
        result = "need_more_information"
        deciding_rules = unresolved_rules
    else:
        # Every rule passed, so every rule supports the verdict.
        result = "eligible"
        deciding_rules = list(package.rules)

    # Step 3: build the response, with source evidence for each deciding rule.
    return EligibilityResponse(
        scheme_id=package.scheme_id,
        result=result,
        # Read the reason text for this verdict from the package,
        # e.g. package.reasons.not_eligible.
        reason=getattr(package.reasons, result),
        age_on_application_date=(
            store.value("age", active_registry)
            if any(
                definition.fact_id == "age"
                for definition in active_registry.definitions
            )
            else None
        ),
        missing_fields=missing_fields,
        deciding_rule_ids=[rule.rule_id for rule in deciding_rules],
        evidence=[
            RuleEvidence(
                rule_id=rule.rule_id,
                source_clause_id=rule.source_clause_id,
                source_url=str(package.source.source_url),
                # Prefer the rule's own clause text; fall back to the
                # package's general eligibility text.
                source_text=(
                    rule.source_text
                    or package.source.official_eligibility_text
                ),
                source_location=rule.source_location,
            )
            for rule in deciding_rules
        ],
        notice=package.notice,
        unresolved_checks=list(package.unresolved_checks),
    )
