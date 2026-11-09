"""Registry-backed definitions and validated values for scheme facts."""

from datetime import date
from decimal import Decimal, InvalidOperation
from graphlib import CycleError, TopologicalSorter
import math
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from src.ui.models import calculate_age_on


FACT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SUPPORTED_LOCALES = frozenset({"en", "hi", "mr"})
UNKNOWN_ANSWER_TOKENS = frozenset(
    {
        "i don't know", "i dont know", "don't know", "dont know",
        "not sure", "unknown", "idk", "skip", "मुझे नहीं पता", "पता नहीं",
        "मालूम नहीं", "अनिश्चित", "माहित नाही", "माहीत नाही", "ठाऊक नाही",
        "निश्चित नाही",
    }
)
DECIMAL_WIRE_KEY = "$decimal"
DECIMAL_TEXT_PATTERN = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)


def _choice_token(value: str) -> str:
    """Normalize choice text with the same case, spacing, and punctuation rules as intake."""

    normalized = value.replace("\u2019", "'").strip().casefold().rstrip(".!?")
    normalized = normalized.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    return " ".join(normalized.split())


def encode_wire_value(value: object) -> object:
    """Turn a fact value into JSON-safe data without losing precision.

    Decimals become ``{"$decimal": "<text>"}`` and dates become ISO text;
    everything else is returned unchanged.
    """

    if isinstance(value, Decimal):
        return {DECIMAL_WIRE_KEY: str(value)}
    if isinstance(value, date):
        return value.isoformat()
    return value


def decode_wire_value(
    definition: "FactDefinition",
    value: object,
    *,
    allow_plain_numbers: bool = False,
) -> object:
    """Reverse ``encode_wire_value`` for one fact, checking the stored form.

    Args:
        definition: The fact's definition (its ``value_type`` decides decoding).
        value: The stored JSON value.
        allow_plain_numbers: Accept a plain JSON number for a decimal fact
            (only older checkpoints stored them that way).

    Raises:
        ValueError: The stored value does not have a valid form.
    """

    if definition.value_type == "decimal":
        if isinstance(value, dict):
            if set(value) != {DECIMAL_WIRE_KEY}:
                raise ValueError("Decimal wire value has an invalid shape")
            decimal_text = value[DECIMAL_WIRE_KEY]
            if (
                type(decimal_text) is not str
                or DECIMAL_TEXT_PATTERN.fullmatch(decimal_text) is None
            ):
                raise ValueError("Decimal wire value is invalid")
            return Decimal(decimal_text)
        if allow_plain_numbers and type(value) in (int, float, Decimal):
            return Decimal(str(value))
        raise ValueError("Decimal facts require a numeric value")
    if definition.value_type == "date" and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Date wire value is invalid") from error
    return value


