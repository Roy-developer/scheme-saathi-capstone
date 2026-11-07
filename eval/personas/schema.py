"""Shared shape for every eval persona: dev, held-out and the simulated citizen.

Built on the project's own contracts so a persona's expected outcome can be
compared field-for-field against what the journey API actually returns:
``HouseholdProfile`` from ``src.rules.models`` is the ground-truth profile,
``VerdictResult`` from ``src.workflow.state`` is the verdict vocabulary.
One persona = one JSON file under ``eval/personas/`` (dev) or
``eval/held_out/`` (held-out).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.rules.models import HouseholdProfile
from src.workflow.state import VerdictResult

Language = Literal["en", "hi", "mr"]
Split = Literal["dev", "held_out"]


class ExpectedOutcome(BaseModel):
    """The labelled answer for one scheme, written before the agent runs."""

    model_config = ConfigDict(extra="forbid")

    result: VerdictResult
    deciding_rule_ids: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    # Why this is the right answer, for the two labellers to reconcile
    # disagreements against and for the report's error analysis later.
    notes: str


class Persona(BaseModel):
    """One synthetic household, its true facts, and the labelled verdicts."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    # Short note on what this persona is for, e.g. "age boundary 59 vs 60,
    # widow, BPL card shown".
    description: str
    language: Language
    split: Split

    # Ground truth. The rule engine's verdict is computed from this, and the
    # simulated citizen answers questions consistently with it.
    profile: HouseholdProfile

    # Optional free-text phrasings the simulated citizen gives instead of a
    # plain yes/no/date, keyed by fact name, to exercise the LLM answer
    # reader (e.g. {"is_widow": "My husband died last year"}). Facts not
    # listed here are answered with a plain yes/no/date derived from
    # ``profile``.
    citizen_answers: dict[str, str] = Field(default_factory=dict)

    # One expected outcome per scheme this persona is checked against.
    # Most personas target one scheme; a multi-scheme persona (Phase 3) can
    # list more than one, e.g. {"IGNWPS-MH": ..., "PM-KISAN-IN": ...}.
    expected: dict[str, ExpectedOutcome]

    # Who independently labelled this persona's expected outcomes. Keep both
    # names until reconciled; the capstone guide requires two labellers.
    labelled_by: list[str] = Field(default_factory=list)
