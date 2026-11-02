"""Typed contracts shared by the supervisor and specialist agents.

Phase 1 defines these contracts so later phases build on agreed shapes.
``HouseholdProfile`` lives in ``src.rules.models`` because the rule engine
evaluates it directly.
"""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.rules.models import HouseholdProfile


SpecialistName = Literal[
    "intake",
    "search",
    "eligibility",
    "documents",
    "application",
]
StepStatus = Literal["pending", "in_progress", "done", "skipped", "failed"]
VerdictResult = Literal[
    "eligible",
    "not_eligible",
    "need_more_information",
    "information_only",
]


class ContractModel(BaseModel):
    """Reject undeclared fields so agents cannot pass unexpected data."""

    model_config = ConfigDict(extra="forbid")


class PlanStep(ContractModel):
    """One step of the supervisor's plan, owned by exactly one specialist."""

    step_id: str
    specialist: SpecialistName
    goal: str
    status: StepStatus = "pending"
    scheme_id: str | None = None


class Plan(ContractModel):
    """The visible plan; each replan bumps the version and records why."""

    version: int = Field(default=1, ge=1)
    steps: list[PlanStep] = Field(default_factory=list)
    replan_reason: str | None = None

    @model_validator(mode="after")
    def validate_steps(self) -> "Plan":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Plan step IDs must be unique")
        if self.version > 1 and not self.replan_reason:
            raise ValueError("A replanned version must record replan_reason")
        return self


class CandidateVerdict(ContractModel):
    """The rule-engine verdict for one candidate scheme."""

    scheme_id: str
    result: VerdictResult
    missing_fields: list[str] = Field(default_factory=list)
    deciding_rule_ids: list[str] = Field(default_factory=list)


class Handoff(ContractModel):
    """A typed message from the supervisor to a specialist, or back."""

    handoff_id: UUID = Field(default_factory=uuid4)
    sender: Literal["supervisor"] | SpecialistName
    recipient: Literal["supervisor"] | SpecialistName
    step_id: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_route(self) -> "Handoff":
        # Specialists only talk to the supervisor, never to each other.
        if "supervisor" not in (self.sender, self.recipient):
            raise ValueError("Handoffs must go to or from the supervisor")
        if self.sender == self.recipient:
            raise ValueError("A handoff needs different sender and recipient")
        return self


__all__ = [
    "CandidateVerdict",
    "Handoff",
    "HouseholdProfile",
    "Plan",
    "PlanStep",
]
