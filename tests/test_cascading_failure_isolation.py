"""ASI08 (cascading failure) live verification.

docs/THREAT_MODEL.md says each specialist "re-derives its own facts from
the rule engine rather than trusting a peer's claim, by design -- not yet
stress-tested with a deliberately wrong upstream result". These tests
inject exactly that: a wrong upstream result at each real hand-off point,
then prove the downstream step does not act on it.

Hand-offs covered:

1. Eligibility model -> verdict. A model that tries to hand off "eligible"
   after the rule engine said no is refused by the handoff schema and the
   run fails closed (no verdict); the one handoff it can make carries the
   rule engine's own result. A rule-tool result for a different scheme is
   discarded rather than treated as a verdict.
2. Intake -> eligibility. A wrong fact read out of the free-text
   description by the quarantined reader (and passed on by the intake
   agent) is never evaluated until the citizen confirms it; a citizen
   "no" overrides the proposal.
3. Eligibility -> application (poisoned verdict). A checkpoint that says
   "eligible" for a profile the rules reject: the application specialist
   re-runs the rule engine itself and writes nothing to the portal.
4. Draft -> submit (profile changed underneath). A draft built and
   approved from one profile cannot be submitted once the saved profile
   differs, even if the new profile is still eligible: the submit path
   re-checks documents against the current profile and the portal marks
   the draft stale.
5. Rule engine -> submit (rules changed underneath). An approval given
   under one rule package is dead once the rules change; the portal's
   ``bind_rules`` dependency revokes it.

All offline: real rule engine, real document checker and real SQLite
mock portal, fake chat models, no MCP subprocess, no paid calls.
"""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from fake_chat_model import FakeChatModel, ModelDecision
from src.api.eligibility import evaluate_mock_eligibility
from src.mcp_servers.tools import applications, documents
from src.rules.data_provider import RulePackageProvider
from src.rules.models import HouseholdProfile
from src.workflow.eligibility_agent import run_eligibility_specialist
from src.workflow.errors import MCPToolError
from src.workflow.journey import (
    ApplicationTaskError,
    JourneyRequest,
    build_journey_graph,
    resume_journey,
    run_application_task,
    run_journey,
)

PACKAGES = RulePackageProvider().packages
SCHEME = "IGNWPS-MH"
ELIGIBLE_PROFILE = {
    "date_of_birth": "1986-01-01",
    "application_date": "2026-01-01",
    "is_widow": True,
    "bpl_card_shown": True,
}
NOT_ELIGIBLE_PROFILE = {**ELIGIBLE_PROFILE, "is_widow": False}
DOCUMENT_REPORT = {
    "scheme_id": SCHEME,
    "documents": {
        "identity_proof": "available",
        "age_proof": "available",
        "widow_status_proof": "available",
        "bpl_proof": "available",
    },
}


@pytest.fixture
def portal(tmp_path, monkeypatch):
    """Real local document checker and SQLite mock portal, call-recorded."""

    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    calls: list[tuple[str, dict]] = []

    async def tool(_client, name, arguments):
        calls.append((name, dict(arguments)))
        try:
            if name == "check_documents":
                return documents.assess_document_metadata(arguments)
            assert name == "mock_portal"
            return applications._portal_action(arguments)
        except (ValueError, RuntimeError) as error:
            raise MCPToolError(str(error)) from error

    return tool, calls


def _graph(application_tool, checkpointer, packages=PACKAGES, rule_calls=None):
    async def eligibility(_client, scheme_id, profile):
        if rule_calls is not None:
            rule_calls.append((scheme_id, profile.model_dump(mode="json")))
        return evaluate_mock_eligibility(profile, packages[scheme_id])

    return build_journey_graph(
        None, packages, eligibility_tool=eligibility,
        application_tool=application_tool, checkpointer=checkpointer,
    )


def _drafts(journey_id) -> list[dict]:
    return applications._portal_action(
        {"action": "list_drafts", "journey_id": str(journey_id)}
    )["drafts"]


