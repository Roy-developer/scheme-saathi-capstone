"""Synthetic PM-KISAN eligibility checks against a versioned rule package."""

import json
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.ui.models import StrictModel


PMKISAN_GUIDELINES_URL = (
    "https://pmkisan.gov.in/Documents/"
    "RevisedPM-KISANOperationalGuidelines(English).pdf"
)


class PMKisanEligibilityRequest(StrictModel):
    """Optional family-level answers; unknown facts stay explicitly unknown."""

    landholding_family_in_state_records: bool | None = None
    institutional_landholder: bool | None = None
    listed_public_office_member: bool | None = None
    excluded_government_employee_member: bool | None = None
    pension_at_least_10000_excluding_stated_grades: bool | None = None
    income_tax_paid_last_assessment_year: bool | None = None
    registered_practicing_professional_member: bool | None = None
    nri_new_beneficiary: bool | None = None


class PMKisanEligibilityEvidence(StrictModel):
    """A dated source location for a potential criterion or exclusion."""

    rule_id: str
    source_url: str = PMKISAN_GUIDELINES_URL
    source_location: str
    source_text: str


class PMKisanEligibilityResponse(StrictModel):
    """Mock result with explicit limits and rule evidence."""

    scheme_id: Literal["PM-KISAN-IN"] = "PM-KISAN-IN"
    result: Literal[
        "eligible",
        "not_eligible",
        "need_more_information",
    ]
    reason: str
    missing_fields: list[str] = Field(default_factory=list)
    deciding_rule_ids: list[str] = Field(default_factory=list)
    evidence: list[PMKisanEligibilityEvidence] = Field(default_factory=list)
    unresolved_checks: list[str] = Field(
        default_factory=lambda: [
            "Current landholding cutoff and subsequent-transfer rules",
            "State/UT verification of land records and family eligibility",
        ]
    )
    notice: str = (
        "This mock result uses PM-KISAN guidelines revised 2020-03-29. "
        "It is not a government decision; current cutoff rules and State/UT "
        "records are not verified."
    )


class PMKisanRule(StrictModel):
    """One typed test in the PM-KISAN package."""

    rule_id: str
    field: Literal[
        "landholding_family_in_state_records",
        "institutional_landholder",
        "listed_public_office_member",
        "excluded_government_employee_member",
        "pension_at_least_10000_excluding_stated_grades",
        "income_tax_paid_last_assessment_year",
        "registered_practicing_professional_member",
        "nri_new_beneficiary",
    ]
    operator: Literal["requires_true", "excludes_true"]
    source_location: str
    source_text: str


class PMKisanRulePackage(StrictModel):
    """Versioned, mock-only rules kept separate from widow-pension rules."""

    model_config = ConfigDict(frozen=True)

    package_version: str
    scheme_id: Literal["PM-KISAN-IN"]
    approval_scope: Literal["synthetic_mock_only"]
    source_url: str
    revised_as_of: str
    rules: tuple[PMKisanRule, ...] = Field(min_length=8)


def load_pmkisan_rule_package() -> PMKisanRulePackage:
    """Load and validate the PM-KISAN-specific rules from package data."""

    package_text = (
        resources.files("src.rules")
        .joinpath("pmkisan", "pmkisan_in.v1.json")
        .read_text(encoding="utf-8")
    )
    return PMKisanRulePackage.model_validate(json.loads(package_text))


def evaluate_pmkisan_eligibility(
    request: PMKisanEligibilityRequest,
) -> PMKisanEligibilityResponse:
    """Evaluate every package rule, preserving unknowns and evidence."""

    package = load_pmkisan_rule_package()
    failed_rules: list[PMKisanRule] = []
    missing_fields: list[str] = []

    for rule in package.rules:
        answer = getattr(request, rule.field)
        if answer is None:
            missing_fields.append(rule.field)
        elif (
            rule.operator == "requires_true"
            and answer is not True
        ) or (
            rule.operator == "excludes_true"
            and answer is True
        ):
            failed_rules.append(rule)

    if failed_rules:
        result = "not_eligible"
        reason = (
            "One or more reported facts do not meet the PM-KISAN mock "
            "criteria in the 2020 guidelines."
        )
        deciding_rules = failed_rules
        missing_fields = []
    elif missing_fields:
        result = "need_more_information"
        reason = (
            "Answer the missing questions before this mock check can continue."
        )
        deciding_rules = [
            rule for rule in package.rules if rule.field in missing_fields
        ]
    else:
        result = "eligible"
        reason = (
            "The supplied answers meet the PM-KISAN mock criteria in the "
            "2020 guidelines. Current cutoff rules and official records "
            "have not been checked."
        )
        deciding_rules = list(package.rules)

    return PMKisanEligibilityResponse(
        result=result,
        reason=reason,
        missing_fields=missing_fields,
        deciding_rule_ids=[rule.rule_id for rule in deciding_rules],
        evidence=[
            PMKisanEligibilityEvidence(
                rule_id=rule.rule_id,
                source_location=rule.source_location,
                source_text=rule.source_text,
                source_url=package.source_url,
            )
            for rule in deciding_rules
        ],
    )
