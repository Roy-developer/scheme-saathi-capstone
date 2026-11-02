import asyncio
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from src.api.eligibility import EligibilityResponse
from src.api.scheme_search import load_passages
from src.rules.data_provider import RulePackageProvider
from src.workflow.journey import (
    JourneyRequest,
    build_journey_graph,
    run_journey,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = RulePackageProvider().packages
PASSAGES = load_passages(ROOT / "data" / "schemes" / "passages.json")


def build_graph(*, eligibility_tool=None):
    async def search_tool(_client, query):
        assert query == "widow pension"
        return [PASSAGES[0]]

    async def identity_rewriter(query):
        return query

    async def fake_eligibility(_client, scheme_id, _profile):
        if eligibility_tool is not None:
            return await eligibility_tool(_client, scheme_id, _profile)
        return EligibilityResponse(
            scheme_id=scheme_id,
            result="eligible",
            reason="Deterministic test result.",
            age_on_application_date=40,
            missing_fields=[],
            deciding_rule_ids=["IGNWPS-MH-AGE-MIN-01"],
            evidence=[],
        )

    return build_journey_graph(
        None,
        PACKAGES,
        search_tool=search_tool,
        eligibility_tool=fake_eligibility,
        query_rewriter=identity_rewriter,
        checkpointer=MemorySaver(),
    )


def test_search_flow_routes_through_intake_and_returns_citations():
    graph = build_graph()
    result = asyncio.run(
        run_journey(
            graph,
            JourneyRequest(action="search", query="widow pension"),
        )
    )

    assert result.status == "search_results"
    assert result.plan
    assert result.passages[0].passage_id == PASSAGES[0].passage_id
    assert any(turn["role"] == "user" for turn in result.conversation)


def test_eligibility_flow_uses_rule_tool_and_returns_its_verdict():
    graph = build_graph()
    result = asyncio.run(
        run_journey(
            graph,
            JourneyRequest(
                action="evaluate",
                scheme_id="IGNWPS-MH",
                profile={
                    "date_of_birth": "1986-10-30",
                    "application_date": "2026-10-30",
                    "is_widow": True,
                    "bpl_card_shown": True,
                },
            ),
        )
    )

    assert result.status == "eligible"
    assert result.eligibility_result is not None
    assert result.eligibility_result.reason == "Deterministic test result."


def test_information_only_scheme_never_calls_eligibility_tool():
    called = False

    async def forbidden_eligibility(_client, _scheme_id, _profile):
        nonlocal called
        called = True
        raise AssertionError("information-only scheme must not be evaluated")

    graph = build_graph(eligibility_tool=forbidden_eligibility)
    result = asyncio.run(
        run_journey(
            graph,
            JourneyRequest(
                action="evaluate",
                # Any scheme without a rule package is information-only.
                scheme_id="PMAY-G-IN",
                profile={
                    "date_of_birth": "1986-10-30",
                    "application_date": "2026-10-30",
                    "is_widow": True,
                    "bpl_card_shown": True,
                },
            ),
        )
    )

    assert result.status == "information_only"
    assert result.eligibility_result is None
    assert called is False


def test_intake_requests_missing_synthetic_profile_facts():
    result = asyncio.run(
        run_journey(
            build_graph(),
            JourneyRequest(action="evaluate", scheme_id="IGNWPS-MH"),
        )
    )

    assert result.status == "need_information"
    assert "date_of_birth" in result.missing_fields


def test_checkpointer_preserves_conversation_for_follow_up_step():
    graph = build_graph()
    conversation_id = uuid4()
    first = asyncio.run(
        run_journey(
            graph,
            JourneyRequest(
                action="search",
                conversation_id=conversation_id,
                query="widow pension",
            ),
        )
    )
    second = asyncio.run(
        run_journey(
            graph,
            JourneyRequest(
                action="evaluate",
                conversation_id=conversation_id,
                scheme_id="IGNWPS-MH",
                profile={
                    "date_of_birth": "1986-10-30",
                    "application_date": "2026-10-30",
                    "is_widow": True,
                    "bpl_card_shown": True,
                },
            ),
        )
    )

    assert len(second.conversation) > len(first.conversation)
    assert any(
        turn["content"] == "widow pension"
        for turn in second.conversation
    )