async def _evaluate(graph, journey_id, profile) -> str:
    response = await run_journey(graph, JourneyRequest(
        action="evaluate", conversation_id=journey_id,
        scheme_id=SCHEME, profile=profile,
    ))
    return response.status


async def _approved_draft(graph, journey_id) -> dict:
    draft = await run_application_task(graph, journey_id, "create_draft", DOCUMENT_REPORT)
    identity = {**DOCUMENT_REPORT, **{
        key: draft[key] for key in ("draft_id", "revision", "fingerprint")
    }}
    approved = await run_application_task(graph, journey_id, "approve", identity)
    assert approved["approved"] is True
    return identity


# 1. Eligibility model -> verdict ---------------------------------------------


class ScriptedEligibilityModel(FakeChatModel):
    """Plays back a fixed list of eligibility choices and records observations."""

    model_name: str = "offline-scripted-eligibility"

    def __init__(self, decisions):
        super().__init__()
        self.decisions = iter(decisions)
        self.seen: list[str] = []

    async def choose(self, _agent, _locale, messages, _actions):
        self.seen.append(messages[-1]["content"])
        return next(self.decisions)


def _not_eligible_rule_check(rule_calls):
    async def rule_check():
        rule_calls.append(True)
        return evaluate_mock_eligibility(
            HouseholdProfile(**NOT_ELIGIBLE_PROFILE), PACKAGES[SCHEME]
        )
    return rule_check


CHECK = ModelDecision(action="check_candidate", arguments={"scheme_id": SCHEME})


def test_model_claiming_eligible_cannot_override_the_rule_engine():
    """The model sees "not_eligible" and tries to hand off "eligible" anyway."""

    rule_calls: list[bool] = []
    model = ScriptedEligibilityModel([
        CHECK,
        # Smuggle a model-written verdict into the handoff (extra field).
        ModelDecision(action="handoff_verdict", arguments={
            "confirm": "return_observed_verdict", "result": "eligible"}),
        ModelDecision(action="handoff_verdict", arguments={
            "confirm": "return_observed_verdict", "result": "eligible"}),
    ])
    result, _, trace, mode = asyncio.run(run_eligibility_specialist(
        model, SCHEME, "en", {}, _not_eligible_rule_check(rule_calls),
    ))
    # The model really did observe the rule engine's "no"...
    assert '"result": "not_eligible"' in model.seen[1]
    # ...its "eligible" handoff was refused by the schema, and the run ended
    # with no verdict at all (fail closed -> a tool_error reply), never with
    # the model's claim.
    assert [event["status"] for event in trace][:2] == ["observed", "invalid_arguments"]
    assert result is None
    assert mode == "deterministic_fallback"
    assert rule_calls == [True]


def test_model_handoff_carries_only_the_observed_rule_engine_verdict():
    """The only handoff the model can make returns the engine's own result."""

    rule_calls: list[bool] = []
    model = ScriptedEligibilityModel([
        CHECK,
        ModelDecision(action="handoff_verdict", arguments={
            "confirm": "return_observed_verdict"}),
    ])
    result, _, _, mode = asyncio.run(run_eligibility_specialist(
        model, SCHEME, "en", {}, _not_eligible_rule_check(rule_calls),
    ))
    assert mode == "model_assisted"
    assert result is not None and result.result == "not_eligible"
    assert rule_calls == [True]


def test_rule_tool_verdict_for_a_different_scheme_is_discarded():
    """A mismatched upstream result (right shape, wrong scheme) is not a verdict."""

    async def wrong_scheme():
        # An "eligible" verdict, but for a different scheme than the task.
        return evaluate_mock_eligibility(
            HouseholdProfile(**ELIGIBLE_PROFILE), PACKAGES["PM-KISAN-IN"]
        ).model_copy(update={"result": "eligible"})

    result, *_ = asyncio.run(run_eligibility_specialist(
        None, SCHEME, "en", {}, wrong_scheme,
    ))
    assert result is None


# 2. Intake -> eligibility -----------------------------------------------------


