"""Deterministic evaluation for the reviewed synthetic mock scheme."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from src.rules.models import RulePackage
from src.ui.models import StrictModel, calculate_age_on


class EligibilityRequest(StrictModel):
    """Synthetic facts required to evaluate one mock application."""

    date_of_birth: date
    application_date: date
    is_widow: bool
    bpl_card_shown: bool | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "EligibilityRequest":
        if self.date_of_birth > self.application_date:
            raise ValueError("date_of_birth cannot be after application_date")
        if calculate_age_on(self.date_of_birth, self.application_date) > 125:
            raise ValueError("age on application_date cannot exceed 125")
        return self

    @property
    def age(self) -> int:
        """Return completed age on the application date."""

        return calculate_age_on(self.date_of_birth, self.application_date)


class RuleEvidence(StrictModel):
    """Source citation for a rule used in the response."""

    rule_id: str
    source_clause_id: str
    source_url: str
    source_text: str


class EligibilityResponse(StrictModel):
    """Deterministic mock result with reasons and source evidence."""

    scheme_id: str
    result: Literal["eligible", "not_eligible", "need_more_information"]
    reason: str
    age_on_application_date: int
    missing_fields: list[str] = Field(default_factory=list)
    deciding_rule_ids: list[str]
    evidence: list[RuleEvidence]


def evaluate_mock_eligibility(
    request: EligibilityRequest,
    package: RulePackage,
) -> EligibilityResponse:
    """Evaluate a preloaded rule package without an LLM or external submission."""

    rules = package.rules
    evidence_by_rule = {
        rule.rule_id: RuleEvidence(
            rule_id=rule.rule_id,
            source_clause_id=rule.source_clause_id,
            source_url=str(package.source.source_url),
            source_text=package.source.official_eligibility_text,
        )
        for rule in rules
    }

    failed_rules: list[str] = []
    missing_fields: list[str] = []
    deciding_rule_ids: list[str] = []

    for rule in rules:
        if rule.field == "is_widow":
            if rule.operator != "eq" or not isinstance(rule.value, bool):
                raise ValueError(f"Unsupported widow rule: {rule.rule_id}")
            if request.is_widow != rule.value:
                failed_rules.append(rule.rule_id)
        elif rule.field == "age":
            if not isinstance(rule.value, int) or isinstance(rule.value, bool):
                raise ValueError(f"Unsupported age rule: {rule.rule_id}")
            if rule.operator == "gte":
                failed = request.age < rule.value
            elif rule.operator == "lte":
                failed = request.age > rule.value
            else:
                raise ValueError(f"Unsupported age operator: {rule.rule_id}")
            if failed:
                failed_rules.append(rule.rule_id)
        elif rule.field == "bpl_status":
            if (
                rule.operator != "eq"
                or rule.value != "confirmed"
                or package.bpl_confirmation
                != "government_bpl_card_shown"
            ):
                raise ValueError(f"Unsupported BPL rule: {rule.rule_id}")
            if request.bpl_card_shown is not True:
                missing_fields.append("government_bpl_card")
                deciding_rule_ids.append(rule.rule_id)
        else:
            raise ValueError(f"Unsupported rule field: {rule.field}")

    if failed_rules:
        result: Literal[
            "eligible", "not_eligible", "need_more_information"
        ] = "not_eligible"
        reason = "One or more required mock scheme conditions are not met."
        deciding_rule_ids = failed_rules
        missing_fields = []
    elif missing_fields:
        result = "need_more_information"
        reason = "Show a government BPL card to confirm BPL status for this mock."
    else:
        result = "eligible"
        reason = (
            "All reviewed mock conditions are met, including the age "
            "range on the application date and a government BPL card shown."
        )
        deciding_rule_ids = [rule.rule_id for rule in rules]

    return EligibilityResponse(
        scheme_id=package.scheme_id,
        result=result,
        reason=reason,
        age_on_application_date=request.age,
        missing_fields=missing_fields,
        deciding_rule_ids=deciding_rule_ids,
        evidence=[evidence_by_rule[rule_id] for rule_id in deciding_rule_ids],
    )
