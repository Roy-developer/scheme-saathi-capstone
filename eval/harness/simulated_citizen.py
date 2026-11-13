"""Simulated citizen with a hidden profile card (PDF Role 5).

Answers only what is asked from the hidden card — never invents facts.
Offline mode returns typed values directly. Live-model mode uses a *different*
chat model only to phrase an utterance for a known card value (or refuse
unknowns); the card remains the sole source of truth.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field


class HiddenProfileCard(BaseModel):
    """Facts the simulated citizen knows; not visible to the agent under test."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citizen_id: str = Field(min_length=1)
    facts: dict[str, Any] = Field(min_length=1)
    language: str = "en"


class CitizenUtterance(BaseModel):
    """Structured citizen reply; value must match the hidden card."""

    model_config = ConfigDict(extra="forbid")

    utterance: str = Field(
        description="Short natural-language answer a citizen would say aloud.",
    )


LIVE_CITIZEN_SYSTEM = (
    "You are a simulated welfare applicant answering one interview question. "
    "You may ONLY rephrase the provided known fact value. "
    "Never invent, change, or add facts. If the fact is unknown, say you don't know. "
    "For boolean facts, prefer yes/no wording that matches the value."
)


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
            "citizen_mode": "offline_card",
        }
    value = card.facts[fact_id]
    if value is None:
        return {
            "citizen_id": card.citizen_id,
            "fact_id": fact_id,
            "status": "unknown",
            "value": None,
            "utterance": "I'm not sure about that.",
            "citizen_mode": "offline_card",
        }
    return {
        "citizen_id": card.citizen_id,
        "fact_id": fact_id,
        "status": "answered",
        "value": value,
        "utterance": str(value),
        "citizen_mode": "offline_card",
    }


def _typed_reply_from_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


async def answer_question_with_model(
    card: HiddenProfileCard,
    fact_id: str,
    *,
    model: BaseChatModel,
    question_text: str | None = None,
) -> dict[str, Any]:
    """Phrase a reply with a live model; card value remains authoritative.

    If the model fails or drifts from the known value, fall back to the offline
    typed reply so the interview stays grounded in the hidden card.
    """

    offline = answer_question(card, fact_id)
    offline_reply = (
        "I don't know"
        if offline["status"] != "answered"
        else _typed_reply_from_value(offline["value"])
    )
    payload = {
        "fact_id": fact_id,
        "question": question_text or fact_id,
        "known_status": offline["status"],
        "known_value": offline["value"],
        "required_typed_reply": offline_reply,
    }
    try:
        runnable = model.with_structured_output(CitizenUtterance)
        proposal = await runnable.ainvoke(
            [
                SystemMessage(content=LIVE_CITIZEN_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ],
        )
        utterance = (
            proposal.utterance
            if isinstance(proposal, CitizenUtterance)
            else str(getattr(proposal, "utterance", "") or "")
        ).strip()
        if not utterance:
            utterance = offline_reply
    except Exception as error:  # noqa: BLE001 — eval arm must keep interviewing
        return {
            **offline,
            "utterance": offline_reply,
            "citizen_mode": "live_model_fallback_offline",
            "citizen_model_error": f"{type(error).__name__}: {error}",
        }
    return {
        **offline,
        # Journey parsers need a typed answer; keep card value, attach model phrasing.
        "utterance": offline_reply,
        "model_utterance": utterance,
        "citizen_mode": "live_model",
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