def test_wrong_intake_proposal_is_not_evaluated_until_the_citizen_confirms():
    """The quarantined reader guesses is_widow=True; the citizen says no."""

    DESCRIPTION = "Synthetic household; the husband passed away."

    class GuessingIntake(FakeChatModel):
        model_name: str = "offline-guessing-intake"

        def __init__(self):
            super().__init__()
            self.reader_requests: list[dict] = []
            self.agent_checked = False
            self.decisions = iter([
                ModelDecision(action="propose_plan", arguments={
                    "step_ids": ["intake", f"eligibility:{SCHEME}"]}),
                ModelDecision(action="finish_plan", arguments={"confirm": "use_validated_plan"}),
                ModelDecision(action="read_required_facts", arguments={"scheme_id": SCHEME}),
                ModelDecision(action="propose_profile_facts", arguments={"facts": [
                    {"fact_name": "is_widow", "value": True}]}),
                ModelDecision(action="finish_intake", arguments={"confirm": "return_to_supervisor"}),
            ])

        async def read_description(self, request):
            # The quarantined description reader is where the wrong guess
            # originates: it "reads" is_widow=True into the free text.
            self.reader_requests.append(request)
            return json.dumps({"facts": [{"fact_name": "is_widow", "value": True}]})

        async def choose(self, agent, _locale, messages, _actions):
            if agent == "intake" and len(messages) == 1:
                # The tool-calling agent never sees the description itself,
                # only the reader's validated (and here wrong) guess.
                context = json.loads(messages[0]["content"])
                assert "profile_description" not in context
                assert DESCRIPTION not in messages[0]["content"]
                assert context["description_facts"] == [
                    {"fact_name": "is_widow", "value": True}]
                self.agent_checked = True
            return next(self.decisions)

    class Client:
        async def call_tool(self, name, arguments):
            assert name == "required_facts"
            return SimpleNamespace(is_error=False, structured_content={"result": list(
                PACKAGES[arguments["scheme_id"]].required_facts,
            )})

    rule_calls: list[tuple[str, dict]] = []

    async def eligibility(_client, scheme_id, profile):
        rule_calls.append((scheme_id, profile.model_dump(mode="json")))
        return evaluate_mock_eligibility(profile, PACKAGES[scheme_id])

    model = GuessingIntake()
    graph = build_journey_graph(
        Client(), PACKAGES, model_provider=model,
        eligibility_tool=eligibility, checkpointer=MemorySaver(),
    )

    async def scenario():
        profile = {k: v for k, v in ELIGIBLE_PROFILE.items() if k != "is_widow"}
        initial = await run_journey(graph, JourneyRequest(
            action="interview", candidate_scheme_ids=[SCHEME], profile=profile,
            profile_description=DESCRIPTION,
        ))
        # The reader really ran on the description and produced the guess...
        assert len(model.reader_requests) == 1
        assert model.agent_checked
        assert model.reader_requests[0]["description"] == DESCRIPTION
        # ...but the proposal becomes a question, not a fact the rule engine sees.
        assert initial.status == "awaiting_answer"
        assert initial.pending_fact == "is_widow"
        assert SCHEME not in initial.candidate_verdicts
        assert not any(p.get("is_widow") is True for _, p in rule_calls)

        # The citizen rejects the proposed value: it is dropped, not kept as
        # a fallback, and the question is asked directly instead.
        rejected = await resume_journey(graph, initial.conversation_id, "no")
        assert rejected.status == "awaiting_answer"
        assert rejected.pending_fact == "is_widow"
        assert SCHEME not in rejected.candidate_verdicts
        assert rule_calls == []

        answered = await resume_journey(graph, initial.conversation_id, "no")
        # The citizen's answer, not the intake guess, reached the rule engine.
        assert answered.candidate_verdicts[SCHEME].result == "not_eligible"
        assert rule_calls and all(p["is_widow"] is False for _, p in rule_calls)

    asyncio.run(scenario())


# 3. Eligibility -> application: poisoned verdict -----------------------------


