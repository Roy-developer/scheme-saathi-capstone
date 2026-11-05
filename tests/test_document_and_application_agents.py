"""Verify bounded Phase 4 specialists and approval authorization offline."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import aiosqlite
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.api.eligibility import evaluate_mock_eligibility
from src.mcp_servers.tools import applications, documents
from src.rules.data_provider import RulePackageProvider
from src.workflow.agent_config import MAX_CONVERSATION_MODEL_CALLS
from src.workflow.agent_config import MAX_CONVERSATION_TOOL_CALLS
from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.agent_runtime import AgentModelError
from src.workflow.errors import MCPToolError
from src.workflow.conversation_budget import ConversationBudget
from src.workflow.journey import (
    ApplicationTaskError, JourneyRequest, build_journey_graph,
    resume_journey, run_application_task, run_journey,
)
from src.workflow.application_agent import (
    run_application_specialist,
)
from src.workflow.document_agent import (
    run_document_specialist,
)


class DocumentChoiceModel(FakeChatModel):
    """Choose a typed handoff only after seeing the deterministic report."""

    model_name: str = "offline-document-model"

    def __init__(self, outcome: str, expected_status: str) -> None:
        super().__init__()
        self.outcome = outcome
        self.expected_status = expected_status

    async def choose(self, agent, locale, messages, actions):
        assert agent == "documents" and locale == "mr"
        assert {action.name for action in actions} == {
            "inspect_document_metadata", "handoff_documents",
        }
        if len(messages) == 1:
            return ModelDecision(
                action="inspect_document_metadata",
                arguments={"scheme_id": "IGNWPS-MH"},
            )
        observation = messages[-1]["content"]
        assert f'"status": "{self.expected_status}"' in observation
        assert "Synthetic private name" not in observation
        return ModelDecision(
            action="handoff_documents",
            arguments={"outcome": self.outcome},
        )


@pytest.mark.parametrize(
    ("name", "document_name", "document_date", "expected_status", "codes"),
    [
        ("Synthetic Example", "Synthetic Example", "1986-01-01", "checklist_complete", []),
        ("Synthetic Example", "Different Synthetic", "1986-01-01", "mismatch", ["name_mismatch"]),
        ("Synthetic Example", "Synthetic Example", "1986-01-02", "mismatch", ["date_of_birth_mismatch"]),
        (None, "Synthetic Example", "1986-01-01", "unknown_items", []),
    ],
)
def test_document_checker_compares_synthetic_name_and_date_without_echoing_values(
    name, document_name, document_date, expected_status, codes
):
    result = documents.assess_document_metadata({
        "scheme_id": "IGNWPS-MH",
        "profile_name": name,
        "profile_date_of_birth": "1986-01-01",
        "documents": {
            "identity_proof": "available",
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        },
        "document_metadata": {
            "identity_proof": {
                "name": document_name,
                "date_of_birth": document_date,
            },
        },
    })

    assert result["status"] == expected_status
    assert [item["code"] for item in result["discrepancies"]] == codes
    assert "Synthetic Example" not in result["message"]
    assert result["demo_only"] is True
    assert "no files were uploaded" in result["message"].lower()


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("checklist_complete", "ready"),
        ("mismatch", "correction"),
        ("missing_items", "clarification"),
        ("unknown_items", "clarification"),
        ("requirements_unverified", "referral"),
    ],
)
def test_document_specialist_selects_allowed_handoff_from_observation(status, outcome):
    called = []

    async def inspect():
        called.append(True)
        return {
            "status": status,
            "discrepancies": (
                [{"code": "name_mismatch"}] if status == "mismatch" else []
            ),
        }

    result, budget, trace, mode = asyncio.run(run_document_specialist(
        DocumentChoiceModel(outcome, status),
        "IGNWPS-MH",
        "mr",
        {},
        inspect,
    ))

    assert result["status"] == status
    assert called == [True]
    assert budget["tool_calls"] == 2
    assert [item["status"] for item in trace] == ["observed", "completed"]
    assert mode == "model_assisted"


def test_document_specialist_rejects_mismatched_handoff_and_tool_error():
    class WrongHandoffModel(FakeChatModel):
        model_name: str = "offline-wrong-document-handoff"

        async def choose(self, _agent, _locale, messages, _actions):
            if len(messages) == 1:
                return ModelDecision(
                    action="inspect_document_metadata",
                    arguments={"scheme_id": "IGNWPS-MH"},
                )
            return ModelDecision(
                action="handoff_documents", arguments={"outcome": "ready"},
            )

    calls = []

    async def mismatch():
        calls.append(True)
        return {"status": "mismatch", "discrepancies": []}

    result, _, trace, mode = asyncio.run(run_document_specialist(
        WrongHandoffModel(), "IGNWPS-MH", "en", {}, mismatch,
    ))
    assert result is None and calls == [True]
    assert trace[-1]["status"] == "action_rejected"
    assert mode == "deterministic_fallback"

    async def unavailable():
        raise MCPToolError("Synthetic service failure")

    with pytest.raises(MCPToolError):
        asyncio.run(run_document_specialist(
            DocumentChoiceModel("ready", "checklist_complete"),
            "IGNWPS-MH", "mr", {}, unavailable,
        ))


@pytest.mark.parametrize(
    ("operation", "action", "status"),
    [
        ("create_draft", "prepare_draft", "draft_ready"),
        ("edit_draft", "edit_draft", "revision_saved"),
        ("submit", "submit_draft", "submitted"),
        ("get_status", "read_application_status", "status_read"),
    ],
)
def test_application_specialist_observes_safe_result_for_each_allowed_action(
    operation, action, status
):
    class ApplicationChoiceModel(FakeChatModel):
        model_name: str = "offline-application-model"

        async def choose(self, agent, locale, messages, actions):
            assert agent == "application" and locale == "hi"
            names = {item.name for item in actions}
            assert action in names
            assert "approve" not in names and "reject" not in names
            if len(messages) == 1:
                return ModelDecision(
                    action=action,
                    arguments={"operation": operation, "draft_id": "synthetic-draft"},
                )
            assert "Synthetic private name" not in messages[-1]["content"]
            return ModelDecision(
                action="handoff_application",
                arguments={"confirm": "return_observed_application_status"},
            )

    executed = []

    async def execute():
        executed.append(True)
        return {
            "revision": 2,
            "receipt_id": "synthetic-receipt" if operation == "submit" else None,
            "draft": {"applicant_reference": "Synthetic private name"},
        }

    result, budget, trace, mode = asyncio.run(run_application_specialist(
        ApplicationChoiceModel(),
        operation,
        "synthetic-draft",
        2,
        "hi",
        {},
        execute,
    ))
    assert result["revision"] == 2
    assert executed == [True]
    assert budget["tool_calls"] == 2
    assert [item["status"] for item in trace] == ["observed", "completed"]
    assert mode == "model_assisted"


def test_application_specialist_denies_spoofed_approval_and_never_reports_tool_failure_as_success():
    class SpoofingModel(FakeChatModel):
        model_name: str = "offline-spoof"

        async def choose(self, *_args):
            return ModelDecision(action="approve", arguments={})

    async def forbidden():
        pytest.fail("A model-selected approval must not reach a portal action.")

    result, _, trace, mode = asyncio.run(run_application_specialist(
        SpoofingModel(), "submit", "synthetic-draft", 1, "en", {}, forbidden,
    ))
    # Every approval attempt is refused (the model may retry within its step
    # limit) and the portal action never runs.
    assert result is None
    assert "denied" in {event["status"] for event in trace}
    assert mode == "deterministic_fallback"

    class SubmitModel(FakeChatModel):
        model_name: str = "offline-submit-failure"

        async def choose(self, _agent, _locale, messages, _actions):
            if len(messages) == 1:
                return ModelDecision(
                    action="submit_draft",
                    arguments={"operation": "submit", "draft_id": "synthetic-draft"},
                )
            return ModelDecision(
                action="handoff_application",
                arguments={"confirm": "return_observed_application_status"},
            )

    async def unavailable():
        raise MCPToolError("Synthetic portal failure")

    with pytest.raises(MCPToolError):
        asyncio.run(run_application_specialist(
            SubmitModel(), "submit", "synthetic-draft", 1, "en", {}, unavailable,
        ))


@pytest.mark.parametrize(
    ("operation", "action", "result"),
    [
        ("create_draft", "prepare_draft", {
            "draft_id": "synthetic-draft", "revision": 1,
            "fingerprint": "a" * 64, "approved": False,
        }),
        ("submit", "submit_draft", {
            "draft_id": "synthetic-draft", "revision": 1,
            "receipt_id": "synthetic-receipt",
        }),
    ],
)
def test_application_specialist_preserves_committed_write_if_handoff_fails(
    operation, action, result,
):
    class HandoffFailureModel(FakeChatModel):
        model_name: str = "offline-handoff-failure"

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def choose(self, *_args):
            self.calls += 1
            if self.calls == 1:
                return ModelDecision(
                    action=action,
                    arguments={"operation": operation, "draft_id": (
                        None if operation == "create_draft" else "synthetic-draft"
                    )},
                )
            raise AgentModelError("Synthetic handoff model failure")

    calls = []

    async def create_once():
        calls.append(True)
        return result

    record, _, trace, mode = asyncio.run(run_application_specialist(
        HandoffFailureModel(), operation,
        None if operation == "create_draft" else "synthetic-draft",
        None if operation == "create_draft" else 1,
        "en", {}, create_once,
    ))
    assert record is not None
    assert record["draft_id"] == "synthetic-draft"
    assert record == result
    assert record.get("receipt_id") == result.get("receipt_id")
    assert calls == [True]
    assert trace[-1]["status"] == "model_unavailable"
    assert mode == "action_completed_handoff_incomplete"


@pytest.fixture
def phase4_portal_database(monkeypatch):
    """Use a unique project-local database, leaving runtime and crash data alone."""

    path = Path.cwd() / f".pytest-phase4-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(path))
    yield path
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _approved_draft() -> tuple[dict[str, object], dict[str, object]]:
    created = applications._portal_action({
        "action": "create_draft",
        "journey_id": "phase4-synthetic",
        "scheme_id": "IGNWPS-MH",
        "profile": {
            "date_of_birth": "1986-01-01",
            "is_widow": True,
        },
        "documents": {
            "identity_proof": "available",
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        },
    })
    identity = {
        "journey_id": "phase4-synthetic",
        "draft_id": created["draft_id"],
        "revision": created["revision"],
        "fingerprint": created["fingerprint"],
    }
    return identity, applications._portal_action({"action": "approve", **identity})


@pytest.mark.parametrize("tamper", ["expired", "future", "malformed"])
def test_expired_or_malformed_approval_fails_closed(phase4_portal_database, tamper):
    identity, approved = _approved_draft()
    issued = datetime.now(timezone.utc)
    if tamper == "expired":
        expiry = (issued - timedelta(seconds=1)).isoformat()
    elif tamper == "future":
        expiry = (issued + timedelta(days=1)).isoformat()
    else:
        expiry = "not-a-timestamp"
    connection = sqlite3.connect(phase4_portal_database)
    try:
        connection.execute(
            "UPDATE application_drafts SET approval_expires_at=? WHERE draft_id=?",
            (expiry, identity["draft_id"]),
        )
        connection.commit()
    finally:
        connection.close()

    current = applications._portal_action({
        "action": "get_draft",
        "journey_id": identity["journey_id"],
        "draft_id": identity["draft_id"],
    })
    assert current["approval_expired"] is True
    assert current["approved"] is False
    with pytest.raises(RuntimeError, match="expired"):
        applications._portal_action({
            "action": "submit",
            **identity,
            "approval_token": approved["approval_token"],
        })


def test_authorization_is_one_use_and_exact_retry_returns_the_same_receipt(
    phase4_portal_database,
):
    identity, approved = _approved_draft()
    authorized = {
        "action": "submit",
        **identity,
        "approval_token": approved["approval_token"],
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(
            applications._portal_action, (authorized, authorized)
        ))
    assert first["receipt_id"] == second["receipt_id"]
    assert first["receipt_id"]

    with pytest.raises(RuntimeError, match="already consumed"):
        applications._portal_action({
            **authorized,
            "approval_token": "0" * 32,
        })
    with pytest.raises(RuntimeError, match="stale"):
        applications._portal_action({
            **authorized,
            "fingerprint": "b" * 64,
        })


def test_document_report_change_revokes_approval_and_never_revives_it(
    phase4_portal_database,
):
    identity, approved = _approved_draft()
    applications._portal_action({
        "action": "bind_documents",
        "journey_id": identity["journey_id"],
        "scheme_id": "IGNWPS-MH",
        "documents": {"identity_proof": "available"},
        "document_report_fingerprint": "c" * 64,
        "dependency_version": 0,
    })
    current = applications._portal_action({
        "action": "get_draft",
        "journey_id": identity["journey_id"],
        "draft_id": identity["draft_id"],
    })
    assert current["stale"] is True and current["approved"] is False
    assert current["approval_token"] is None
    with pytest.raises(RuntimeError, match="Dependencies changed"):
        applications._portal_action({
            "action": "submit",
            **identity,
            "approval_token": approved["approval_token"],
        })


def test_repeated_draft_creation_is_idempotent_for_exact_current_dependencies(
    phase4_portal_database,
):
    request = {
        "action": "create_draft",
        "journey_id": "phase4-idempotent",
        "scheme_id": "IGNWPS-MH",
        "profile": {
            "date_of_birth": "1986-01-01",
            "is_widow": True,
        },
        "documents": {
            "identity_proof": "available",
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        },
    }

    first = applications._portal_action(request)
    with ThreadPoolExecutor(max_workers=2) as executor:
        repeated, concurrent = list(executor.map(
            applications._portal_action, (request, request),
        ))
    assert repeated["draft_id"] == first["draft_id"]
    assert concurrent["draft_id"] == first["draft_id"]
    assert repeated["fingerprint"] == first["fingerprint"]
    assert applications._portal_action({
        "action": "list_drafts", "journey_id": request["journey_id"],
    })["drafts"] == [first]
    edited = applications._portal_action({
        "action": "edit_draft", "journey_id": request["journey_id"],
        "draft_id": first["draft_id"], "revision": 1,
        "applicant_reference": "Revised synthetic reference",
        "district": "Synthetic district",
    })
    recovered = applications._portal_action(request)
    assert recovered == edited
    assert recovered["approved"] is False
    changed = applications._portal_action({
        **request, "district": "Different synthetic district",
    })
    other_conversation = applications._portal_action({
        **request, "journey_id": "phase4-isolated",
    })
    assert len({first["draft_id"], changed["draft_id"],
                other_conversation["draft_id"]}) == 3
    applications._portal_action({
        "action": "bind_documents", "journey_id": request["journey_id"],
        "scheme_id": request["scheme_id"], "documents": request["documents"],
        "document_report_fingerprint": "e" * 64,
    })
    fresh = applications._portal_action(request)
    assert fresh["draft_id"] != first["draft_id"]
    assert fresh["approved"] is False


def test_model_budget_allows_safe_document_recheck_draft_and_submission_after_restart(
    phase4_portal_database,
):
    """Keep the original paid ceiling while code owns bounded recovery."""

    packages = RulePackageProvider().packages
    profile = {
        "date_of_birth": "1986-01-01", "application_date": "2026-01-01",
        "is_widow": True, "bpl_card_shown": True,
    }
    report = {
        "scheme_id": "IGNWPS-MH",
        "documents": {name: "available" for name in (
            "identity_proof", "age_proof", "widow_status_proof", "bpl_proof",
        )},
    }
    checkpoint = Path.cwd() / f".pytest-budget-{uuid4().hex}.sqlite3"
    calls: list[str] = []
    lost_responses: list[str] = []

    class Model(FakeChatModel):
        model_name: str = "offline-full-phase4"

        async def choose(self, agent, _locale, messages, _actions):
            calls.append(agent)
            context = json.loads(messages[0]["content"])
            observation = (
                json.loads(messages[-1]["content"])["observation"]
                if len(messages) > 1 else None
            )
            if agent == "supervisor":
                return ModelDecision(
                    action="propose_plan" if observation is None else "finish_plan",
                    arguments=(
                        {"step_ids": context["valid_step_ids"]} if observation is None
                        else {"confirm": "use_validated_plan"}
                    ),
                )
            if agent == "intake":
                if observation is None:
                    return ModelDecision(action="read_required_facts",
                                         arguments={"scheme_id": "IGNWPS-MH"})
                if "required_facts" in observation:
                    return ModelDecision(action="propose_profile_facts",
                                         arguments={"facts": [
                                             {"fact_name": "is_widow", "value": True},
                                         ]})
                return ModelDecision(action="finish_intake",
                                     arguments={"confirm": "return_to_supervisor"})
            if agent == "eligibility":
                return ModelDecision(
                    action="check_candidate" if observation is None else "handoff_verdict",
                    arguments=(
                        {"scheme_id": "IGNWPS-MH"} if observation is None
                        else {"confirm": "return_observed_verdict"}
                    ),
                )
            assert agent == "documents" and observation is None
            return ModelDecision(action="inspect_document_metadata",
                                 arguments={"scheme_id": "IGNWPS-MH"})

    class Client:
        async def call_tool(self, name, arguments):
            assert name == "required_facts"
            return SimpleNamespace(is_error=False, structured_content=list(
                packages[arguments["scheme_id"]].required_facts,
            ))

    async def evaluate(_client, scheme_id, confirmed):
        return evaluate_mock_eligibility(confirmed, packages[scheme_id])

    async def portal(_client, name, arguments):
        result = (
            documents.assess_document_metadata(arguments)
            if name == "check_documents" else applications._portal_action(arguments)
        )
        if arguments.get("action") == "create_draft" and not lost_responses:
            lost_responses.append(result["draft_id"])
            raise MCPToolError("Synthetic response lost after portal commit")
        return result

    def graph_for(connection):
        return build_journey_graph(
            Client(), packages, model_provider=Model(), eligibility_tool=evaluate,
            eligibility_model_provider=Model(),
            application_tool=portal, checkpointer=AsyncSqliteSaver(connection),
            today=lambda: date(2026, 1, 1),
        )

    async def scenario():
        conversation_id = uuid4()
        async with aiosqlite.connect(checkpoint) as connection:
            graph = graph_for(connection)
            journey = await run_journey(graph, JourneyRequest(
                action="interview", scheme_id="IGNWPS-MH",
                profile={key: value for key, value in profile.items() if key != "is_widow"},
                profile_description="Synthetic widow household.",
                conversation_id=conversation_id,
            ))
            assert journey.status == "awaiting_answer"
            assert journey.pending_fact == "is_widow"
            journey = await resume_journey(graph, conversation_id, "yes")
            assert journey.status == "eligible"
            first = await run_application_task(graph, conversation_id, "check_documents", report)
            assert first["status"] == "checklist_complete"
        async with aiosqlite.connect(checkpoint) as connection:
            graph = graph_for(connection)
            rechecked = await run_application_task(
                graph, conversation_id, "check_documents", report,
            )
            assert rechecked["status"] == "checklist_complete"
            with pytest.raises(ApplicationTaskError, match="unavailable"):
                await run_application_task(graph, conversation_id, "create_draft", report)
            persisted = applications._portal_action({
                "action": "list_drafts", "journey_id": str(conversation_id),
            })["drafts"]
            assert len(persisted) == 1
            assert persisted[0]["draft_id"] == lost_responses[0]
            assert persisted[0]["approved"] is False
            draft = await run_application_task(graph, conversation_id, "create_draft", report)
            assert draft["draft_id"] == persisted[0]["draft_id"]
            assert draft["approved"] is False and not draft["receipt_id"]
            identity = {**report, **{key: draft[key] for key in (
                "draft_id", "revision", "fingerprint",
            )}}
            with pytest.raises(ApplicationTaskError, match="Approve"):
                await run_application_task(graph, conversation_id, "submit", identity)
            approved = await run_application_task(graph, conversation_id, "approve", identity)
            assert approved["approved"] is True
            receipt = await run_application_task(graph, conversation_id, "submit", identity)
            retry = await run_application_task(graph, conversation_id, "submit", identity)
            assert receipt["receipt_id"] and retry["receipt_id"] == receipt["receipt_id"]
            ledger = ConversationBudget(graph.checkpointer)
            await ledger.load(str(conversation_id))
            assert ledger.values["counters"]["model_calls"] == len(calls) == 8
            assert len(calls) == MAX_CONVERSATION_MODEL_CALLS
            assert calls[:2] == ["supervisor"] * 2
            assert calls[2:5] == ["intake"] * 3
            assert calls[5:7] == ["eligibility"] * 2
            assert ledger.values["counters"]["tool_calls"] <= MAX_CONVERSATION_TOOL_CALLS

    try:
        asyncio.run(scenario())
    finally:
        for suffix in ("", "-wal", "-shm"):
            checkpoint.with_name(checkpoint.name + suffix).unlink(missing_ok=True)


@pytest.mark.parametrize("specialist", ["documents", "application"])
def test_model_recovery_never_bypasses_the_remaining_tool_budget(specialist):
    class Unavailable(FakeChatModel):
        model_name: str = "offline-unavailable"

        async def choose(self, *_args):
            raise AgentModelError("Synthetic unavailable model")

    calls = []

    async def execute():
        calls.append(True)
        return {"status": "checklist_complete", "revision": 1, "approved": False}

    async def run(budget):
        if specialist == "documents":
            return await run_document_specialist(
                Unavailable(), "IGNWPS-MH", "en", budget, execute,
            )
        return await run_application_specialist(
            Unavailable(), "create_draft", None, None, "en", budget, execute,
        )

    result, budget, _, _ = asyncio.run(run({}))
    assert result is not None and calls == [True]
    assert budget["model_calls"] == 1 and budget["tool_calls"] == 1
    result, budget, _, _ = asyncio.run(run({
        "model_calls": MAX_CONVERSATION_MODEL_CALLS,
        "tool_calls": MAX_CONVERSATION_TOOL_CALLS,
    }))
    assert result is None and calls == [True]
    assert budget["model_calls"] == MAX_CONVERSATION_MODEL_CALLS
    assert budget["tool_calls"] == MAX_CONVERSATION_TOOL_CALLS


def test_forgetting_a_journey_removes_its_portal_dependencies_only(
    phase4_portal_database,
):
    for journey_id in ("phase4-forget-one", "phase4-keep-two"):
        applications._portal_action({
            "action": "bind_documents",
            "journey_id": journey_id,
            "scheme_id": "IGNWPS-MH",
            "documents": {"identity_proof": "available"},
            "document_report_fingerprint": "c" * 64,
            "dependency_version": 0,
        })
        applications._portal_action({
            "action": "bind_rules",
            "journey_id": journey_id,
            "scheme_id": "IGNWPS-MH",
            "rules_fingerprint": "d" * 64,
            "dependency_version": 0,
        })
        applications._portal_action({
            "action": "create_draft",
            "journey_id": journey_id,
            "scheme_id": "IGNWPS-MH",
            "profile": {
                "date_of_birth": "1986-01-01",
                "is_widow": True,
            },
            "documents": {
                "identity_proof": "available",
                "age_proof": "available",
                "widow_status_proof": "available",
                "bpl_proof": "available",
            },
        })
    forgotten = applications._portal_action({
        "action": "delete_journey", "journey_id": "phase4-forget-one",
    })
    assert forgotten["deleted"] is True

    connection = sqlite3.connect(phase4_portal_database)
    try:
        for table in (
            "application_drafts", "journey_dependencies",
            "document_dependencies", "rule_dependencies",
        ):
            rows = connection.execute(
                f"SELECT journey_id FROM {table} ORDER BY journey_id"
            ).fetchall()
            assert rows == [("phase4-keep-two",)]
    finally:
        connection.close()
