"""Journey-facing planned vs fixed question-order ablation for E4.

Drives the real interview graph (``run_journey`` / ``resume_journey``) with a
simulated citizen that answers only from the persona's known facts. Compares
adaptive (``question_order=planned``) vs fixed questionnaire
(``question_order=fixed``) on the same persona × scheme.

No live LLM is required: intake is deterministic and answers are typed from
the hidden profile. This is evaluation-only and does not write household
memory or portal state.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from eval.harness.runner import load_persona_evaluation_set, persona_input
from eval.harness.simulated_citizen import HiddenProfileCard, answer_question
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactRegistry, HouseholdProfile
from src.workflow.journey import (
    JourneyRequest,
    build_journey_graph,
    resume_journey,
    run_journey,
)
from src.workflow.question_picker import fixed_questionnaire_facts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_PERSONAS = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
MAX_TURNS = 40
NOTICE = (
    "journey-facing question-order ablation: uses the interview graph with "
    "simulated-citizen answers; no live LLM; no household memory writes"
)


def _seed_profile(full: HouseholdProfile, scheme_id: str) -> dict[str, Any] | None:
    """Prefill only application_date when known (APY / NSAP start date)."""

    state = full.facts.get("application_date")
    if state is not None and state.status == "known" and state.value is not None:
        value = state.value
        return {
            "application_date": (
                value.isoformat() if hasattr(value, "isoformat") else str(value)
            ),
        }
    if scheme_id == "APY-IN":
        return {"application_date": date(2026, 10, 30).isoformat()}
    return None


def _card_from_profile(
    persona_id: str, profile: HouseholdProfile, registry: FactRegistry,
) -> HiddenProfileCard:
    facts: dict[str, Any] = {}
    for fact_id, state in profile.facts.items():
        if state.status != "known":
            continue
        value = state.value
        facts[fact_id] = (
            value.isoformat() if hasattr(value, "isoformat") else value
        )
    if not facts:
        facts["__empty__"] = True
    return HiddenProfileCard(citizen_id=persona_id, facts=facts, language="en")


def _reply_for_fact(card: HiddenProfileCard, fact_id: str) -> str:
    reply = answer_question(card, fact_id)
    if reply["status"] != "answered":
        return "I don't know"
    value = reply["value"]
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _build_graph(provider: RulePackageProvider):
    async def eligibility_tool(_client, scheme_id: str, profile: HouseholdProfile):
        return evaluate_mock_eligibility(
            profile, provider.get(scheme_id), registry=provider.registry,
        )

    return build_journey_graph(
        None,
        provider.packages,
        eligibility_tool=eligibility_tool,
        checkpointer=MemorySaver(),
        today=lambda: date(2026, 10, 30),
        fact_registry=provider.registry,
    )


async def _run_interview(
    *,
    provider: RulePackageProvider,
    persona_id: str,
    scheme_id: str,
    full: HouseholdProfile,
    question_order: str,
) -> dict[str, Any]:
    graph = _build_graph(provider)
    card = _card_from_profile(persona_id, full, provider.registry)
    seed = _seed_profile(full, scheme_id)
    response = await run_journey(
        graph,
        JourneyRequest(
            action="interview",
            conversation_id=uuid4(),
            scheme_id=scheme_id,
            profile=seed,
            question_order=question_order,  # type: ignore[arg-type]
        ),
    )
    asked: list[str] = []
    confirmations = 0
    turns = 0

    def _is_confirming() -> bool:
        definition = response.question_definition
        if definition is not None and getattr(definition, "confirming", False):
            return True
        text = (response.question or "").lower()
        return "confirm" in text and "yes" in text and "no" in text

    while response.status == "awaiting_answer" and turns < MAX_TURNS:
        turns += 1
        fact = response.pending_fact
        if _is_confirming():
            confirmations += 1
            response = await resume_journey(
                graph, response.conversation_id, "yes",
            )
            continue
        if not fact:
            break
        if asked and asked[-1] == fact:
            # Unclear/repeat — answer don't-know once then stop if stuck.
            response = await resume_journey(
                graph, response.conversation_id, "I don't know",
            )
            if response.pending_fact == fact and not _is_confirming():
                break
            continue
        asked.append(fact)
        response = await resume_journey(
            graph, response.conversation_id, _reply_for_fact(card, fact),
        )

    verdict = None
    if response.eligibility_result is not None:
        verdict = response.eligibility_result.result
    elif response.status in {"eligible", "not_eligible", "need_more_information"}:
        verdict = response.status

    return {
        "questions": len(asked),
        "asked_facts": asked,
        "confirmations": confirmations,
        "verdict": verdict,
        "status": response.status,
        "decided": verdict is not None and verdict != "need_more_information",
        "question_order": question_order,
        "fixed_questionnaire": fixed_questionnaire_facts(
            [provider.get(scheme_id)], provider.registry,
        ),
    }


async def run_journey_question_order_ablation(
    *,
    eval_path: Path = DEV_PERSONAS,
    allow_held_out: bool = False,
    scheme_ids: set[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Compare journey planned vs fixed question order on a persona set."""

    evaluation_set = load_persona_evaluation_set(
        eval_path, allow_held_out=allow_held_out,
    )
    provider = RulePackageProvider()
    registry = provider.registry
    rows: list[dict[str, Any]] = []

    for persona in evaluation_set.personas:
        full = persona_input(persona, registry)
        for scheme_id, expected in persona.expected_by_scheme.items():
            if scheme_ids is not None and scheme_id not in scheme_ids:
                continue
            planned = await _run_interview(
                provider=provider,
                persona_id=persona.persona_id,
                scheme_id=scheme_id,
                full=full,
                question_order="planned",
            )
            fixed = await _run_interview(
                provider=provider,
                persona_id=persona.persona_id,
                scheme_id=scheme_id,
                full=full,
                question_order="fixed",
            )
            rows.append({
                "persona_id": persona.persona_id,
                "scheme_id": scheme_id,
                "expected_result": expected.result,
                "planned": planned,
                "fixed": fixed,
                "verdict_match": planned["verdict"] == fixed["verdict"],
                "questions_planned": planned["questions"],
                "questions_fixed": fixed["questions"],
            })
            if limit is not None and len(rows) >= limit:
                break
        if limit is not None and len(rows) >= limit:
            break

    count = len(rows)
    return {
        "notice": NOTICE,
        "arm": "journey_question_order",
        "eval_set": str(eval_path),
        "case_count": count,
        "fixed_questions_total": sum(r["questions_fixed"] for r in rows),
        "planned_questions_total": sum(r["questions_planned"] for r in rows),
        "verdict_match_count": sum(1 for r in rows if r["verdict_match"]),
        "questions_per_conversation": {
            "fixed_mean": round(
                sum(r["questions_fixed"] for r in rows) / count, 4,
            ) if count else None,
            "planned_mean": round(
                sum(r["questions_planned"] for r in rows) / count, 4,
            ) if count else None,
        },
        "cases": rows,
    }


def run_journey_question_order_ablation_sync(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(run_journey_question_order_ablation(**kwargs))