def test_poisoned_eligible_verdict_is_rederived_before_any_portal_write(portal):
    """The checkpoint lies "eligible"; the application step asks the rules itself."""

    tool, calls = portal
    rule_calls: list[tuple[str, dict]] = []
    graph = _graph(tool, MemorySaver(), rule_calls=rule_calls)

    async def scenario():
        journey_id = uuid4()
        assert await _evaluate(graph, journey_id, NOT_ELIGIBLE_PROFILE) == "not_eligible"

        # Poison the upstream result every downstream step reads.
        config = {"configurable": {"thread_id": str(journey_id)}}
        await graph.aupdate_state(config, {"candidate_verdicts": {
            SCHEME: {"scheme_id": SCHEME, "result": "eligible",
                     "missing_fields": [], "deciding_rule_ids": []},
        }})
        rule_calls.clear()

        with pytest.raises(ApplicationTaskError, match="no longer eligible") as caught:
            await run_application_task(graph, journey_id, "create_draft", DOCUMENT_REPORT)
        assert caught.value.status_code == 409
        # The refusal came from a fresh rule-engine call on the saved profile...
        assert len(rule_calls) == 1 and rule_calls[0][1]["is_widow"] is False
        # Current behaviour worth knowing: the documents step gates only on
        # the saved verdict, so the poisoned claim *did* let it run a
        # read-only checklist check. It is the application step's own rule
        # re-check that stops the cascade before anything citizen-facing.
        assert "check_documents" in {name for name, _ in calls}
        # ...and nothing was written: no create_draft reached the portal.
        assert "create_draft" not in {
            arguments.get("action") for name, arguments in calls if name == "mock_portal"
        }
        assert _drafts(journey_id) == []

    asyncio.run(scenario())


# 4. Draft -> submit: profile changed underneath ------------------------------


def test_approved_draft_cannot_be_submitted_after_the_profile_changes(portal):
    """Still-eligible but different profile: the old draft is not trusted."""

    tool, _ = portal
    graph = _graph(tool, MemorySaver())

    async def scenario():
        journey_id = uuid4()
        assert await _evaluate(graph, journey_id, ELIGIBLE_PROFILE) == "eligible"
        identity = await _approved_draft(graph, journey_id)

        # Change the saved profile behind the draft's back (no correction
        # flow, so no portal reconciliation is triggered). It stays eligible.
        config = {"configurable": {"thread_id": str(journey_id)}}
        snapshot = await graph.aget_state(config)
        await graph.aupdate_state(config, {
            "profile": {**snapshot.values["profile"], "date_of_birth": "1980-06-15"},
        })

        # The submit path re-checks the documents against the *current*
        # profile first; the new date of birth changes the document report
        # fingerprint, so the portal marks the old draft stale.
        with pytest.raises(ApplicationTaskError, match="stale") as caught:
            await run_application_task(graph, journey_id, "submit", identity)
        assert caught.value.status_code == 409
        [draft] = _drafts(journey_id)
        assert draft["stale"] is True
        assert draft["approved"] is False
        assert not draft["receipt_id"]

    asyncio.run(scenario())


# 5. Rule engine -> submit: rules changed underneath --------------------------


def test_approval_under_old_rules_is_dead_once_the_rule_package_changes(portal):
    """bind_rules sees a new rule fingerprint and revokes the approval."""

    tool, _ = portal
    checkpointer = MemorySaver()
    graph = _graph(tool, checkpointer)

    async def scenario():
        journey_id = uuid4()
        assert await _evaluate(graph, journey_id, ELIGIBLE_PROFILE) == "eligible"
        identity = await _approved_draft(graph, journey_id)

        # Same conversation, same portal, but the rule package changed
        # upstream (e.g. a rules update shipped after the approval).
        changed = {
            **PACKAGES,
            SCHEME: PACKAGES[SCHEME].model_copy(update={"package_version": "99.0.0"}),
        }
        updated_graph = _graph(tool, checkpointer, packages=changed)

        with pytest.raises(ApplicationTaskError, match="stale") as caught:
            await run_application_task(updated_graph, journey_id, "submit", identity)
        assert caught.value.status_code == 409
        [draft] = _drafts(journey_id)
        assert draft["stale"] is True
        assert not draft["receipt_id"]
        assert draft["approved"] is False

    asyncio.run(scenario())
