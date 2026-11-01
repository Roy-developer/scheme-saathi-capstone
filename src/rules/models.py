"""Strict schema for version-controlled, reviewer-approved scheme rules."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class RulePackageModel(BaseModel):
    """Reject undeclared fields in version-controlled rule data."""

    model_config = ConfigDict(extra="forbid")


class RuleSource(RulePackageModel):
    """Source provenance for the policy statements encoded in a rule package."""

    model_config = ConfigDict(frozen=True)

    publisher: str
    source_url: HttpUrl
    collected_at: date
    official_eligibility_text: str
    publication_date_status: Literal["verified", "not_confirmed"]


class Rule(RulePackageModel):
    """One normalized eligibility condition tied to a source clause."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    field: Literal["is_widow", "age", "bpl_status"]
    operator: Literal["eq", "gte", "lte"]
    value: bool | int | str
    source_clause_id: str

    @model_validator(mode="after")
    def validate_field_operator_value(self) -> "Rule":
        """Reject combinations the deterministic evaluator cannot support."""

        if self.field == "is_widow":
            valid = self.operator == "eq" and isinstance(self.value, bool)
        elif self.field == "age":
            valid = (
                self.operator in {"gte", "lte"}
                and type(self.value) is int
                and 0 <= self.value <= 125
            )
        else:
            valid = (
                self.operator == "eq"
                and self.value == "confirmed"
                and isinstance(self.value, str)
            )
        if not valid:
            raise ValueError(
                f"Invalid operator or value for rule field '{self.field}'"
            )
        return self


class RulePackage(RulePackageModel):
    """A versioned, mock-scoped and human-approved rule bundle."""

    model_config = ConfigDict(frozen=True)

    package_version: str
    scheme_id: str
    approval_status: Literal["approved_for_mock_portal"]
    reviewer_name: str
    reviewed_at: date
    approval_scope: Literal["synthetic_mock_portal_only"]
    source: RuleSource
    age_as_of: Literal["application_date"]
    age_boundaries_inclusive: Literal[True]
    bpl_confirmation: Literal["government_bpl_card_shown"]
    documents_status: Literal["not_verified"]
    rules: tuple[Rule, ...] = Field(min_length=4)

    @model_validator(mode="after")
    def validate_rule_set(self) -> "RulePackage":
        """Require the complete, internally consistent mock rule set."""

        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Policy rule IDs must be unique")

        widow_rules = [rule for rule in self.rules if rule.field == "is_widow"]
        age_rules = [rule for rule in self.rules if rule.field == "age"]
        bpl_rules = [rule for rule in self.rules if rule.field == "bpl_status"]
        if (
            len(widow_rules) != 1
            or widow_rules[0].value is not True
            or len(bpl_rules) != 1
            or len(age_rules) != 2
            or {rule.operator for rule in age_rules} != {"gte", "lte"}
        ):
            raise ValueError(
                "Policy must define one widow rule, lower and upper age "
                "bounds, and one BPL rule"
            )

        age_bounds = {rule.operator: rule.value for rule in age_rules}
        if age_bounds["gte"] > age_bounds["lte"]:
            raise ValueError("Minimum age cannot exceed maximum age")
        return self
