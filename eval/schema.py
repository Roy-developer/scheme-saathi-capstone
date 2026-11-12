"""Pydantic schemas for evaluation personas and red-team stubs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.rules.facts import FactRegistry, HouseholdProfile


VerdictResult = Literal["eligible", "not_eligible", "need_more_information"]
EvalSplit = Literal["development", "held_out"]
LabelStatus = Literal["single", "dual_agreed", "dual_conflict", "pending"]
AttackReviewStatus = Literal["approved_for_implementation", "changes_requested"]
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

    Use ``profile`` for known registered facts or ``typed_facts`` when explicit
    unknown values are needed. Both are evaluated against the current registry.
    """

    persona_id: str = Field(min_length=1)
    boundary_family: str = Field(min_length=1)
    split: EvalSplit
    protected: bool
    description: str = Field(min_length=1)
    profile: dict[str, Any] | None = None
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


RedTeamCheckKind = Literal[
    "injection_screen",
    "id_mask",
    "eligibility_truthful",
    "scam_screen",
    "pytest_case",
]


class RedTeamCheck(StrictFrozen):
    """Local check that Role 5 can execute for a red-team case.

    ``injection_screen`` — ``screen_free_text`` must flag the attack input.
    ``scam_screen`` — ``screen_scam_text`` must flag the attack input.
    ``id_mask`` — ``mask_sensitive_text`` must remove ``must_not_contain``.
    ``eligibility_truthful`` — rule engine on ``profile`` / ``typed_facts``
    must match ``expect_result`` (true facts win over a user's request to lie).
    ``pytest_case`` — the suite runner executes the attack's allowlisted local
    pytest case.
    """

    kind: RedTeamCheckKind
    expect_flagged: bool | None = None
    must_not_contain: tuple[str, ...] = ()
    scheme_id: str | None = None
    profile: dict[str, Any] | None = None
    typed_facts: dict[str, Any] | None = None
    expect_result: VerdictResult | None = None

    @model_validator(mode="after")
    def check_fields_for_kind(self) -> RedTeamCheck:
        if self.kind in {"injection_screen", "scam_screen"} and self.expect_flagged is None:
            raise ValueError(f"{self.kind} checks require expect_flagged")
        if self.kind == "id_mask" and not self.must_not_contain:
            raise ValueError("id_mask checks require must_not_contain")
        if self.kind == "eligibility_truthful":
            if not self.scheme_id or self.expect_result is None:
                raise ValueError(
                    "eligibility_truthful checks require scheme_id and expect_result"
                )
            if self.profile is None and self.typed_facts is None:
                raise ValueError(
                    "eligibility_truthful checks require profile or typed_facts"
                )
        return self


class RedTeamCase(StrictFrozen):
    """One red-team attack. ``check`` makes it offline-runnable; else stub."""

    attack_id: str = Field(min_length=1)
    category: AttackCategory
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    attack_input: str = Field(min_length=1)
    expected_behaviour: str = Field(min_length=1)
    status: Literal["stub", "runnable"] = "stub"
    check: RedTeamCheck | None = None
    author: str | None = Field(default=None, min_length=1)
    reviewed_by: str | None = Field(default=None, min_length=1)
    review_status: AttackReviewStatus | None = None

    @model_validator(mode="after")
    def runnable_requires_check(self) -> RedTeamCase:
        if self.status == "runnable" and self.check is None:
            raise ValueError(
                f"Attack {self.attack_id!r}: runnable cases need a check block"
            )
        if self.status == "stub" and self.check is not None:
            raise ValueError(
                f"Attack {self.attack_id!r}: stub cases must not declare a check"
            )
        if self.reviewed_by is not None and self.author is None:
            raise ValueError(
                f"Attack {self.attack_id!r}: reviewed_by requires an author"
            )
        if self.review_status is not None and self.reviewed_by is None:
            raise ValueError(
                f"Attack {self.attack_id!r}: review status requires author and reviewer metadata"
            )
        if (
            self.author is not None
            and self.reviewed_by is not None
            and self.author.casefold() == self.reviewed_by.casefold()
        ):
            raise ValueError(
                f"Attack {self.attack_id!r}: author and reviewer must be different"
            )
        return self


class AIAttackReviewDecision(StrictFrozen):
    """AI scenario review decision, separate from human authorship metadata."""

    decision: Literal["approved_for_suite", "changes_requested"]
    note: str = Field(min_length=1)


class AIAttackReview(StrictFrozen):
    """Batch record for an AI review; not a claim of independent validation."""

    reviewer: str = Field(min_length=1)
    review_date: str = Field(min_length=1)
    scope_note: str = Field(min_length=1)
    decisions: dict[str, AIAttackReviewDecision] = Field(min_length=1)


class RedTeamSuite(StrictFrozen):
    """Versioned collection of red-team attack stubs."""

    suite_version: str = Field(min_length=1)
    annotation_note: str = Field(min_length=1)
    attacks: tuple[RedTeamCase, ...] = Field(min_length=1)
    ai_review: AIAttackReview | None = None

    @model_validator(mode="after")
    def unique_ids(self) -> RedTeamSuite:
        by_id: dict[str, RedTeamCase] = {}
        for attack in self.attacks:
            if attack.attack_id in by_id:
                raise ValueError(f"Duplicate attack_id {attack.attack_id!r}")
            by_id[attack.attack_id] = attack
        if self.ai_review is not None:
            unknown_ids = set(self.ai_review.decisions) - set(by_id)
            if unknown_ids:
                raise ValueError(
                    f"AI review contains unknown attack IDs: {sorted(unknown_ids)}"
                )
        return self


class ExperimentConfig(BaseModel):
    """E1–E4 experiment config stub loaded from eval/experiments/.

    Extra keys (for example ``approved_lessons``) are ignored so configs can
    grow without breaking the inventory loader.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    experiment_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: str = Field(min_length=1)
    description: str = Field(min_length=1)
    controls: dict[str, Any] = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    blocker: str | None = None
    configurations: tuple[dict[str, Any], ...] | None = None
    commands: dict[str, Any] | None = None
    note: str | None = None


def profile_from_mapping(
    raw: dict[str, Any], registry: FactRegistry,
) -> HouseholdProfile:
    """Build a registry-validated fact store, ignoring UI-only fields."""

    allowed = {
        definition.fact_id for definition in registry.definitions
        if not definition.derived_from
    }
    cleaned = {key: value for key, value in raw.items() if key in allowed}
    return HouseholdProfile.from_answers(cleaned, registry)
