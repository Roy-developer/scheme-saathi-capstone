"""Generic schema for version-controlled scheme rules and household facts.

Every scheme package uses the same shape: the facts it needs, the rules over
those facts, and the source text each rule came from. One deterministic
engine (``src.api.eligibility``) evaluates any package, so new schemes add data,
not code.
"""

from datetime import date
from typing import Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from src.ui.models import calculate_age_on


BoolFact = Literal[
    "is_widow",
    "bpl_card_shown",
    "landholding_family_in_state_records",
    "institutional_landholder",
    "listed_public_office_member",
    "excluded_government_employee_member",
    "pension_at_least_10000_excluding_stated_grades",
    "income_tax_paid_last_assessment_year",
    "registered_practicing_professional_member",
    "nri_new_beneficiary",
]
DateFact = Literal["date_of_birth", "application_date"]
# New registered facts are data-defined; these aliases remain for callers that
# use the legacy profile's fact names.
FactName = str
RuleFact = str

BOOL_FACTS: frozenset[str] = frozenset(get_args(BoolFact))

# Derived facts are computed from raw facts; a rule over a derived fact needs
# every listed input, and unknown inputs are reported by their raw names.
DERIVED_FACT_INPUTS: dict[str, tuple[str, ...]] = {
    "age": ("date_of_birth", "application_date"),
}


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
    revised_as_of: date | None = None


class Rule(RulePackageModel):
    """One normalized condition over a single fact, tied to a source clause."""

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
    field: RuleFact
    operator: Literal["eq", "gte", "lte"]
    value: StrictBool | StrictInt | StrictFloat | StrictStr
    unit: str | None = Field(default=None, max_length=80)
    source_clause_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/()-]{0,119}$"
    )
    # Per-rule source text overrides the package's eligibility text.
    source_text: str | None = None
    source_location: str | None = None
    # Some policies treat a "no" as "show proof", not as a rejection.
    if_not_met: Literal["not_eligible", "need_more_information"] = (
        "not_eligible"
    )
    # User-facing name for the missing evidence; defaults to the fact names.
    missing_field_label: str | None = None

    @model_validator(mode="after")
    def validate_field_operator_value(self) -> "Rule":
        """Reject combinations the deterministic evaluator cannot support."""

        if self.field == "age":
            # Age needs a minimum or maximum with a realistic whole number.
            # type(...) is int rejects True/False, which Python treats as 1/0.
            valid = (
                self.operator in {"gte", "lte"}
                and type(self.value) is int
                and 0 <= self.value <= 125
            )
        elif self.field in BOOL_FACTS:
            # Yes/no facts can only be compared with eq true or eq false.
            valid = self.operator == "eq" and isinstance(self.value, bool)
        else:
            # Generic registered-fact compatibility is checked by the
            # provider against its pinned registry before activation.
            valid = self.operator in {"eq", "gte", "lte"}
        if not valid:
            raise ValueError(
                f"Invalid operator or value for rule field '{self.field}'"
            )
        return self

    @property
    def input_facts(self) -> tuple[str, ...]:
        """Return the raw profile facts this rule reads.

        "age" returns ("date_of_birth", "application_date");
        any other field returns just itself, e.g. ("is_widow",).
        """

        return DERIVED_FACT_INPUTS.get(self.field, (self.field,))


class ReasonText(RulePackageModel):
    """Plain-language reason shown for each possible verdict."""

    model_config = ConfigDict(frozen=True)

    eligible: str
    not_eligible: str
    need_more_information: str


class RulePackage(RulePackageModel):
    """A versioned, mock-scoped rule bundle for one scheme."""

    model_config = ConfigDict(frozen=True)

    package_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    scheme_id: str = Field(pattern=r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
    approval_status: Literal[
        "approved_for_mock_portal",
        "mock_baseline_pending_human_rule_approval",
    ]
    reviewer_name: str
    reviewed_at: date
    approval_scope: Literal["synthetic_mock_portal_only"]
    source: RuleSource
    required_facts: tuple[FactName, ...] = Field(min_length=1)
    age_as_of: Literal["application_date"] | None = None
    age_boundaries_inclusive: Literal[True] | None = None
    bpl_confirmation: Literal["government_bpl_card_shown"] | None = None
    documents_status: Literal["not_verified"]
    reasons: ReasonText
    notice: str | None = None
    unresolved_checks: tuple[str, ...] = ()
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rule_set(self) -> "RulePackage":
        """Require unique rules whose facts are declared and consistent."""

        # Two rules with the same ID would make evidence ambiguous.
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Policy rule IDs must be unique")
        if len(self.required_facts) != len(set(self.required_facts)):
            raise ValueError("required_facts must be unique")

        # Every fact a rule reads must be listed in required_facts, because
        # intake uses that list to know what to ask.
        undeclared = sorted(
            {
                fact
                for rule in self.rules
                for fact in rule.input_facts
                if fact not in self.required_facts
            }
        )
        if undeclared:
            raise ValueError(
                f"Rules use facts missing from required_facts: {undeclared}"
            )

        # Age rules must say which date age is measured on.
        age_rules = [rule for rule in self.rules if rule.field == "age"]
        if age_rules and self.age_as_of is None:
            raise ValueError("Age rules require age_as_of")
        # A minimum above the maximum (e.g. 80 to 40) would reject everyone.
        minimums = [rule.value for rule in age_rules if rule.operator == "gte"]
        maximums = [rule.value for rule in age_rules if rule.operator == "lte"]
        if minimums and maximums and max(minimums) > min(maximums):
            raise ValueError("Minimum age cannot exceed maximum age")
        return self