class StrictDataModel(BaseModel):
    """Reject undeclared fields in registry and fact-store data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalizedQuestion(StrictDataModel):
    """Question copy and optional help text for one supported locale."""

    text: str = Field(min_length=1, max_length=1000)
    help_text: str | None = Field(default=None, max_length=1000)


class PrivacyPolicy(StrictDataModel):
    """Declared purpose and review state for collecting a fact."""

    policy_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    purpose: str = Field(min_length=1, max_length=500)
    sensitivity: Literal["ordinary", "sensitive", "highly_sensitive"]
    review_status: Literal["pending", "approved"]
    reviewer: str | None = Field(default=None, max_length=150)
    reviewed_at: date | None = None

    @model_validator(mode="after")
    def require_privacy_review_details(self) -> "PrivacyPolicy":
        """Do not label privacy policy as approved without review evidence."""

        if not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Privacy policy version must use numeric semver")
        if not self.policy_id.strip() or not self.purpose.strip():
            raise ValueError("Privacy policy ID and purpose cannot be blank")
        if self.review_status == "approved" and (
            self.reviewer is None or self.reviewed_at is None
        ):
            raise ValueError("Approved privacy policy requires reviewer and date")
        return self


class FactDefinition(StrictDataModel):
    """Stable meaning, validation, question, privacy, and version of one fact."""

    fact_id: str
    version: str = Field(min_length=1, max_length=40)
    meaning: str = Field(min_length=1, max_length=1000)
    source_refs: tuple[HttpUrl, ...] = Field(min_length=1)
    definition_review_status: Literal["pending", "approved"]
    definition_reviewer: str | None = Field(default=None, max_length=150)
    definition_reviewed_at: date | None = None
    scope: Literal["person", "family"]
    value_type: Literal[
        "boolean", "date", "integer", "decimal", "choice", "text"
    ]
    unit: str | None = Field(default=None, max_length=80)
    period: str | None = Field(default=None, max_length=100)
    minimum: int | float | None = None
    maximum: int | float | None = None
    choices: tuple[str, ...] = ()
    choice_labels: dict[str, dict[str, str]] = Field(default_factory=dict)
    max_length: int | None = Field(default=None, ge=1, le=2000)
    display_only: bool = False
    derived_from: tuple[str, ...] = ()
    derivation: Literal["age_on_application_date"] | None = None
    questions: dict[str, LocalizedQuestion]
    question_review_status: Literal["pending", "approved"]
    question_reviewer: str | None = Field(default=None, max_length=150)
    questions_reviewed_at: date | None = None
    privacy: PrivacyPolicy

    @model_validator(mode="before")
    @classmethod
    def reject_non_numeric_bounds(cls, value: object) -> object:
        """Reject booleans and numeric strings in registry bounds."""

        if isinstance(value, dict):
            for name in ("minimum", "maximum"):
                bound = value.get(name)
                if bound is not None and type(bound) not in (int, float):
                    raise ValueError(f"{name} must be a JSON number")
                if isinstance(bound, float) and not math.isfinite(bound):
                    raise ValueError(f"{name} must be finite")
        return value

    @model_validator(mode="after")
    def validate_definition(self) -> "FactDefinition":
        """Enforce type-specific metadata and complete locale coverage."""

        if not FACT_ID_PATTERN.fullmatch(self.fact_id):
            raise ValueError(f"Invalid fact ID: {self.fact_id}")
        if not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Fact definition version must use numeric semver")
        if set(self.questions) != SUPPORTED_LOCALES:
            raise ValueError("Questions must define exactly en, hi, and mr")
        if not self.meaning.strip() or any(
            not question.text.strip() for question in self.questions.values()
        ):
            raise ValueError("Fact meaning and localized questions cannot be blank")
        if self.definition_review_status == "approved" and (
            self.definition_reviewer is None
            or self.definition_reviewed_at is None
        ):
            raise ValueError("Approved fact definitions require reviewer and date")
        if self.question_review_status == "approved" and (
            self.question_reviewer is None or self.questions_reviewed_at is None
        ):
            raise ValueError("Approved questions require reviewer and date")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("Fact minimum cannot exceed maximum")
        if self.value_type in {"integer", "decimal"}:
            for bound in (self.minimum, self.maximum):
                if bound is not None and type(bound) not in (int, float):
                    raise ValueError("Numeric facts require numeric bounds")
                if (
                    self.value_type == "integer"
                    and bound is not None
                    and type(bound) is not int
                ):
                    raise ValueError("Integer facts require integer bounds")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("Only numeric facts may have numeric bounds")
        if self.value_type == "choice":
            if (
                not self.choices
                or len(self.choices) != len(set(self.choices))
                or len({_choice_token(choice) for choice in self.choices})
                != len(self.choices)
                or any(not choice.strip() for choice in self.choices)
            ):
                raise ValueError("Choice facts require unique choices")
            if self.choice_labels and (
                set(self.choice_labels) != SUPPORTED_LOCALES
                or any(
                    set(labels) != set(self.choices)
                    or any(not label.strip() for label in labels.values())
                    for labels in self.choice_labels.values()
                )
            ):
                raise ValueError(
                    "Choice labels must cover every choice in en, hi, and mr"
                )
            for locale, labels in self.choice_labels.items():
                owners: dict[str, str] = {}
                for code in self.choices:
                    for token in (code, labels[code]):
                        normalized = _choice_token(token)
                        owner = owners.setdefault(normalized, code)
                        if owner != code:
                            raise ValueError(
                                "Choice codes and localized labels must be "
                                "unambiguous in every locale"
                            )
            labels_and_codes = [
                *self.choices,
                *(
                    label
                    for locale_labels in self.choice_labels.values()
                    for label in locale_labels.values()
                ),
            ]
            if any(
                item.strip().lower() in UNKNOWN_ANSWER_TOKENS
                for item in labels_and_codes
            ):
                raise ValueError("Choice values cannot overlap unknown answers")
        elif self.choices or self.choice_labels:
            raise ValueError("Only choice facts may declare choices")
        if self.value_type == "text":
            if self.max_length is None or not self.display_only:
                raise ValueError("Text facts must be bounded and display-only")
        elif self.max_length is not None or self.display_only:
            raise ValueError("Text constraints are only valid for text facts")
        if self.derived_from:
            if (
                self.fact_id != "age"
                or self.value_type != "integer"
                or self.derivation != "age_on_application_date"
                or self.derived_from != ("date_of_birth", "application_date")
            ):
                raise ValueError("Unsupported derived fact definition")
        elif self.derivation is not None:
            raise ValueError("A derivation requires declared input facts")
        return self

    def validate_value(self, value: object) -> object:
        """Return a normalized value or reject a value incompatible with this fact."""

        if self.value_type == "boolean":
            if type(value) is not bool:
                raise ValueError(f"{self.fact_id} must be a boolean")
            return value
        if self.value_type == "date":
            if type(value) is date:
                return value
            if isinstance(value, str):
                try:
                    return date.fromisoformat(value)
                except ValueError as error:
                    raise ValueError(f"{self.fact_id} must be an ISO date") from error
            raise ValueError(f"{self.fact_id} must be an ISO date")
        if self.value_type == "integer":
            if type(value) is not int:
                raise ValueError(f"{self.fact_id} must be an integer")
            numeric = Decimal(value)
        elif self.value_type == "decimal":
            if type(value) not in (int, float, Decimal):
                raise ValueError(f"{self.fact_id} must be a finite decimal")
            try:
                numeric = Decimal(str(value))
            except InvalidOperation as error:
                raise ValueError(
                    f"{self.fact_id} must be a finite decimal"
                ) from error
            if not numeric.is_finite():
                raise ValueError(f"{self.fact_id} must be a finite decimal")
        elif self.value_type == "choice":
            if type(value) is not str or value not in self.choices:
                raise ValueError(f"{self.fact_id} is not a registered choice")
            return value
        elif self.value_type == "text":
            if type(value) is not str or len(value) > (self.max_length or 0):
                raise ValueError(f"{self.fact_id} exceeds its text limit")
            return value
        else:
            raise ValueError(f"Unsupported fact type: {self.value_type}")

        if self.minimum is not None and numeric < Decimal(str(self.minimum)):
            raise ValueError(f"{self.fact_id} is below its minimum")
        if self.maximum is not None and numeric > Decimal(str(self.maximum)):
            raise ValueError(f"{self.fact_id} is above its maximum")
        return int(numeric) if self.value_type == "integer" else numeric


class FactRegistry(StrictDataModel):
    """Versioned, immutable definitions shared by scheme bundles."""

    schema_version: Literal["1.0"]
    registry_version: str = Field(min_length=1, max_length=40)
    definitions: tuple[FactDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry(self) -> "FactRegistry":
        """Reject duplicate IDs, bad derivation references, and cycles."""

        if not VERSION_PATTERN.fullmatch(self.registry_version):
            raise ValueError("Fact registry version must use numeric semver")
        ids = [definition.fact_id for definition in self.definitions]
        if len(ids) != len(set(ids)):
            raise ValueError("Fact registry IDs must be unique")
        by_id = {definition.fact_id: definition for definition in self.definitions}
        for definition in self.definitions:
            for input_id in definition.derived_from:
                if input_id not in by_id:
                    raise ValueError(
                        f"Unknown derived-fact input '{input_id}'"
                    )
            if definition.derivation == "age_on_application_date":
                if any(
                    by_id[input_id].value_type != "date"
                    for input_id in definition.derived_from
                ):
                    raise ValueError("Age derivation requires date inputs")
        self._validate_acyclic(by_id)
        return self

    @staticmethod
    def _validate_acyclic(by_id: dict[str, FactDefinition]) -> None:
        """Reject cycles so data cannot recursively derive itself."""

        dependencies = {
            fact_id: [d for d in definition.derived_from if d in by_id]
            for fact_id, definition in by_id.items()
        }
        try:
            TopologicalSorter(dependencies).prepare()
        except CycleError as error:
            raise ValueError("Derived fact definitions contain a cycle") from error

    def get(self, fact_id: str) -> FactDefinition:
        """Return a registered fact or raise ``KeyError``."""

        for definition in self.definitions:
            if definition.fact_id == fact_id:
                return definition
        raise KeyError(fact_id)


class FactState(StrictDataModel):
    """A fact's known, unknown, or declined state with its definition version."""

    status: Literal["known", "unknown", "declined"]
    value: object = None
    definition_version: str
    provenance: Literal["user_reported", "document", "verified_record"] | None = None

    @model_validator(mode="after")
    def validate_state_shape(self) -> "FactState":
        """Keep unknown and declined states distinct from concrete values."""

        if self.status == "known":
            if self.value is None or self.provenance is None:
                raise ValueError("Known facts require value and provenance")
        elif self.value is not None or self.provenance is not None:
            raise ValueError("Unknown or declined facts cannot contain values")
        return self


