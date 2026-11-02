import asyncio
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.api.eligibility import EligibilityResponse, evaluate_mock_eligibility
from src.api.scheme_search import load_passages
from src.rules.data_provider import RulePackageProvider
from src.workflow.journey import (
    JourneyNotWaitingError,
    JourneyRequest,
    build_journey_graph,
    get_journey,
    resume_journey,
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


# ---- Phase 2: supervisor plan and question-by-question interviews ----


def build_interview_graph():
    """Graph using the real rule engine and a fixed application date."""

    async def real_engine(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])

    return build_graph(eligibility_tool=real_engine)


def interview(graph, scheme_id, answers):
    """Start an interview, send each answer, and return every response."""

    async def run():
        responses = [
            await run_journey(
                graph,
                JourneyRequest(
                    action="interview",
                    scheme_id=scheme_id,
                    profile={"application_date": "2026-10-30"},
                ),
            )
        ]
        for answer in answers:
            responses.append(
                await resume_journey(
                    graph, responses[0].conversation_id, answer
                )
            )
        return responses

    return asyncio.run(run())


def test_interview_asks_one_question_at_a_time_until_eligible():
    responses = interview(
        build_interview_graph(), "IGNWPS-MH", ["yes", "30/10/1976", "yes"]
    )

    assert [r.pending_fact for r in responses[:3]] == [
        "is_widow",
        "date_of_birth",
        "bpl_card_shown",
    ]
    assert all(r.status == "awaiting_answer" for r in responses[:3])
    final = responses[-1]
    assert final.status == "eligible"
    assert final.question is None
    assert [s.status for s in final.plan_detail.steps] == ["done", "done"]


def test_interview_plan_is_visible_while_waiting():
    first = interview(build_interview_graph(), "IGNWPS-MH", [])[0]

    assert [(s.step_id, s.status) for s in first.plan_detail.steps] == [
        ("intake", "in_progress"),
        ("eligibility", "pending"),
    ]


def test_unclear_answer_repeats_the_question_with_a_hint():
    responses = interview(build_interview_graph(), "IGNWPS-MH", ["maybe"])

    assert responses[1].pending_fact == "is_widow"
    assert "Please answer" in responses[1].question


def test_impossible_date_is_rejected_and_asked_again():
    responses = interview(
        build_interview_graph(), "IGNWPS-MH", ["yes", "01/01/2030"]
    )

    assert responses[2].pending_fact == "date_of_birth"
    assert "date of birth cannot be after application date" in (
        responses[2].question
    )


def test_dont_know_is_not_asked_again_and_ends_with_missing_facts():
    responses = interview(
        build_interview_graph(),
        "IGNWPS-MH",
        ["I don't know", "30/10/1976", "not sure"],
    )

    asked = [r.pending_fact for r in responses if r.pending_fact]
    assert asked == ["is_widow", "date_of_birth", "bpl_card_shown"]
    final = responses[-1]
    assert final.status == "need_more_information"
    assert set(final.missing_fields) == {"is_widow", "government_bpl_card"}


def test_failed_rule_stops_the_questions_early():
    # Ramesh: has land, then says he paid income tax.
    responses = interview(
        build_interview_graph(),
        "PM-KISAN-IN",
        ["yes", "no", "no", "no", "no", "yes"],
    )

    final = responses[-1]
    assert final.status == "not_eligible"
    assert final.eligibility_result.deciding_rule_ids == [
        "PMKISAN-INCOME-TAX-01"
    ]


def test_reply_when_not_waiting_is_refused():
    graph = build_interview_graph()
    responses = interview(graph, "IGNWPS-MH", ["no"])
    assert responses[-1].status == "not_eligible"

    with pytest.raises(JourneyNotWaitingError):
        asyncio.run(
            resume_journey(graph, responses[0].conversation_id, "yes")
        )


def test_saved_interview_can_be_reloaded_after_refresh():
    graph = build_interview_graph()
    responses = interview(graph, "IGNWPS-MH", ["yes"])

    saved = asyncio.run(get_journey(graph, responses[0].conversation_id))

    assert saved.status == "awaiting_answer"
    assert saved.pending_fact == "date_of_birth"
    assert asyncio.run(get_journey(graph, uuid4())) is None


def test_new_request_replaces_a_waiting_question():
    graph = build_interview_graph()
    first = interview(graph, "IGNWPS-MH", [])[0]

    result = asyncio.run(
        run_journey(
            graph,
            JourneyRequest(
                action="interview",
                conversation_id=first.conversation_id,
                scheme_id="PM-KISAN-IN",
            ),
        )
    )

    assert result.pending_fact == "landholding_family_in_state_records"
    assert [s.scheme_id for s in result.plan_detail.steps] == [
        "PM-KISAN-IN",
        "PM-KISAN-IN",
    ]


def test_interview_defaults_application_date_to_today():
    async def real_engine(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])

    graph = build_journey_graph(
        None,
        PACKAGES,
        eligibility_tool=real_engine,
        checkpointer=MemorySaver(),
        today=lambda: date(2026, 10, 30),
    )

    async def run():
        start = await run_journey(
            graph,
            JourneyRequest(action="interview", scheme_id="IGNWPS-MH"),
        )
        for answer in ["yes", "30/10/1986", "yes"]:
            result = await resume_journey(graph, start.conversation_id, answer)
        return result

    result = asyncio.run(run())

    assert result.eligibility_result.age_on_application_date == 40
