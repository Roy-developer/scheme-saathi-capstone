"""Functional, synthetic memory-on/off smoke for the governed journey flow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from src.api.eligibility import evaluate_mock_eligibility
from src.api.scheme_search import load_passages
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import FactState, HouseholdProfile
from src.workflow.household_memory import save_household
from src.workflow.intake import AnswerInterpretation
from src.workflow.journey import (
    JourneyRequest,
    build_journey_graph,
    resume_journey,
    run_journey,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEME_ID = "IGNWPS-MH"
RETURN_CODE = "SAATHI-AB12CD34EF"


@dataclass(frozen=True)
class SyntheticMemoryCase:
    case_id: str
    bpl_card_shown: bool
    income_tax_paid_last_assessment_year: bool
    is_widow: bool
    date_of_birth: str


SCENARIOS = (
    SyntheticMemoryCase("SYN-MEMORY-001", True, False, True, "01/01/1986"),
    SyntheticMemoryCase("SYN-MEMORY-002", False, False, True, "01/01/1986"),
    SyntheticMemoryCase("SYN-MEMORY-003", True, True, True, "01/01/1986"),
    SyntheticMemoryCase("SYN-MEMORY-004", False, True, False, "01/01/1970"),
)


async def _uncertain_answer(_fact: str, _question: str, _reply: str) -> AnswerInterpretation:
    return AnswerInterpretation(kind="uncertain", confidence=0.0)


def _build_graph(provider: RulePackageProvider):
    passages = load_passages(
        PROJECT_ROOT / "data" / "schemes" / "passages"
    )
    scheme_passages = [p for p in passages if p.scheme_id == SCHEME_ID]

    async def search_tool(_client: object, _query: str) -> list:
        return scheme_passages[:1]

    async def query_rewriter(query: str) -> str:
        return query

    async def eligibility_tool(
        _client: object, scheme_id: str, profile: HouseholdProfile,
    ):
        return evaluate_mock_eligibility(
            profile, provider.packages[scheme_id], registry=provider.registry,
        )

    return build_journey_graph(
        None,
        provider.packages,
        search_tool=search_tool,
        eligibility_tool=eligibility_tool,
        query_rewriter=query_rewriter,
        answer_interpreter=_uncertain_answer,
        checkpointer=MemorySaver(),
    )


async def _finish(
    graph: Any,
    response: Any,
    answers: dict[str, str],
) -> tuple[Any, list[str]]:
    asked: list[str] = []
    while response.status == "awaiting_answer":
        fact = response.pending_fact
        if not fact or fact in asked:
            raise RuntimeError("The synthetic memory interview stalled.")
        asked.append(fact)
        try:
            answer = answers[fact]
        except KeyError as error:
            raise RuntimeError(
                f"No synthetic answer is defined for {fact!r}."
            ) from error
        response = await resume_journey(
            graph, response.conversation_id, answer,
        )
    return response, asked


async def _run_case(
    provider: RulePackageProvider,
    scenario: SyntheticMemoryCase,
) -> dict[str, Any]:
    graph = _build_graph(provider)
    facts = {}
    reusable_facts = {
        "bpl_card_shown": scenario.bpl_card_shown,
        "income_tax_paid_last_assessment_year": (
            scenario.income_tax_paid_last_assessment_year
        ),
    }
    reusable_fact_ids = set(reusable_facts)
    for fact_id, value in reusable_facts.items():
        definition = provider.registry.get(fact_id)
        facts[fact_id] = FactState(
            status="known",
            value=definition.validate_value(value),
            definition_version=definition.version,
            provenance="user_reported",
        )
    profile = HouseholdProfile(
        registry_version=provider.registry.registry_version,
        facts=facts,
    )
    await save_household(
        graph.store,
        RETURN_CODE,
        profile,
        provider.registry,
        memory_consent=True,
    )

    answers = {
        "is_widow": "yes" if scenario.is_widow else "no",
        "date_of_birth": scenario.date_of_birth,
        "bpl_card_shown": "yes" if scenario.bpl_card_shown else "no",
        "income_tax_paid_last_assessment_year": (
            "yes" if scenario.income_tax_paid_last_assessment_year else "no"
        ),
    }
    profile = {"application_date": date(2026, 11, 12).isoformat()}
    memory_on_start = await run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id=SCHEME_ID,
            profile=profile,
            return_code=RETURN_CODE,
            memory_consent=True,
        ),
    )
    memory_off_start = await run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id=SCHEME_ID,
            profile=profile,
            memory_consent=False,
        ),
    )
    memory_on, memory_on_asked = await _finish(graph, memory_on_start, answers)
    memory_off, memory_off_asked = await _finish(graph, memory_off_start, answers)
    if memory_on.eligibility_result is None or memory_off.eligibility_result is None:
        raise RuntimeError("The synthetic memory journeys returned no verdict.")
    return {
        "case_id": scenario.case_id,
        "scheme_id": SCHEME_ID,
        "memory_on": {
            "consent": True,
            "reused_fact_count": len(
                set(memory_on_start.known_fact_names) & reusable_fact_ids
            ),
            "asked_fact_count": len(memory_on_asked),
            "verdict": memory_on.eligibility_result.result,
        },
        "memory_off": {
            "consent": False,
            "reused_fact_count": len(
                set(memory_off_start.known_fact_names) & reusable_fact_ids
            ),
            "asked_fact_count": len(memory_off_asked),
            "verdict": memory_off.eligibility_result.result,
        },
    }


def memory_on_off_report() -> dict[str, Any]:
    """Compare four deterministic synthetic journeys with memory on and off."""

    provider = RulePackageProvider()
    cases = [asyncio.run(_run_case(provider, scenario)) for scenario in SCENARIOS]
    compared_cases = [
        {
            **case,
            "verdicts_match": case["memory_on"]["verdict"] == case["memory_off"]["verdict"],
            "questions_avoided": (
                case["memory_off"]["asked_fact_count"]
                - case["memory_on"]["asked_fact_count"]
            ),
        }
        for case in cases
    ]
    agreement_count = sum(case["verdicts_match"] for case in compared_cases)
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split": "development",
        "model_calls": 0,
        "case_count": len(compared_cases),
        "cases": compared_cases,
        "summary": {
            "case_count": len(compared_cases),
            "verdict_agreement_count": agreement_count,
            "verdict_agreement_rate": agreement_count / len(compared_cases),
            "memory_on_reused_fact_count": sum(
                case["memory_on"]["reused_fact_count"] for case in compared_cases
            ),
            "memory_off_reused_fact_count": sum(
                case["memory_off"]["reused_fact_count"] for case in compared_cases
            ),
            "questions_avoided": sum(
                case["questions_avoided"] for case in compared_cases
            ),
        },
        "claim_boundary": (
            "Four deterministic synthetic functional cases only; not independent "
            "validation, a user study, a security evaluation, or full L9 evidence."
        ),
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
