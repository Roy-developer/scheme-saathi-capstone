from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedText(StrictModel):
    en: str
    hi: str
    mr: str


class PolicySource(StrictModel):
    publisher: str
    source_url: HttpUrl
    collected_at: date
    official_eligibility_text: str
    publication_date_status: Literal["verified", "not_confirmed"]


class PolicyRule(StrictModel):
    rule_id: str
    field: Literal["is_widow", "age", "bpl_status"]
    operator: Literal["eq", "gte", "lte"]
    value: bool | int | str
    source_clause_id: str


class PolicyFixture(StrictModel):
    scheme_id: str
    scheme_name: LocalizedText
    benefit_summary: LocalizedText
    source: PolicySource
    rules: list[PolicyRule]
    documents_status: Literal["not_verified"]


class SyntheticProfile(StrictModel):
    synthetic: Literal[True]
    profile_id: str
    age: int = Field(ge=0, le=125)
    is_widow: bool
    bpl_status: Literal["confirmed", "not_confirmed", "unknown"]
    state: Literal["Maharashtra"]


class ExpectedVerdict(StrictModel):
    result: Literal["eligible", "not_eligible", "cant_tell"]
    reason: LocalizedText
    deciding_rule_ids: list[str]
    missing_fields: list[str] = Field(default_factory=list)


class DevelopmentScenario(StrictModel):
    scenario_id: str
    visible_in_ui: bool
    label: LocalizedText
    profile: SyntheticProfile
    expected_verdict: ExpectedVerdict


class FixtureSet(StrictModel):
    fixture_version: str
    status: Literal["draft_pending_role_review", "approved"]
    synthetic_personas: Literal[True]
    policy: PolicyFixture
    scenarios: list[DevelopmentScenario]

    @model_validator(mode="after")
    def validate_scenario_set(self) -> "FixtureSet":
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

        return self
