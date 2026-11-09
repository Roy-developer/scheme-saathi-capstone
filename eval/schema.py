"""Pydantic schemas for evaluation personas and red-team stubs."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.rules.models import HouseholdProfile


VerdictResult = Literal["eligible", "not_eligible", "need_more_information"]
EvalSplit = Literal["development", "held_out"]
LabelStatus = Literal["single", "dual_agreed", "dual_conflict", "pending"]
AttackCategory = Literal[
    "scam_page",
    "scheme_text_injection",
    "inflate_eligibility",
    "cross_household_memory",
    "id_leakage",
    "other",
]


class StrictFrozen(BaseModel):
    """Reject undeclared fields; keep eval cases immutable once loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedVerdict(StrictFrozen):
    """Expected rule-engine outcome for one scheme."""

    result: VerdictResult
    missing_fields: tuple[str, ...] = ()
    deciding_rule_ids: tuple[str, ...] | None = None
    note: str | None = None

    @field_validator("result", mode="before")
    @classmethod
    def normalize_cant_tell(cls, value: object) -> object:
        """Map the UI fixture alias ``cant_tell`` to the engine verdict."""

        if value == "cant_tell":
            return "need_more_information"
        return value


class PersonaLabel(StrictFrozen):
    """One human label on a persona × scheme expected verdict."""

    labeller_id: str = Field(min_length=1)
    scheme_id: str = Field(min_length=1)
    result: VerdictResult
    status: LabelStatus = "single"
    note: str | None = None

    @field_validator("result", mode="before")
    @classmethod
    def normalize_cant_tell(cls, value: object) -> object:
        if value == "cant_tell":
            return "need_more_information"
        return value


class EvalPersona(StrictFrozen):
    """One synthetic boundary persona with expected scheme verdicts.

    Use ``profile`` for legacy HouseholdProfile fields, or ``typed_facts`` for
    registry facts (for example IGNOAPS ``name_on_bpl_list``). At least one
    must be set. ``null`` in ``typed_facts`` means unknown.
    """

    persona_id: str = Field(min_length=1)
    boundary_family: str = Field(min_length=1)
    split: EvalSplit
    protected: bool
    description: str = Field(min_length=1)
    profile: HouseholdProfile | None = None
    typed_facts: dict[str, Any] | None = None
    expected_by_scheme: dict[str, ExpectedVerdict] = Field(min_length=1)
    labels: tuple[PersonaLabel, ...] = ()

    @model_validator(mode="after")
    def check_inputs_and_split(self) -> EvalPersona:
        """Require a profile or typed facts; enforce split/protection rules."""

        if self.profile is None and not self.typed_facts:
            raise ValueError(
                f"Persona {self.persona_id!r}: provide profile and/or typed_facts"
            )
        if self.split == "development" and self.protected:
            raise ValueError(
                f"Persona {self.persona_id!r}: development cases cannot be protected"
            )
        if self.split == "held_out" and not self.protected:
            raise ValueError(
                f"Persona {self.persona_id!r}: held-out cases must be protected"
            )
        return self


class PersonaEvaluationSet(StrictFrozen):
    """A versioned set of personas for one split."""

    dataset_version: str = Field(min_length=1)
    split: EvalSplit
    protected: bool
    annotation_note: str = Field(min_length=1)
    personas: tuple[EvalPersona, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_consistency(self) -> PersonaEvaluationSet:
        """Ensure set-level flags match every persona and IDs are unique."""

        if self.split == "development" and self.protected:
            raise ValueError("Development evaluation sets cannot be protected")
        if self.split == "held_out" and not self.protected:
            raise ValueError("Held-out evaluation sets must be protected")

        seen: set[str] = set()
        for persona in self.personas:
            if persona.persona_id in seen:
                raise ValueError(f"Duplicate persona_id {persona.persona_id!r}")
            seen.add(persona.persona_id)
            if persona.split != self.split:
                raise ValueError(
                    f"Persona {persona.persona_id!r} split "
                    f"{persona.split!r} != set split {self.split!r}"
                )
            if persona.protected != self.protected:
                raise ValueError(
                    f"Persona {persona.persona_id!r} protected flag mismatches set"
                )
        return self


class RedTeamCase(StrictFrozen):
    """One red-team attack stub (execution against defences is a later pass)."""

    attack_id: str = Field(min_length=1)
    category: AttackCategory
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    attack_input: str = Field(min_length=1)
    expected_behaviour: str = Field(min_length=1)
    status: Literal["stub", "runnable"] = "stub"


class RedTeamSuite(StrictFrozen):
    """Versioned collection of red-team attack stubs."""

    suite_version: str = Field(min_length=1)
    annotation_note: str = Field(min_length=1)
    attacks: tuple[RedTeamCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> RedTeamSuite:
        seen: set[str] = set()
        for attack in self.attacks:
            if attack.attack_id in seen:
                raise ValueError(f"Duplicate attack_id {attack.attack_id!r}")
            seen.add(attack.attack_id)
        return self


def profile_from_mapping(raw: dict) -> HouseholdProfile:
    """Build a HouseholdProfile, ignoring UI-only keys such as state."""

    allowed = set(HouseholdProfile.model_fields)
    cleaned = {key: value for key, value in raw.items() if key in allowed}
    for key in ("date_of_birth", "application_date"):
        value = cleaned.get(key)
        if isinstance(value, str):
            cleaned[key] = date.fromisoformat(value)
    return HouseholdProfile.model_validate(cleaned)
