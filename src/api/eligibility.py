"""Deterministic eligibility engine shared by every synthetic mock scheme."""

from typing import Literal

from pydantic import Field

from src.rules.models import HouseholdProfile, Rule, RulePackage
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


def _rule_is_met(rule: Rule, value: bool | int) -> bool:
    if rule.operator == "eq":
        return value == rule.value
    if rule.operator == "gte":
        return value >= rule.value
    return value <= rule.value


def evaluate_mock_eligibility(
    profile: HouseholdProfile,
    package: RulePackage,
) -> EligibilityResponse:
    """Evaluate every rule in a package without an LLM.

    Verdict order: any failed rule gives ``not_eligible``; otherwise any
    unknown fact (or a rule marked ``need_more_information``) gives
    ``need_more_information``; otherwise ``eligible``.
    """

    failed_rules: list[Rule] = []
    unresolved_rules: list[Rule] = []
    missing_fields: list[str] = []

    def add_missing(labels: list[str]) -> None:
        for label in labels:
            if label not in missing_fields:
                missing_fields.append(label)

    for rule in package.rules:
        value = profile.fact_value(rule.field)
        if value is None:
            unresolved_rules.append(rule)
            add_missing(
                [rule.missing_field_label]
                if rule.missing_field_label
                else [
                    fact
                    for fact in rule.input_facts
                    if profile.fact_value(fact) is None
                ]
            )
        elif not _rule_is_met(rule, value):
            if rule.if_not_met == "not_eligible":
                failed_rules.append(rule)
            else:
                unresolved_rules.append(rule)
                add_missing([rule.missing_field_label or rule.field])

    if failed_rules:
        result: Literal[
            "eligible", "not_eligible", "need_more_information"
        ] = "not_eligible"
        deciding_rules = failed_rules
        missing_fields = []
    elif unresolved_rules:
        result = "need_more_information"
        deciding_rules = unresolved_rules
    else:
        result = "eligible"
        deciding_rules = list(package.rules)

    return EligibilityResponse(
        scheme_id=package.scheme_id,
        result=result,
        reason=getattr(package.reasons, result),
        age_on_application_date=profile.age,
        missing_fields=missing_fields,
        deciding_rule_ids=[rule.rule_id for rule in deciding_rules],
        evidence=[
            RuleEvidence(
                rule_id=rule.rule_id,
                source_clause_id=rule.source_clause_id,
                source_url=str(package.source.source_url),
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
