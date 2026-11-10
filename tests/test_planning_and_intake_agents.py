"""Verify bounded model-selected planning and confirmed profile extraction."""

import asyncio
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import aiosqlite
import httpx
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from src.api.eligibility import EligibilityResponse, evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import HouseholdProfile

_REGISTRY = RulePackageProvider().registry


def household_profile(**facts) -> HouseholdProfile:
    """Confirmed answers for a test, keyed by fact ID."""

    return HouseholdProfile.from_answers(facts, _REGISTRY)
from fake_chat_model import FakeChatModel, ModelDecision
from langchain_core.tools import tool
from src.workflow.agent_runtime import (
    AgentModelError,
    AgentSchema,
    observation,
    run_accounted_model_call,
    run_agent,
)
from src.workflow.agent_config import (
    MAX_CONVERSATION_AGENT_STEPS,
    MAX_CONVERSATION_MODEL_CALLS,
    MAX_CONVERSATION_TOOL_CALLS,
)
from src.workflow.intake import AnswerInterpretation, interpret_free_text_answer
from src.workflow.journey import (
    JourneyCorrection,
    JourneyRequest,
    build_journey_graph,
    correct_journey_answer,
    resume_journey,
    run_journey,
)
from src.workflow.supervisor_agent import (
    FinishPlanArguments,
    FinishPlanObservation,
    PlanProposalArguments,
    PlanProposalObservation,
    propose_supervisor_plan,
)
from src.workflow.supervisor import build_initial_plan


PACKAGES = RulePackageProvider().packages


class ScriptedProvider(FakeChatModel):
    """Return predetermined tool choices without network access."""

    model_name: str = "fake-phase2-model"

    def __init__(self, choices: list[ModelDecision]) -> None:
        super().__init__()
        self.choices = choices
        self.messages: list[list[dict[str, str]]] = []

    async def choose(self, _agent, _locale, messages, _actions):
        self.messages.append(messages)
        if not self.choices:
            raise AssertionError("Unexpected model choice")
        return self.choices.pop(0)


