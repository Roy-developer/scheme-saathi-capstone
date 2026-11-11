"""Simulated citizen with a hidden profile card (PDF Role 5).

Answers only what is asked from the hidden card — never invents facts.
This is the offline stand-in for a different-model simulated citizen.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class HiddenProfileCard(BaseModel):
    """Facts the simulated citizen knows; not visible to the agent under test."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citizen_id: str = Field(min_length=1)
    facts: dict[str, Any] = Field(min_length=1)
    language: str = "en"


def answer_question(
    card: HiddenProfileCard,
    fact_id: str,
) -> dict[str, Any]:
    """Return the asked fact, or explicitly unknown — never guess."""

    if fact_id not in card.facts:
        return {
            "citizen_id": card.citizen_id,
            "fact_id": fact_id,
            "status": "unknown",
            "value": None,
            "utterance": "I don't know / I wasn't asked that before.",
        }
    value = card.facts[fact_id]
    if value is None:
        return {
            "citizen_id": card.citizen_id,
            "fact_id": fact_id,
            "status": "unknown",
            "value": None,
            "utterance": "I'm not sure about that.",
        }
    return {
        "citizen_id": card.citizen_id,
        "fact_id": fact_id,
        "status": "answered",
        "value": value,
        "utterance": str(value),
    }


def interview(
    card: HiddenProfileCard,
    questions: Mapping[str, str],
) -> dict[str, Any]:
    """Ask a planned list of fact_id → prompt; answer only from the card."""

    turns = []
    for fact_id, prompt in questions.items():
        reply = answer_question(card, fact_id)
        turns.append({"prompt": prompt, **reply})
    answered = sum(1 for turn in turns if turn["status"] == "answered")
    return {
        "citizen_id": card.citizen_id,
        "language": card.language,
        "question_count": len(turns),
        "answered_count": answered,
        "unknown_count": len(turns) - answered,
        "turns": turns,
    }
