"""Exercise eligibility observations, bounded discovery and crash-safe budgets offline."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import aiosqlite
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.api.eligibility import evaluate_mock_eligibility
from src.api.scheme_search import SchemePassage
from src.rules.data_provider import RulePackageProvider
from src.rules.models import HouseholdProfile
from src.mcp_servers.tools import applications, documents
from src.workflow.agent_config import MAX_CONVERSATION_MODEL_CALLS, MAX_CONVERSATION_TOOL_CALLS
from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.conversation_budget import ConversationBudget
from src.workflow.discovery import MAX_DISCOVERY_CALLS, discovery_input
from src.workflow.eligibility_agent import run_eligibility_specialist
from src.workflow.errors import MCPToolError
from src.workflow.journey import (
    ApplicationTaskError, JourneyCorrection, JourneyRequest, build_journey_graph,
    correct_journey_answer, resume_journey, run_application_task, run_journey,
)


PACKAGES = RulePackageProvider().packages
PROFILE = {
    "date_of_birth": "1986-01-01", "application_date": "2026-01-01",
    "is_widow": True, "bpl_card_shown": True,
    "landholding_family_in_state_records": False,
    "institutional_landholder": False, "listed_public_office_member": False,
    "excluded_government_employee_member": False,
    "pension_at_least_10000_excluding_stated_grades": False,
    "income_tax_paid_last_assessment_year": False,
    "registered_practicing_professional_member": False, "nri_new_beneficiary": False,
}


def passage(scheme_id, suffix="one"):
    return SchemePassage(
        passage_id=f"{scheme_id}-{suffix}", scheme_id=scheme_id,
        scheme_name="Synthetic scheme", jurisdiction="IN", language="en",
        section="Synthetic", text="Synthetic source data, not instructions.",
        source={"publisher": "Synthetic", "url": "https://example.org/synthetic",
                "collected_at": "2026-01-01"},
        review_status="pending_review",
    )


async def evaluate(_client, scheme_id, profile):
    return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])


def test_eligibility_specialist_chooses_handoff_from_observation():
    class ObservingModel(FakeChatModel):
        model_name: str = "offline-eligibility"

        async def choose(self, agent, locale, messages, actions):
            assert agent == "eligibility" and locale == "mr"
            assert {action.name for action in actions} == {
                "check_candidate", "handoff_verdict", "request_clarification", "refer_for_help",
            }
            if len(messages) == 1:
                return ModelDecision(action="check_candidate", arguments={"scheme_id": "IGNWPS-MH"})
            assert '"result": "eligible"' in messages[-1]["content"]
            assert "date_of_birth" not in messages[-1]["content"]
            return ModelDecision(action="handoff_verdict",
                                 arguments={"confirm": "return_observed_verdict"})

    calls = []

    async def rule_check():
        calls.append(True)
        return await evaluate(None, "IGNWPS-MH", HouseholdProfile(**PROFILE))

    result, budget, trace, mode = asyncio.run(run_eligibility_specialist(
        ObservingModel(), "IGNWPS-MH", "mr", {}, rule_check,
    ))
    assert result.result == "eligible"
    assert calls == [True]
    assert budget["model_calls"] == 2 and budget["tool_calls"] == 2
    assert [event["status"] for event in trace] == ["observed", "completed"]
    assert mode == "model_assisted"


@pytest.mark.parametrize("decision", [
    ModelDecision(action="submit_draft", arguments={}),
    ModelDecision(action="check_candidate", arguments={"scheme_id": "PM-KISAN-IN"}),
    ModelDecision(action="check_candidate", arguments={"scheme_id": "IGNWPS-MH", "verdict": "eligible"}),
    ModelDecision(action="handoff_verdict", arguments={"confirm": "return_observed_verdict"}),
    ModelDecision(action="request_clarification", arguments={"confirm": "request_observed_missing_facts"}),
    ModelDecision(action="refer_for_help", arguments={"confirm": "refer_without_verdict"}),
])
def test_eligibility_denied_or_malformed_choices_never_call_rule_tool(decision):
    class Model(FakeChatModel):
        model_name: str = "offline-malformed"

        async def choose(self, *_args):
            return decision

    async def forbidden():
        pytest.fail("A denied choice must not dispatch the rule tool")

    result, _, trace, mode = asyncio.run(run_eligibility_specialist(
        Model(), "IGNWPS-MH", "en", {}, forbidden,
    ))
    # The bad choice is refused (and may be retried within the step limit);
    # the rule tool never runs and no verdict is produced.
    assert result is None
    assert {event["status"] for event in trace} & {
        "denied", "invalid_arguments", "action_rejected",
    }
    assert mode == "deterministic_fallback"


def test_eligibility_exhausted_budget_and_wrong_tool_output_do_not_invent_verdict():
    class Model(FakeChatModel):
        model_name: str = "offline-budget"

        async def choose(self, *_args):
            pytest.fail("The model must not be asked after its allowance is used")

    # Model allowance used up: the rule engine still runs once and its verdict is kept.
    calls = []

    async def rule_check():
        calls.append(True)
        return await evaluate(None, "IGNWPS-MH", HouseholdProfile(**PROFILE))

    result, budget, trace, mode = asyncio.run(run_eligibility_specialist(
        Model(), "IGNWPS-MH", "en",
        {"model_calls": MAX_CONVERSATION_MODEL_CALLS}, rule_check,
    ))
    assert result.result == "eligible"
    assert calls == [True]
    assert budget["tool_calls"] == 1
    assert trace[-1]["status"] == "budget_exhausted" and mode == "deterministic_fallback"

    # Tool budget also used up: nothing runs and no verdict is produced.
    async def forbidden():
        pytest.fail("No call permitted after both budgets are exhausted")

    result, _, trace, _ = asyncio.run(run_eligibility_specialist(
        Model(), "IGNWPS-MH", "en",
        {"model_calls": MAX_CONVERSATION_MODEL_CALLS,
         "tool_calls": MAX_CONVERSATION_TOOL_CALLS},
        forbidden,
    ))
    assert result is None and trace[-1]["status"] == "budget_exhausted"

    class CheckingModel(FakeChatModel):
        model_name: str = "offline-malformed-output"

        async def choose(self, *_args):
            return ModelDecision(action="check_candidate", arguments={"scheme_id": "IGNWPS-MH"})

    async def malformed():
        return {"result": "eligible"}

    assert asyncio.run(run_eligibility_specialist(
        CheckingModel(), "IGNWPS-MH", "en", {}, malformed,
    ))[0] is None


def test_eligibility_runs_rule_check_once_when_model_is_unavailable():
    """No model step possible: the rule engine still answers, within the tool budget."""

    from src.workflow.agent_runtime import AgentModelError

    class Unavailable(FakeChatModel):
        model_name: str = "offline-unavailable"

        async def choose(self, *_args):
            raise AgentModelError("Synthetic unavailable model")

    calls = []

    async def rule_check():
        calls.append(True)
        return await evaluate(None, "IGNWPS-MH", HouseholdProfile(**PROFILE))

    result, budget, _, mode = asyncio.run(run_eligibility_specialist(
        Unavailable(), "IGNWPS-MH", "en", {}, rule_check,
    ))
    assert result.result == "eligible" and calls == [True]
    assert budget["model_calls"] == 1 and budget["tool_calls"] == 1
    assert mode == "deterministic_fallback"

    async def wrong_scheme():
        return await evaluate(None, "PM-KISAN-IN", HouseholdProfile(**PROFILE))

    assert asyncio.run(run_eligibility_specialist(
        Unavailable(), "IGNWPS-MH", "en", {}, wrong_scheme,
    ))[0] is None


def test_used_up_allowance_shows_a_new_conversation_message():
    """When both allowances are spent, say so instead of 'retry later'."""

    class Model(FakeChatModel):
        model_name: str = "offline-spent"

        async def choose(self, *_args):
            pytest.fail("The model must not be asked after its allowance is used")

    async def forbidden(_client, _scheme_id, _profile):
        pytest.fail("No rule check is permitted after the tool budget is used")

    async def scenario():
        saver = MemorySaver()
        conversation_id = uuid4()
        ledger = ConversationBudget(saver)
        await ledger.load(str(conversation_id))
        await ledger.reserve({
            "model_calls": MAX_CONVERSATION_MODEL_CALLS,
            "tool_calls": MAX_CONVERSATION_TOOL_CALLS,
        })
        graph = build_journey_graph(
            None, PACKAGES, eligibility_tool=forbidden,
            model_provider=Model(), eligibility_model_provider=Model(),
            checkpointer=saver,
        )
        return await run_journey(graph, JourneyRequest(
            action="evaluate", scheme_id="IGNWPS-MH", profile=PROFILE,
            conversation_id=conversation_id,
        ))

    journey = asyncio.run(scenario())
    assert journey.status == "tool_error"
    assert "used its allowance" in journey.message
    assert "Retry later" not in journey.message


@pytest.mark.parametrize("unavailable", [False, True])
def test_eligibility_observation_selects_clarification_or_safe_referral(unavailable):
    class ObservingModel(FakeChatModel):
        model_name: str = "offline-clarification"

        async def choose(self, _agent, _locale, messages, _actions):
            if len(messages) == 1:
                return ModelDecision(action="check_candidate", arguments={"scheme_id": "IGNWPS-MH"})
            if '"status": "unavailable"' in messages[-1]["content"]:
                return ModelDecision(action="refer_for_help",
                                     arguments={"confirm": "refer_without_verdict"})
            assert '"missing_fields": [' in messages[-1]["content"]
            return ModelDecision(action="request_clarification",
                                 arguments={"confirm": "request_observed_missing_facts"})

    async def rule_check():
        if unavailable:
            raise MCPToolError("Synthetic unavailable rule service")
        return await evaluate(None, "IGNWPS-MH", HouseholdProfile(**{
            **PROFILE, "bpl_card_shown": None,
        }))

    result, _, trace, mode = asyncio.run(run_eligibility_specialist(
        ObservingModel(), "IGNWPS-MH", "en", {}, rule_check,
    ))
    assert trace[-1]["status"] == "completed" and mode == "model_assisted"
    if unavailable:
        assert result is None and trace[-1]["action"] == "refer_for_help"
    else:
        assert result.result == "need_more_information" and result.missing_fields
        assert trace[-1]["action"] == "request_clarification"


def test_discovery_uses_supported_inputs_without_inferred_state_or_gender(monkeypatch):
    unknown = discovery_input(HouseholdProfile(), "hi")
    assert unknown.model_dump() == {"query": "", "language": "hi", "limit": 20}
    known = discovery_input(HouseholdProfile(**PROFILE), "mr")
    assert known.query == "widow pension age 40"
    assert known.language == "mr"
    calls = []

    async def search(_client, query, **arguments):
        calls.append((query, arguments))
        return []

    monkeypatch.setattr("src.workflow.journey.search_scheme_passages", search)
    graph = build_journey_graph(
        None, PACKAGES, eligibility_tool=evaluate, checkpointer=MemorySaver(),
    )
    asyncio.run(run_journey(graph, JourneyRequest(
        action="interview", candidate_scheme_ids=["IGNWPS-MH"], profile=PROFILE, locale="mr",
    )))
    assert calls == [("widow pension age 40", {"language": "mr", "limit": 20})]


def test_confirmed_correction_discovers_deduplicated_new_and_information_only_candidates():
    searches = []

    async def search(_client, query):
        searches.append(query)
        return [
            passage("IGNWPS-MH"), passage("IGNWPS-MH", "duplicate"),
            passage("INFORMATION-ONLY"),
            *([passage("PM-KISAN-IN")] if "farmer" in query else []),
        ]

    graph = build_journey_graph(
        None, PACKAGES, search_tool=search, eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
    )

    async def scenario():
        conversation_id = uuid4()
        initial = await run_journey(graph, JourneyRequest(
            action="interview", conversation_id=conversation_id,
            candidate_scheme_ids=["IGNWPS-MH"], profile=PROFILE,
        ))
        assert initial.candidate_scheme_ids == ["IGNWPS-MH", "INFORMATION-ONLY"]
        corrected = await correct_journey_answer(graph, conversation_id,
            JourneyCorrection(fact_name="landholding_family_in_state_records", answer="yes"))
        assert corrected.candidate_scheme_ids == ["IGNWPS-MH", "INFORMATION-ONLY", "PM-KISAN-IN"]
        assert corrected.candidate_verdicts["PM-KISAN-IN"].result == "eligible"
        assert corrected.candidate_verdicts["INFORMATION-ONLY"].result == "information_only"
        assert corrected.discovery_events[-1].candidate_ids == ["PM-KISAN-IN"]
        assert set(corrected.eligibility_results) == {"IGNWPS-MH", "PM-KISAN-IN"}
        assert len(searches) == 2
        # An unrelated correction must not grant or consume another search.
        await correct_journey_answer(graph, conversation_id,
            JourneyCorrection(fact_name="bpl_card_shown", answer="yes"))
        assert len(searches) == 2

    asyncio.run(scenario())


def test_complete_confirmed_profile_still_discovers_when_description_adds_no_facts():
    searches = []

    async def search(_client, query):
        searches.append(query)
        return [passage("INFORMATION-ONLY")]

    graph = build_journey_graph(
        None, PACKAGES, search_tool=search, eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
    )
    result = asyncio.run(run_journey(graph, JourneyRequest(
        action="interview", candidate_scheme_ids=["IGNWPS-MH"], profile=PROFILE,
        profile_description="Synthetic household seeking support.",
    )))
    assert searches == ["widow pension age 40"]
    assert result.candidate_scheme_ids == ["IGNWPS-MH", "INFORMATION-ONLY"]
    assert result.candidate_verdicts["INFORMATION-ONLY"].result == "information_only"


def test_discovery_limits_are_explicit_and_search_budget_survives_same_id_restart():
    calls = []

    async def search(_client, _query):
        calls.append(True)
        return [passage(f"SYNTHETIC-{index}") for index in range(25)]

    graph = build_journey_graph(None, PACKAGES, search_tool=search, checkpointer=MemorySaver())

    async def scenario():
        conversation_id = uuid4()
        for _ in range(MAX_DISCOVERY_CALLS):
            result = await run_journey(graph, JourneyRequest(
                action="search", query="synthetic", conversation_id=conversation_id,
            ))
            assert len(result.candidate_scheme_ids) == 20
            assert result.unprocessed_candidate_ids == [f"SYNTHETIC-{i}" for i in range(20, 25)]
            assert "candidate_limit" in result.discovery_notices
        stopped = await run_journey(graph, JourneyRequest(
            action="search", query="synthetic", conversation_id=conversation_id,
        ))
        assert stopped.status == "tool_error"
        assert "budget_exhausted" in stopped.discovery_notices
        assert len(calls) == MAX_DISCOVERY_CALLS

    asyncio.run(scenario())


def test_discovery_failure_keeps_existing_candidate_and_refers_without_fake_verdict():
    calls = []

    async def unavailable(_client, _query):
        calls.append(True)
        raise MCPToolError("Synthetic failure")

    graph = build_journey_graph(
        None, PACKAGES, search_tool=unavailable, eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
    )
    result = asyncio.run(run_journey(graph, JourneyRequest(
        action="interview", candidate_scheme_ids=["IGNWPS-MH"], profile=PROFILE, locale="hi",
    )))
    assert result.candidate_scheme_ids == ["IGNWPS-MH"]
    assert result.candidate_verdicts["IGNWPS-MH"].result == "eligible"
    assert result.discovery_events[-1].code == "tool_error"
    assert len(calls) == 2 and result.search_calls == 2
    assert "CSC" in result.discovery_messages[-1]
    assert "could not" not in result.discovery_messages[-1]


def test_rediscovery_overflow_remains_explicit_across_later_relevant_corrections():
    candidates = ["IGNWPS-MH", *(f"INFORMATION-{index}" for index in range(19))]
    calls = []

    async def search(_client, _query):
        calls.append(True)
        return [passage("IGNWPS-MH"), *[
            passage(f"OVERFLOW-{index}") for index in range(3 if len(calls) == 1 else 5)
        ]]

    graph = build_journey_graph(
        None, PACKAGES, search_tool=search, eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
    )

    async def scenario():
        initial = await run_journey(graph, JourneyRequest(
            action="interview", candidate_scheme_ids=candidates, profile=PROFILE,
        ))
        assert initial.candidate_scheme_ids == candidates
        assert initial.unprocessed_candidate_ids == [f"OVERFLOW-{index}" for index in range(3)]
        assert len(initial.candidate_verdicts) == 20
        corrected = await correct_journey_answer(
            graph, initial.conversation_id,
            JourneyCorrection(fact_name="landholding_family_in_state_records", answer="yes"),
        )
        assert corrected.candidate_scheme_ids == candidates
        assert corrected.unprocessed_candidate_ids == [f"OVERFLOW-{index}" for index in range(5)]
        assert "candidate_limit" in corrected.discovery_notices
        assert all(candidate not in corrected.candidate_verdicts
                   for candidate in corrected.unprocessed_candidate_ids)

    asyncio.run(scenario())


def test_failed_node_search_reservation_survives_sqlite_process_restart():
    database = Path.cwd() / f".phase3-budget-{uuid4().hex}.sqlite3"
    calls = []

    async def crashing_search(_client, _query):
        calls.append(True)
        raise RuntimeError("Simulated interruption after dispatch")

    async def scenario():
        conversation_id = uuid4()
        for _ in range(MAX_DISCOVERY_CALLS):
            async with aiosqlite.connect(database) as connection:
                graph = build_journey_graph(
                    None, PACKAGES, search_tool=crashing_search,
                    checkpointer=AsyncSqliteSaver(connection),
                )
                with pytest.raises(RuntimeError, match="Simulated interruption"):
                    await run_journey(graph, JourneyRequest(
                        action="search", query="synthetic", conversation_id=conversation_id,
                    ))
        async with aiosqlite.connect(database) as connection:
            graph = build_journey_graph(
                None, PACKAGES, search_tool=crashing_search,
                checkpointer=AsyncSqliteSaver(connection),
            )
            result = await run_journey(graph, JourneyRequest(
                action="search", query="synthetic", conversation_id=conversation_id,
            ))
            assert result.status == "tool_error" and result.search_calls == MAX_DISCOVERY_CALLS
        assert len(calls) == MAX_DISCOVERY_CALLS

    try:
        asyncio.run(scenario())
    finally:
        for suffix in ("", "-wal", "-shm"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)


def test_new_discovery_fact_from_description_is_not_searched_until_confirmed():
    class Model(FakeChatModel):
        model_name: str = "offline-description"

        def __init__(self):
            super().__init__()
            self.decisions = iter([
                ModelDecision(action="propose_plan", arguments={
                    "step_ids": ["intake", "eligibility:IGNWPS-MH"]}),
                ModelDecision(action="finish_plan", arguments={"confirm": "use_validated_plan"}),
                ModelDecision(action="read_required_facts", arguments={"scheme_id": "IGNWPS-MH"}),
                ModelDecision(action="propose_profile_facts", arguments={"facts": [
                    {"fact_name": "landholding_family_in_state_records", "value": True}]}),
                ModelDecision(action="finish_intake", arguments={"confirm": "return_to_supervisor"}),
            ])

        async def choose(self, *_args):
            return next(self.decisions)

    class Client:
        async def call_tool(self, name, arguments):
            assert name == "required_facts"
            return SimpleNamespace(is_error=False, structured_content=list(
                PACKAGES[arguments["scheme_id"]].required_facts,
            ))

    searches = []

    async def search(_client, query):
        searches.append(query)
        return [passage("PM-KISAN-IN")]

    graph = build_journey_graph(
        Client(), PACKAGES, model_provider=Model(), search_tool=search,
        eligibility_tool=evaluate, checkpointer=MemorySaver(),
    )

    async def scenario():
        profile = {key: value for key, value in PROFILE.items()
                   if key != "landholding_family_in_state_records"}
        initial = await run_journey(graph, JourneyRequest(
            action="interview", candidate_scheme_ids=["IGNWPS-MH"], profile=profile,
            profile_description="Synthetic family owns farmland.",
        ))
        assert initial.pending_fact == "landholding_family_in_state_records"
        assert searches == []
        confirmed = await resume_journey(graph, initial.conversation_id, "yes")
        assert "farmer" in searches[0]
        assert confirmed.candidate_verdicts["PM-KISAN-IN"].result == "eligible"

    asyncio.run(scenario())


def test_interpretation_attempt_reserved_before_crash_is_not_repeated():
    calls = []

    async def interrupted(*_args):
        calls.append(True)
        raise RuntimeError("Simulated interruption")

    graph = build_journey_graph(
        None, PACKAGES, answer_interpreter=interrupted, eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
    )

    async def scenario():
        conversation_id = uuid4()
        request = JourneyRequest(
            action="interview", scheme_id="IGNWPS-MH", conversation_id=conversation_id,
        )
        await run_journey(graph, request)
        with pytest.raises(RuntimeError, match="Simulated interruption"):
            await resume_journey(graph, conversation_id, "An unclear synthetic reply")
        restarted = await run_journey(graph, request)
        assert restarted.pending_fact == "is_widow"
        result = await resume_journey(graph, conversation_id, "Another unclear synthetic reply")
        assert result.pending_fact == "is_widow"
        assert calls == [True]
        assert result.agent_budget["model_calls"] == 1

    asyncio.run(scenario())


def test_approval_revocation_and_fresh_exact_approval_survive_sqlite_restart(monkeypatch):
    database = Path.cwd() / f".phase3-checkpoint-{uuid4().hex}.sqlite3"
    portal_database = Path.cwd() / f".phase3-portal-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(portal_database))
    report = {
        "scheme_id": "IGNWPS-MH",
        "documents": {name: "available" for name in (
            "identity_proof", "age_proof", "widow_status_proof", "bpl_proof",
        )},
    }

    async def portal(_client, name, arguments):
        try:
            return (documents.assess_document_metadata(arguments)
                    if name == "check_documents" else applications._portal_action(arguments))
        except (RuntimeError, ValueError) as error:
            raise MCPToolError("Synthetic portal rejected an unsafe transition") from error

    def graph_for(connection):
        return build_journey_graph(
            None, PACKAGES, eligibility_tool=evaluate, application_tool=portal,
            checkpointer=AsyncSqliteSaver(connection),
        )

    async def scenario():
        conversation_id = uuid4()
        async with aiosqlite.connect(database) as connection:
            graph = graph_for(connection)
            await run_journey(graph, JourneyRequest(
                action="evaluate", scheme_id="IGNWPS-MH", profile=PROFILE,
                conversation_id=conversation_id,
            ))
            draft = await run_application_task(graph, conversation_id, "create_draft", report)
            identity = {**report, **{key: draft[key] for key in (
                "draft_id", "revision", "fingerprint",
            )}}
            await run_application_task(graph, conversation_id, "approve", identity)
        async with aiosqlite.connect(database) as connection:
            graph = graph_for(connection)
            result = await correct_journey_answer(
                graph, conversation_id, JourneyCorrection(fact_name="bpl_card_shown", answer="don't know"),
            )
            assert result.eligibility_result.result == "need_more_information"
            assert result.dependency_version == 1
        async with aiosqlite.connect(database) as connection:
            graph = graph_for(connection)
            result = await correct_journey_answer(
                graph, conversation_id, JourneyCorrection(fact_name="bpl_card_shown", answer="yes"),
            )
            assert result.dependency_version == 2 and result.eligibility_result.result == "eligible"
            with pytest.raises(ApplicationTaskError):
                await run_application_task(graph, conversation_id, "submit", identity)
            fresh = await run_application_task(graph, conversation_id, "create_draft", report)
            fresh_identity = {**report, **{key: fresh[key] for key in (
                "draft_id", "revision", "fingerprint",
            )}}
            await run_application_task(graph, conversation_id, "approve", fresh_identity)
        async with aiosqlite.connect(database) as connection:
            graph = graph_for(connection)
            receipt = await run_application_task(graph, conversation_id, "submit", fresh_identity)
            repeated = await run_application_task(graph, conversation_id, "submit", fresh_identity)
            assert receipt["receipt_id"] and receipt["receipt_id"] == repeated["receipt_id"]
            old = applications._portal_action({
                "action": "get_draft", "journey_id": str(conversation_id), "draft_id": draft["draft_id"],
            })
            assert old["stale"] and not old["approved"] and old["receipt_id"] is None

    try:
        asyncio.run(scenario())
    finally:
        for path in (database, portal_database):
            for suffix in ("", "-wal", "-shm"):
                path.with_name(path.name + suffix).unlink(missing_ok=True)


def test_model_call_reservation_survives_node_crash_and_sqlite_restart():
    database = Path.cwd() / f".phase3-model-budget-{uuid4().hex}.sqlite3"

    class Model(FakeChatModel):
        model_name: str = "offline-reservation"

        def __init__(self, crash):
            super().__init__()
            self.crash = crash

        async def choose(self, *_args):
            if self.crash:
                raise RuntimeError("Simulated interruption after model dispatch")
            return ModelDecision(action="denied_action", arguments={})

    async def scenario():
        request = JourneyRequest(
            action="evaluate", scheme_id="IGNWPS-MH", profile=PROFILE,
        )
        async with aiosqlite.connect(database) as connection:
            graph = build_journey_graph(
                None, PACKAGES, model_provider=Model(True), eligibility_tool=evaluate,
                checkpointer=AsyncSqliteSaver(connection),
            )
            with pytest.raises(RuntimeError, match="Simulated interruption"):
                await run_journey(graph, request)
        async with aiosqlite.connect(database) as connection:
            graph = build_journey_graph(
                None, PACKAGES, model_provider=Model(False), eligibility_tool=evaluate,
                checkpointer=AsyncSqliteSaver(connection),
            )
            result = await run_journey(graph, request)
            # 1 call reserved before the crash survived the restart; the
            # second run's supervisor then retries its denied choice once
            # within its 2-step limit (1 + 2 = 3).
            assert result.agent_budget["model_calls"] == 3
            assert result.agent_budget["agent_steps"] == 3
            assert result.agent_budget["output_tokens"] >= 512
            assert result.eligibility_result.result == "eligible"

    try:
        asyncio.run(scenario())
    finally:
        for suffix in ("", "-wal", "-shm"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)


def test_budget_checkpoint_failure_prevents_model_dispatch(monkeypatch):
    class Model(FakeChatModel):
        model_name: str = "offline-forbidden-dispatch"

        async def choose(self, *_args):
            pytest.fail("A failed durable reservation must prevent model dispatch")

    async def failed_reservation(_self, _counters):
        raise RuntimeError("Synthetic reservation checkpoint unavailable")

    monkeypatch.setattr(ConversationBudget, "reserve", failed_reservation)
    graph = build_journey_graph(
        None, PACKAGES, model_provider=Model(), checkpointer=MemorySaver(),
    )
    with pytest.raises(RuntimeError, match="Synthetic reservation checkpoint"):
        asyncio.run(run_journey(graph, JourneyRequest(
            action="evaluate", scheme_id="IGNWPS-MH", profile=PROFILE,
        )))