class FakeRuleClient:
    """Return the reviewed package's required facts as an MCP observation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, name: str, arguments: dict[str, object]):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            is_error=False,
            structured_content={"result": list(
                PACKAGES[str(arguments["scheme_id"])].required_facts
            )},
        )


def _plan_choices(order: list[str] | None = None) -> list[ModelDecision]:
    return [
        ModelDecision(
            action="propose_plan",
            arguments={
                "step_ids": order or ["intake", "eligibility"],
            },
        ),
        ModelDecision(
            action="finish_plan",
            arguments={"confirm": "use_validated_plan"},
        ),
    ]


def test_openrouter_chat_model_sends_one_strict_tool_choice_without_network(
    fake_openrouter,
):
    """The real ChatOpenAI agent path, answered by an in-process fake OpenRouter."""

    from src.llm_client import openrouter_chat_model

    fake_openrouter.answer(
        tool_call=("propose_plan", '{"step_ids":["intake","eligibility"]}')
    )
    model = openrouter_chat_model("synthetic-test-key", "fake-phase2-model")

    @tool(args_schema=PlanProposalArguments)
    async def propose_plan(step_ids: list[str]) -> str:
        """Propose the validated plan."""
        return observation(PlanProposalObservation(accepted=True, step_ids=step_ids))

    run = asyncio.run(run_agent(model, "supervisor", "en", {}, [propose_plan], max_steps=1))

    assert run.trace[0]["action"] == "propose_plan"
    assert run.budget["model_calls"] == 1 and run.budget["tool_calls"] == 1
    request = fake_openrouter.requests[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer synthetic-test-key"
    payload = fake_openrouter.sent_json()
    assert payload["model"] == "fake-phase2-model"
    assert payload["tool_choice"] == "required"
    assert payload["parallel_tool_calls"] is False
    assert payload["tools"][0]["function"]["name"] == "propose_plan"
    assert payload["tools"][0]["function"]["strict"] is True
    assert len(fake_openrouter.requests) == 1   # max_retries=0: no hidden retries



def test_supervisor_uses_observation_to_choose_next_action():
    """The next proposal depends on the code-validated plan observation."""

    class ObservationDrivenProvider(FakeChatModel):
        model_name: str = "fake-observation-model"

        def __init__(self):
            super().__init__()
            self.observed_validation = False

        async def choose(self, _agent, _locale, messages, _actions):
            if len(messages) == 1:
                return ModelDecision(
                    action="propose_plan",
                    arguments={"step_ids": ["intake", "eligibility"]},
                )
            observation_message = json.loads(messages[-1]["content"])
            self.observed_validation = (
                observation_message["observation"]["accepted"] is True
            )
            return ModelDecision(
                action=(
                    "finish_plan"
                    if self.observed_validation else "propose_plan"
                ),
                arguments=(
                    {"confirm": "use_validated_plan"}
                    if self.observed_validation
                    else {"step_ids": ["intake", "eligibility"]}
                ),
            )

    provider = ObservationDrivenProvider()
    initial_plan = build_initial_plan("interview", "IGNWPS-MH")

    plan, _budget, trace, status = asyncio.run(propose_supervisor_plan(
        provider,
        initial_plan,
        "en",
        None,
    ))

    assert status == "model_validated"
    assert provider.observed_validation
    assert [step.step_id for step in plan.steps] == ["intake", "eligibility"]
    assert [event["status"] for event in trace] == ["observed", "completed"]


def test_intake_selects_each_action_from_the_prior_observation():
    class ObservationDrivenProvider(FakeChatModel):
        model_name: str = "fake-intake-observation-model"

        def __init__(self):
            super().__init__()
            self.choices = []

        async def choose(self, agent, _locale, messages, _actions):
            observation = (
                json.loads(messages[-1]["content"]).get("observation")
                if len(messages) > 1
                else None
            )
            if agent == "supervisor":
                if observation is None:
                    action = ModelDecision(
                        action="propose_plan",
                        arguments={
                            "step_ids": ["intake", "eligibility"],
                        },
                    )
                else:
                    assert observation["accepted"] is True
                    action = ModelDecision(
                        action="finish_plan",
                        arguments={"confirm": "use_validated_plan"},
                    )
            elif observation is None:
                action = ModelDecision(
                    action="read_required_facts",
                    arguments={"scheme_id": "IGNWPS-MH"},
                )
            elif "required_facts" in observation:
                assert "is_widow" in observation["required_facts"]
                action = ModelDecision(
                    action="propose_profile_facts",
                    arguments={
                        "facts": [{"fact_name": "is_widow", "value": True}],
                    },
                )
            else:
                assert observation["accepted"][0]["fact_name"] == "is_widow"
                action = ModelDecision(
                    action="finish_intake",
                    arguments={"confirm": "return_to_supervisor"},
                )
            self.choices.append(action.action)
            return action

    client = FakeRuleClient()
    provider = ObservationDrivenProvider()
    graph = _interview_graph(client, provider)
    journey = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            profile_description="Synthetic widow household.",
        ),
    ))

    assert journey.status == "awaiting_answer"
    assert journey.pending_fact == "is_widow"
    assert journey.question is not None
    assert provider.choices == [
        "propose_plan",
        "finish_plan",
        "read_required_facts",
        "propose_profile_facts",
        "finish_intake",
    ]
    assert [
        event.action for event in journey.agent_trace
    ] == provider.choices


def _interview_graph(
    client,
    provider,
    checkpointer=None,
    answer_interpreter=None,
):
    async def search_tool(_client, _query):
        return []

    async def fake_eligibility(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])

    return build_journey_graph(
        client,
        PACKAGES,
        search_tool=search_tool,
        eligibility_tool=fake_eligibility,
        model_provider=provider,
        answer_interpreter=answer_interpreter or interpret_free_text_answer,
        checkpointer=checkpointer or MemorySaver(),
        today=lambda: date(2026, 11, 4),
    )


def test_react_intake_observes_allowed_tool_then_confirms_each_fact(caplog):
    client = FakeRuleClient()
    provider = ScriptedProvider([
        *_plan_choices(),
        ModelDecision(
            action="read_required_facts",
            arguments={"scheme_id": "IGNWPS-MH"},
        ),
        ModelDecision(
            action="propose_profile_facts",
            arguments={
                "facts": [
                    {"fact_name": "is_widow", "value": True},
                    {"fact_name": "bpl_card_shown", "value": True},
                    {"fact_name": "date_of_birth", "value": "1984-05-01"},
                ]
            },
        ),
        ModelDecision(
            action="finish_intake",
            arguments={"confirm": "return_to_supervisor"},
        ),
    ])
    graph = _interview_graph(client, provider)

    async def scenario():
        journey = await run_journey(
            graph,
            JourneyRequest(
                action="interview",
                scheme_id="IGNWPS-MH",
                profile_description=(
                    "Synthetic household facts; contact test@synthetic.invalid, "
                    "ID 0000 0000 0000."
                ),
            ),
        )
        assert journey.status == "awaiting_answer"
        assert journey.pending_fact == "is_widow"
        assert journey.known_fact_names == ["application_date"]
        assert "Are you a widow?" in journey.question
        assert journey.react_status == "model_assisted"
        assert journey.agent_budget["model_calls"] == 5
        assert journey.agent_budget["tool_calls"] == 5
        assert [event.action for event in journey.agent_trace] == [
            "propose_plan",
            "finish_plan",
            "read_required_facts",
            "propose_profile_facts",
            "finish_intake",
        ]
        assert len(client.calls) == 1
        assert "observation" in provider.messages[3][-1]["content"]
        assert "[REDACTED_EMAIL]" in provider.messages[2][0]["content"]
        assert "[REDACTED_AADHAAR]" in provider.messages[2][0]["content"]
        trace_text = json.dumps([
            event.model_dump(mode="json") for event in journey.agent_trace
        ])
        assert "test@synthetic.invalid" not in trace_text
        assert "0000 0000 0000" not in trace_text
        assert all(
            "test@synthetic.invalid" not in record.getMessage()
            and "0000 0000 0000" not in record.getMessage()
            for record in caplog.records
        )

        journey = await resume_journey(graph, journey.conversation_id, "yes")
        assert journey.pending_fact == "bpl_card_shown"
        assert journey.known_fact_names == ["application_date", "is_widow"]

        journey = await resume_journey(graph, journey.conversation_id, "no")
        assert journey.pending_fact == "date_of_birth"
        assert "I understood your answer as" in journey.question
        assert journey.known_fact_names == ["application_date", "is_widow"]

        journey = await resume_journey(graph, journey.conversation_id, "yes")
        assert journey.pending_fact == "bpl_card_shown"
        assert journey.question == (
            "Can you show a government BPL (Below Poverty Line) card?"
        )

        journey = await resume_journey(graph, journey.conversation_id, "yes")
        expected = evaluate_mock_eligibility(
            household_profile(
                date_of_birth=date(1984, 5, 1),
                application_date=date(2026, 11, 4),
                is_widow=True,
                bpl_card_shown=True,
            ),
            PACKAGES["IGNWPS-MH"],
        )
        assert journey.eligibility_result is not None
        assert journey.eligibility_result.result == expected.result
        assert (
            journey.eligibility_result.deciding_rule_ids
            == expected.deciding_rule_ids
        )

    asyncio.run(scenario())


def test_malformed_fact_proposal_is_not_confirmed_or_saved():
    provider = ScriptedProvider([
        *_plan_choices(),
        ModelDecision(
            action="read_required_facts",
            arguments={"scheme_id": "IGNWPS-MH"},
        ),
        # The malformed proposal is refused and the model may try again within
        # its 3-step limit; here it repeats the same mistake.
        *[ModelDecision(
            action="propose_profile_facts",
            arguments={
                "facts": [{"fact_name": "is_widow", "value": ["yes"]}],
            },
        )] * 2,
    ])
    client = FakeRuleClient()
    graph = _interview_graph(client, provider)

    result = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            profile_description="A synthetic household description.",
        ),
    ))

    assert result.status == "awaiting_answer"
    assert result.pending_fact == "is_widow"
    assert result.question == "Are you a widow?"
    assert result.known_fact_names == ["application_date"]
    assert any(event.status == "invalid_arguments" for event in result.agent_trace)


def test_model_failures_fall_back_to_the_fixed_question_flow():
    class UnavailableProvider(FakeChatModel):
        model_name: str = "fake-unavailable-model"

        async def choose(self, _agent, _locale, _messages, _actions):
            raise AgentModelError("Synthetic provider failure.")

    graph = _interview_graph(FakeRuleClient(), UnavailableProvider())

    journey = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            profile_description="A synthetic household description.",
        ),
    ))

    assert journey.status == "awaiting_answer"
    assert journey.question == "Are you a widow?"
    assert journey.react_status == "deterministic_fallback"
    assert [event.status for event in journey.agent_trace] == [
        "model_unavailable",
        "model_unavailable",
    ]


def test_unconfigured_model_uses_c0_without_false_failure_caption():
    graph = _interview_graph(FakeRuleClient(), None)

    journey = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            profile_description="A synthetic household description.",
        ),
    ))

    assert journey.status == "awaiting_answer"
    assert journey.react_status == "deterministic"
    assert journey.agent_budget["model_calls"] == 0
    assert journey.agent_trace == []


def test_search_query_rewrite_uses_the_durable_model_budget():
    rewritten_queries = []

    async def rewrite(query):
        rewritten_queries.append(query)
        return "widow pension"

    async def search(_client, query):
        assert query == "widow pension"
        return []

    graph = build_journey_graph(
        None,
        PACKAGES,
        query_rewriter=rewrite,
        search_tool=search,
        model_provider=None,
        checkpointer=MemorySaver(),
    )
    journey = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="search",
            query="Need support for test@example.invalid",
        ),
    ))

    assert rewritten_queries == ["Need support for [REDACTED_EMAIL]"]
    assert journey.agent_budget["model_calls"] == 1
    assert journey.agent_budget["agent_steps"] == 1
    assert journey.agent_trace[0].action == "rewrite_scheme_query"
    assert journey.agent_trace[0].status == "completed"
    trace_text = json.dumps([
        event.model_dump(mode="json") for event in journey.agent_trace
    ])
    assert "test@example.invalid" not in trace_text


def test_query_rewriter_timeout_falls_back_with_counted_trace(
    monkeypatch, fake_openrouter,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    fake_openrouter.reply = httpx.ReadTimeout("Synthetic timeout.")

    async def search(_client, query):
        assert query == "widow pension"
        return []

    provider = ScriptedProvider(_plan_choices(["intake", "search"]))
    graph = build_journey_graph(
        None,
        PACKAGES,
        search_tool=search,
        model_provider=provider,
        checkpointer=MemorySaver(),
    )
    journey = asyncio.run(run_journey(
        graph,
        JourneyRequest(action="search", query="widow pension"),
    ))

    assert journey.status == "search_results"
    assert journey.react_status == "deterministic_fallback"
    assert journey.agent_budget["model_calls"] == 3
    assert any(
        event.action == "rewrite_scheme_query"
        and event.status == "model_unavailable"
        for event in journey.agent_trace
    )


def test_legacy_chat_call_is_rejected_before_provider_at_budget_limit():
    calls = []

    async def callback():
        calls.append(True)
        return "unexpected"

    result, budget, trace, status = asyncio.run(run_accounted_model_call(
        agent="intake",
        action="interpret_free_text_answer",
        model="fake-budget-model",
        input_text="synthetic reply",
        budget={
            "model_calls": MAX_CONVERSATION_MODEL_CALLS,
            "agent_steps": MAX_CONVERSATION_AGENT_STEPS,
        },
        callback=callback,
        failure_type=AgentModelError,
    ))

    assert result is None
    assert status == "budget_exhausted"
    assert budget["model_calls"] == MAX_CONVERSATION_MODEL_CALLS
    assert trace[0]["status"] == "budget_exhausted"
    assert calls == []


def test_person_can_reject_initial_profile_proposal_without_mutation():
    provider = ScriptedProvider([
        *_plan_choices(),
        ModelDecision(
            action="read_required_facts",
            arguments={"scheme_id": "IGNWPS-MH"},
        ),
        ModelDecision(
            action="propose_profile_facts",
            arguments={"facts": [{"fact_name": "is_widow", "value": True}]},
        ),
        ModelDecision(
            action="finish_intake",
            arguments={"confirm": "return_to_supervisor"},
        ),
    ])
    graph = _interview_graph(FakeRuleClient(), provider)

    async def scenario():
        journey = await run_journey(
            graph,
            JourneyRequest(
                action="interview",
                scheme_id="IGNWPS-MH",
                profile_description="A synthetic household description.",
            ),
        )
        assert journey.pending_fact == "is_widow"
        checkpoint = await graph.aget_state(
            {"configurable": {"thread_id": str(journey.conversation_id)}}
        )
        assert checkpoint.values["pending_confirmation"] is True

        rejected = await resume_journey(
            graph, journey.conversation_id, "no"
        )
        assert rejected.pending_fact == "is_widow"
        assert rejected.known_fact_names == ["application_date"]
        checkpoint = await graph.aget_state(
            {"configurable": {"thread_id": str(journey.conversation_id)}}
        )
        assert checkpoint.values["pending_confirmation"] is False

    asyncio.run(scenario())


def test_initial_profile_proposal_cannot_replace_a_confirmed_fact():
    provider = ScriptedProvider([
        *_plan_choices(),
        ModelDecision(
            action="read_required_facts",
            arguments={"scheme_id": "IGNWPS-MH"},
        ),
        ModelDecision(
            action="propose_profile_facts",
            arguments={
                "facts": [
                    {"fact_name": "is_widow", "value": True},
                    {"fact_name": "bpl_card_shown", "value": True},
                ]
            },
        ),
        ModelDecision(
            action="finish_intake",
            arguments={"confirm": "return_to_supervisor"},
        ),
    ])
    graph = _interview_graph(FakeRuleClient(), provider)

    async def scenario():
        journey = await run_journey(
            graph,
            JourneyRequest(
                action="interview",
                scheme_id="IGNWPS-MH",
                profile={
                    "application_date": "2026-11-04",
                    "is_widow": False,
                },
                profile_description="A synthetic household description.",
            ),
        )
        assert journey.pending_fact == "bpl_card_shown"
        assert "is_widow" in journey.known_fact_names
        checkpoint = await graph.aget_state(
            {"configurable": {"thread_id": str(journey.conversation_id)}}
        )
        assert checkpoint.values["pending_confirmation"] is True

        accepted = await resume_journey(
            graph, journey.conversation_id, "yes"
        )
        checkpoint = await graph.aget_state(
            {"configurable": {"thread_id": str(journey.conversation_id)}}
        )
        assert checkpoint.values["typed_facts"]["facts"]["is_widow"]["value"] is False
        assert "bpl_card_shown" in accepted.known_fact_names

    asyncio.run(scenario())


def test_supervisor_rejects_dependency_violation_and_keeps_c0_plan():
    provider = ScriptedProvider([
        *_plan_choices(["eligibility", "intake"]),
        ModelDecision(
            action="read_required_facts",
            arguments={"scheme_id": "IGNWPS-MH"},
        ),
    ])
    client = FakeRuleClient()
    graph = _interview_graph(client, provider)

    result = asyncio.run(run_journey(
        graph,
        JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            profile={
                "date_of_birth": "1984-05-01",
                "is_widow": True,
                "bpl_card_shown": True,
            },
        ),
    ))

    assert result.status == "eligible"
    assert result.react_status == "deterministic_fallback"
    assert result.plan_detail is not None
    assert [step.step_id for step in result.plan_detail.steps] == [
        "intake",
        "eligibility",
    ]
    assert any(event.status == "action_rejected" for event in result.agent_trace)
    assert not client.calls


def test_agent_action_schema_denial_and_budget_stop_before_executor():
    class Args(AgentSchema):
        value: str = Field(min_length=1)

    class Output(AgentSchema):
        called: bool

    calls: list[str] = []

    @tool(args_schema=Args)
    async def propose_plan(value: str) -> str:
        """An allowed test action."""
        calls.append("executed")
        return observation(Output(called=True))

    provider = ScriptedProvider([
        ModelDecision(action="propose_plan", arguments={"value": ""}),
        ModelDecision(action="erase_household", arguments={}),
    ])

    def run(model, budget=None):
        return run_agent(model, "supervisor", "en", {}, [propose_plan], budget, max_steps=1)

    # A bad choice is answered with an error and the model may try again
    # within its step limit (LangChain behaviour). max_steps=1 gives it no
    # second try, so each run records the refusal and then stops.
    async def scenario():
        invalid = await run(provider)
        assert [event["status"] for event in invalid.trace] == [
            "invalid_arguments", "step_limit",
        ]
        assert invalid.status == "step_limit"
        assert not calls

        # A tool this agent was not given is denied: the tool list is the allow-list.
        denied = await run(provider)
        assert [event["status"] for event in denied.trace] == ["denied", "step_limit"]
        assert denied.status == "step_limit"
        assert not calls

        step_limited = await run(ScriptedProvider([
            ModelDecision(action="propose_plan", arguments={"value": "safe"}),
        ]))
        assert step_limited.status == "step_limit"
        assert step_limited.trace[-1]["status"] == "step_limit"
        assert calls == ["executed"]
        calls.clear()

        exhausted = await run(provider, {"model_calls": 8, "agent_steps": 8})
        assert exhausted.status == "budget_exhausted"
        assert len(provider.messages) == 2
        assert not calls

        tool_exhausted = await run(
            ScriptedProvider([ModelDecision(action="propose_plan", arguments={"value": "safe"})]),
            {"tool_calls": MAX_CONVERSATION_TOOL_CALLS},
        )
        assert tool_exhausted.status == "budget_exhausted"
        assert not calls

    asyncio.run(scenario())


def test_same_id_restart_preserves_model_budget():
    provider = ScriptedProvider(_plan_choices() * 2)
    conversation_id = uuid4()
    database = Path.cwd() / f".phase2-restart-{uuid4().hex}.sqlite3"
    request = JourneyRequest(
        action="interview",
        conversation_id=conversation_id,
        scheme_id="IGNWPS-MH",
        profile={
            "date_of_birth": "1984-05-01",
            "is_widow": True,
            "bpl_card_shown": True,
        },
    )

    async def scenario():
        connection = await aiosqlite.connect(str(database))
        try:
            saver = AsyncSqliteSaver(connection)
            await saver.setup()
            graph = _interview_graph(None, provider, saver)
            first = await run_journey(graph, request)
            assert first.agent_budget["model_calls"] == 2
        finally:
            await connection.close()

        # A fresh graph and SQLite connection model an API restart.
        restarted_connection = await aiosqlite.connect(str(database))
        try:
            restarted_saver = AsyncSqliteSaver(restarted_connection)
            restarted_graph = _interview_graph(
                None, provider, restarted_saver
            )
            second = await run_journey(restarted_graph, request)
            assert second.agent_budget["model_calls"] == 4
            assert len(provider.messages) == 4
        finally:
            await restarted_connection.close()

    try:
        asyncio.run(scenario())
    finally:
        if database.exists():
            database.unlink()


def test_model_budget_survives_correction_and_same_id_process_restart():
    interpreted_facts = []
    interpreted_replies = []

    async def interpret_answer(fact, _question, reply):
        interpreted_facts.append(fact)
        interpreted_replies.append(reply)
        return AnswerInterpretation(
            kind="value",
            value=True,
            confidence=0.99,
        )

    candidate_ids = ["IGNWPS-MH", "PM-KISAN-IN"]
    plan_choices = _plan_choices([
        "intake",
        "eligibility:IGNWPS-MH",
        "eligibility:PM-KISAN-IN",
    ])
    provider = ScriptedProvider(plan_choices * 3)
    conversation_id = uuid4()
    database = Path.cwd() / f".phase2-correction-{uuid4().hex}.sqlite3"
    request = JourneyRequest(
        action="interview",
        conversation_id=conversation_id,
        candidate_scheme_ids=candidate_ids,
        profile={
            "date_of_birth": "1984-05-01",
            "application_date": "2026-11-04",
            "bpl_card_shown": True,
            "landholding_family_in_state_records": True,
            "institutional_landholder": False,
            "listed_public_office_member": False,
            "excluded_government_employee_member": False,
            "pension_at_least_10000_excluding_stated_grades": False,
            "income_tax_paid_last_assessment_year": False,
            "registered_practicing_professional_member": False,
            "nri_new_beneficiary": False,
        },
    )

    async def scenario():
        connection = await aiosqlite.connect(str(database))
        try:
            saver = AsyncSqliteSaver(connection)
            await saver.setup()
            graph = _interview_graph(
                None, provider, saver, interpret_answer
            )
            first = await run_journey(graph, request)
            assert first.agent_budget["model_calls"] == 2
            assert first.pending_fact == "is_widow"

            interpreted = await resume_journey(
                graph, conversation_id,
                "My husband passed away. 9876543210",
            )
            assert interpreted.agent_budget["model_calls"] == 3
            assert interpreted.pending_fact == "is_widow"
            assert "I understood your answer as" in interpreted.question
            assert interpreted.agent_trace[-1].action == (
                "interpret_free_text_answer"
            )
            assert interpreted_replies == [
                "My husband passed away. [REDACTED_PHONE]"
            ]
            assert "9876543210" not in json.dumps([
                event.model_dump(mode="json")
                for event in interpreted.agent_trace
            ])
            completed = await resume_journey(
                graph, conversation_id, "yes"
            )
            assert completed.agent_budget["model_calls"] == 3

            corrected = await correct_journey_answer(
                graph,
                conversation_id,
                JourneyCorrection(fact_name="is_widow", answer="no"),
            )
            assert corrected.agent_budget["model_calls"] == 5
        finally:
            await connection.close()

        restarted_connection = await aiosqlite.connect(str(database))
        try:
            restarted_saver = AsyncSqliteSaver(restarted_connection)
            restarted_graph = _interview_graph(
                None, provider, restarted_saver, interpret_answer
            )
            restarted = await run_journey(restarted_graph, request)
            assert restarted.agent_budget["model_calls"] == 7
            assert len(provider.messages) == 6
            assert interpreted_facts == ["is_widow"]
        finally:
            await restarted_connection.close()

    try:
        asyncio.run(scenario())
    finally:
        if database.exists():
            database.unlink()


def test_fact_interpretation_attempt_survives_correction_and_same_id_restart():
    attempts: list[str] = []

    async def interpreter(fact, _question, _reply):
        attempts.append(fact)
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    async def eligibility(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])

    database = Path.cwd() / f".phase2-attempts-{uuid4().hex}.sqlite3"
    conversation_id = uuid4()
    request = JourneyRequest(
        action="interview",
        conversation_id=conversation_id,
        candidate_scheme_ids=["IGNWPS-MH", "PM-KISAN-IN"],
    )

    async def scenario():
        connection = await aiosqlite.connect(str(database))
        try:
            saver = AsyncSqliteSaver(connection)
            await saver.setup()
            graph = build_journey_graph(
                None,
                PACKAGES,
                eligibility_tool=eligibility,
                answer_interpreter=interpreter,
                checkpointer=saver,
                today=lambda: date(2026, 11, 4),
            )
            journey = await run_journey(graph, request)
            assert journey.pending_fact == "is_widow"
            journey = await resume_journey(graph, conversation_id, "maybe")
            assert attempts == ["is_widow"]
            journey = await resume_journey(graph, conversation_id, "yes")
            assert journey.pending_fact == "date_of_birth"
            await resume_journey(graph, conversation_id, "1986-01-01")

            corrected = await correct_journey_answer(
                graph,
                conversation_id,
                JourneyCorrection(
                    fact_name="date_of_birth",
                    answer="1985-01-01",
                ),
            )
            assert corrected.agent_budget["model_calls"] == 1
            checkpoint = await graph.aget_state(
                {"configurable": {"thread_id": str(conversation_id)}}
            )
            assert "is_widow" in checkpoint.values["llm_attempted_facts"]
        finally:
            await connection.close()

        restarted_connection = await aiosqlite.connect(str(database))
        restarted_saver = AsyncSqliteSaver(restarted_connection)
        restarted_graph = build_journey_graph(
            None,
            PACKAGES,
            eligibility_tool=eligibility,
            answer_interpreter=interpreter,
            checkpointer=restarted_saver,
            today=lambda: date(2026, 11, 4),
        )
        try:
            journey = await run_journey(restarted_graph, request)
            assert journey.pending_fact == "bpl_card_shown"
            restored = await restarted_graph.aget_state(
                {"configurable": {"thread_id": str(conversation_id)}}
            )
            assert "is_widow" in restored.values["llm_attempted_facts"]
            assert attempts == ["is_widow"]
        finally:
            await restarted_connection.close()

    try:
        asyncio.run(scenario())
    finally:
        if database.exists():
            database.unlink()


def test_csc_interview_requires_citizen_presence_and_has_localized_contract():
    try:
        JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            mode="csc",
        )
    except ValueError as error:
        assert "citizen to be present" in str(error)
    else:
        raise AssertionError("CSC intake accepted without citizen presence")

    accepted = JourneyRequest(
        action="interview",
        scheme_id="IGNWPS-MH",
        locale="mr",
        mode="csc",
        citizen_present=True,
    )
    assert accepted.locale == "mr"


def test_initial_plan_goals_and_questions_are_localized():
    plan = build_initial_plan("interview", "IGNWPS-MH", locale="hi")

    assert plan.steps[0].goal == "आपके परिवार की जानकारी समझें"
    assert plan.steps[1].goal == "IGNWPS-MH के नियम जाँचें"


def test_intake_reads_required_facts_from_the_real_rule_engine_server():
    """Contract test: the real MCP server wraps a list as {"result": [...]}."""

    from mcp import Client

    from src.mcp_servers.rule_engine_server import mcp as rule_engine_server
    from src.workflow.intake_agent import propose_initial_registered_facts

    package = PACKAGES["IGNWPS-MH"]
    provider = ScriptedProvider([
        ModelDecision(action="read_required_facts", arguments={"scheme_id": "IGNWPS-MH"}),
        ModelDecision(action="finish_intake", arguments={"confirm": "return_to_supervisor"}),
    ])

    async def scenario():
        async with Client(rule_engine_server) as client:
            return await propose_initial_registered_facts(
                provider, client, "intake", "IGNWPS-MH", "I am a widow.",
                household_profile(), _REGISTRY, package.required_facts, "en", None,
            )

    _proposals, _budget, trace, status = asyncio.run(scenario())
    assert [event["status"] for event in trace][:1] == ["observed"], trace
    assert status == "model_assisted"