class TypedFactStore(StrictDataModel):
    """Registry-versioned values; values are validated before rule evaluation."""

    registry_version: str
    facts: dict[str, FactState]

    @classmethod
    def from_answers(
        cls, answers: Mapping[str, object], registry: FactRegistry,
    ) -> "TypedFactStore":
        """Build a store from confirmed answers keyed by fact ID; None means unknown."""

        facts = {}
        for fact_id, value in answers.items():
            if value is None:
                continue
            definition = registry.get(fact_id)
            if definition.value_type == "date" and isinstance(value, str):
                value = date.fromisoformat(value)
            facts[fact_id] = FactState(
                status="known",
                value=definition.validate_value(value),
                definition_version=definition.version,
                provenance="user_reported",
            )
        return cls(
            registry_version=registry.registry_version, facts=facts,
        ).validate_against(registry)

    def to_wire(self, registry: FactRegistry | None = None) -> dict[str, object]:
        """Serialize checkpoint/MCP values without losing decimal precision."""

        if registry is not None:
            self.validate_against(registry)
        states: dict[str, object] = {}
        for fact_id, state in self.facts.items():
            value = state.value
            if state.status == "known":
                value = encode_wire_value(value)
            states[fact_id] = {
                "status": state.status,
                "value": value,
                "definition_version": state.definition_version,
                "provenance": state.provenance,
            }
        return {"registry_version": self.registry_version, "facts": states}

    @classmethod
    def from_wire(
        cls,
        data: object,
        registry: FactRegistry,
    ) -> "TypedFactStore":
        """Restore explicitly tagged decimals and validate a wire fact store."""

        if not isinstance(data, dict):
            raise ValueError("Fact store wire data must be an object")
        restored = dict(data)
        raw_facts = restored.get("facts")
        if not isinstance(raw_facts, dict):
            raise ValueError("Fact store wire facts must be an object")
        facts: dict[str, dict[str, object]] = {}
        for fact_id, raw_state in raw_facts.items():
            definition = registry.get(fact_id)
            if not isinstance(raw_state, dict):
                raise ValueError("Fact state wire data must be an object")
            state_data = dict(raw_state)
            if state_data.get("status") == "known":
                # Older checkpoints stored decimals as plain JSON numbers.
                state_data["value"] = decode_wire_value(
                    definition, state_data.get("value"), allow_plain_numbers=True
                )
            facts[fact_id] = state_data
        restored["facts"] = facts
        return cls.model_validate(restored).validate_against(registry)

    def validate_against(self, registry: FactRegistry) -> "TypedFactStore":
        """Validate all supplied IDs, versions, types, and bounds."""

        if self.registry_version != registry.registry_version:
            raise ValueError("Fact store uses an incompatible registry version")
        for fact_id, state in self.facts.items():
            definition = registry.get(fact_id)
            if definition.derived_from:
                raise ValueError(f"Derived fact '{fact_id}' cannot be supplied")
            if state.definition_version != definition.version:
                raise ValueError(f"Incompatible definition version for {fact_id}")
            if state.status == "known":
                definition.validate_value(state.value)
        if any(
            definition.fact_id == "age"
            for definition in registry.definitions
        ):
            birth_date = self.value("date_of_birth", registry)
            application_date = self.value("application_date", registry)
            if birth_date is not None and application_date is not None:
                age = calculate_age_on(birth_date, application_date)
                if age < 0:
                    raise ValueError(
                        "date_of_birth cannot be after application_date"
                    )
                if age > 125:
                    raise ValueError("age on application_date cannot exceed 125")
        return self

    def state(self, fact_id: str) -> FactState | None:
        """Return a supplied state, or ``None`` for an unanswered fact."""

        return self.facts.get(fact_id)

    def value(self, fact_id: str, registry: FactRegistry) -> object | None:
        """Read a known raw or explicitly supported derived value."""

        definition = registry.get(fact_id)
        if not definition.derived_from:
            state = self.state(fact_id)
            if state is None or state.status != "known":
                return None
            return definition.validate_value(state.value)
        if definition.derivation == "age_on_application_date":
            birth_date = self.value("date_of_birth", registry)
            application_date = self.value("application_date", registry)
            if birth_date is None or application_date is None:
                return None
            return calculate_age_on(birth_date, application_date)
        raise ValueError(f"Unsupported derivation for {fact_id}")

    def missing_inputs(self, fact_id: str, registry: FactRegistry) -> list[str]:
        """Return unanswered raw inputs, preserving explicit unknown/declined."""

        definition = registry.get(fact_id)
        inputs = definition.derived_from or (fact_id,)
        return [
            input_id
            for input_id in inputs
            if self.value(input_id, registry) is None
        ]
