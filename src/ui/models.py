"""Define strict contracts for policy evidence and synthetic demonstrations."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    """Reject undeclared fields in fixture data instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid")


class LocalizedText(StrictModel):
    """Store equivalent interface text in the supported locales."""

    en: str
    hi: str
    mr: str


class PolicySource(StrictModel):
    """Record provenance and collection details for an official policy source."""

    publisher: str
    source_url: HttpUrl
    collected_at: date
    official_eligibility_text: str
    publication_date_status: Literal["verified", "not_confirmed"]


class PolicyRule(StrictModel):
    """Represent one normalized rule traced to a source clause."""

    rule_id: str
    field: Literal["is_widow", "age", "bpl_status"]
    operator: Literal["eq", "gte", "lte"]
    value: bool | int | str
    source_clause_id: str


def calculate_age_on(date_of_birth: date, as_of_date: date) -> int:
    """Return completed years on a date; a Feb. 29 birthday advances on March 1."""

    return as_of_date.year - date_of_birth.year - (
        (as_of_date.month, as_of_date.day)
        < (date_of_birth.month, date_of_birth.day)
    )


class PolicyFixture(StrictModel):
    """Combine scheme metadata, cited rules, and verification status."""

    scheme_id: str
    scheme_name: LocalizedText
    benefit_summary: LocalizedText
    source: PolicySource
    rules: list[PolicyRule]
    age_as_of: Literal["application_date"]
    age_boundaries_inclusive: Literal[True]
    bpl_confirmation: Literal["government_bpl_card_shown"]
    documents_status: Literal["not_verified"]


class SyntheticProfile(StrictModel):
    """Describe a bounded, explicitly synthetic household profile."""

    synthetic: Literal[True]
    profile_id: str
    date_of_birth: date
    application_date: date
    is_widow: bool
    bpl_card_shown: bool
    state: Literal["Maharashtra"]

    @model_validator(mode="after")
    def validate_application_date(self) -> "SyntheticProfile":
        if self.date_of_birth > self.application_date:
            raise ValueError("date_of_birth cannot be after application_date")
        if calculate_age_on(self.date_of_birth, self.application_date) > 125:
            raise ValueError("age on application_date cannot exceed 125")
        return self

    @property
    def age(self) -> int:
        """Calculate completed age on the application date."""

        return calculate_age_on(self.date_of_birth, self.application_date)

    @property
    def bpl_status(self) -> Literal["confirmed", "unknown"]:
        """A shown government card confirms BPL only for this mock."""

        return "confirmed" if self.bpl_card_shown else "unknown"


class ExpectedVerdict(StrictModel):
    """Capture a reviewed fixture result and the evidence behind it."""

    result: Literal["eligible", "not_eligible", "cant_tell"]
    reason: LocalizedText
    deciding_rule_ids: list[str]
    missing_fields: list[str] = Field(default_factory=list)


class ApplicationDraft(StrictModel):
    """Represent a synthetic application draft eligible for explicit approval."""

    draft_id: str
    scheme_id: str
    applicant_reference: str
    district: str
    date_of_birth: date
    application_date: date
    is_widow: bool
    bpl_card_shown: bool
    declaration: LocalizedText

    @model_validator(mode="after")
    def validate_application_date(self) -> "ApplicationDraft":
        if self.date_of_birth > self.application_date:
            raise ValueError("date_of_birth cannot be after application_date")
        if calculate_age_on(self.date_of_birth, self.application_date) > 125:
            raise ValueError("age on application_date cannot exceed 125")
        return self

    @property
    def age(self) -> int:
        """Calculate completed age on the application date."""

        return calculate_age_on(self.date_of_birth, self.application_date)

    @property
    def bpl_status(self) -> Literal["confirmed", "unknown"]:
        """A shown government card confirms BPL only for this mock."""

        return "confirmed" if self.bpl_card_shown else "unknown"


class DevelopmentScenario(StrictModel):
    """Pair a synthetic profile with its expected reviewed outcome."""

    scenario_id: str
    visible_in_ui: bool
    label: LocalizedText
    profile: SyntheticProfile
    expected_verdict: ExpectedVerdict
    application_draft: ApplicationDraft | None = None


class ReviewerApproval(StrictModel):
    """Record the human review scope for a synthetic mock fixture."""

    reviewer_name: str
    decision: Literal["approved_for_mock_portal"]
    reviewed_at: date
    scope: Literal["synthetic_mock_portal_only"]


class FixtureSet(StrictModel):
    """Validate the policy fixture pack as one internally consistent unit."""

    fixture_version: str
    status: Literal["draft_pending_technical_review", "approved"]
    synthetic_personas: Literal[True]
    reviewer_approval: ReviewerApproval
    policy: PolicyFixture
    scenarios: list[DevelopmentScenario]

    @model_validator(mode="after")
    def validate_scenario_set(self) -> "FixtureSet":
        """Enforce cross-record references and safe draft eligibility."""

        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("Scenario IDs must be unique")

        known_rules = {rule.rule_id for rule in self.policy.rules}
        for scenario in self.scenarios:
            unknown_rules = (
                set(scenario.expected_verdict.deciding_rule_ids) - known_rules
            )
            if unknown_rules:
                raise ValueError(
                    f"{scenario.scenario_id} references unknown rules: "
                    f"{sorted(unknown_rules)}"
                )

            if (
                scenario.expected_verdict.result == "cant_tell"
                and not scenario.expected_verdict.missing_fields
            ):
                raise ValueError(
                    f"{scenario.scenario_id} must identify missing fields"
                )

            draft = scenario.application_draft
            if draft is not None:
                if scenario.expected_verdict.result != "eligible":
                    raise ValueError(
                        f"{scenario.scenario_id} cannot have an application "
                        "draft unless its expected verdict is eligible"
                    )
                if draft.scheme_id != self.policy.scheme_id:
                    raise ValueError(
                        f"{scenario.scenario_id} draft uses a different scheme"
                    )
                if (
                    draft.date_of_birth != scenario.profile.date_of_birth
                    or draft.application_date
                    != scenario.profile.application_date
                    or draft.is_widow != scenario.profile.is_widow
                    or draft.bpl_card_shown
                    != scenario.profile.bpl_card_shown
                ):
                    raise ValueError(
                        f"{scenario.scenario_id} draft does not match its "
                        "synthetic profile"
                    )

        return self
