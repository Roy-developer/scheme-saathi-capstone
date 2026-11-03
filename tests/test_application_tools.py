"""Verify the synthetic document checklist and mock-portal approval gate."""

import asyncio
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.mcp_servers.tools import applications, documents
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.workflow.application_gate import (
    application_gate_thread_id,
    build_application_gate,
)
from src.workflow.errors import MCPToolError
from src.workflow.journey import (
    ApplicationTaskError,
    JourneyCorrection,
    JourneyRequest,
    build_journey_graph,
    correct_journey_answer,
    get_journey,
    run_application_task,
    run_journey,
)
from src.workflow.state import Handoff


def _create_draft(journey_id: str = "journey-a") -> dict:
    return applications._portal_action(
        {
            "action": "create_draft",
            "journey_id": journey_id,
            "scheme_id": "IGNWPS-MH",
            "profile": {
                "date_of_birth": "1986-01-01",
                "application_date": "2026-01-01",
                "is_widow": True,
                "bpl_card_shown": True,
            },
            "documents": {
                "identity_proof": "available",
                "age_proof": "available",
                "widow_status_proof": "available",
                "bpl_proof": "available",
            },
        }
    )


def test_document_check_never_calls_demo_items_official() -> None:
    result = documents.assess_document_metadata(
        {"scheme_id": "IGNWPS-MH", "documents": {}}
    )

    assert result["status"] == "unknown_items"
    assert result["demo_only"] is True
    assert all(item["status"] == "unknown" for item in result["requirements"])
    assert "not verified official" in result["message"]


def test_unknown_scheme_requirements_block_draft() -> None:
    result = documents.assess_document_metadata(
        {"scheme_id": "UNKNOWN", "documents": {}}
    )

    assert result["status"] == "requirements_unverified"
    assert result["requirements"] == []


def test_submit_requires_approval_and_is_idempotent(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB",
        str(tmp_path / "applications.sqlite3"),
    )
    draft = _create_draft()
    request = {
        "action": "submit",
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
        "revision": draft["revision"],
        "fingerprint": draft["fingerprint"],
    }

    with pytest.raises(RuntimeError, match="not been approved"):
        applications._portal_action(request)

    approved = applications._portal_action({**request, "action": "approve"})
    assert approved["approved"] is True
    submitted = applications._portal_action(request)
    repeated = applications._portal_action(request)
    assert submitted["receipt_id"]
    assert repeated["receipt_id"] == submitted["receipt_id"]


def test_edit_invalidates_approval_and_old_fingerprint(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB",
        str(tmp_path / "applications.sqlite3"),
    )
    draft = _create_draft()
    identity = {
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
        "revision": draft["revision"],
        "fingerprint": draft["fingerprint"],
    }
    applications._portal_action({"action": "approve", **identity})
    edited = applications._portal_action({
        "action": "edit_draft",
        **identity,
        "applicant_reference": "Synthetic applicant 2",
        "district": "Nashik",
    })

    assert edited["revision"] == 2
    assert edited["approved"] is False
    inaccessible = applications._portal_action({
        "action": "get_draft",
        "journey_id": "different-journey",
        "draft_id": draft["draft_id"],
    })
    assert inaccessible == {"not_found": True}


def test_incomplete_documents_cannot_create_a_draft(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB",
        str(tmp_path / "applications.sqlite3"),
    )
    with pytest.raises(ValueError, match="not complete"):
        applications._portal_action({
            "action": "create_draft",
            "journey_id": "journey-a",
            "scheme_id": "IGNWPS-MH",
            "profile": {},
            "documents": {},
        })


@pytest.fixture
def application_graph(tmp_path, monkeypatch):
    """Use the real local tools with no MCP subprocess or paid model calls."""

    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    packages = RulePackageProvider().packages
    checkpointer = MemorySaver()
    calls = []

    async def eligibility(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, packages[scheme_id])

    async def tool(_client, name, arguments):
        calls.append((name, dict(arguments)))
        try:
            if name == "check_documents":
                return documents.assess_document_metadata(arguments)
            assert name == "mock_portal"
            return applications._portal_action(arguments)
        except (ValueError, RuntimeError) as error:
            raise MCPToolError(str(error)) from error

    graph = build_journey_graph(
        None, packages, eligibility_tool=eligibility,
        application_tool=tool, checkpointer=checkpointer,
    )
    return graph, checkpointer, calls


async def _start_application_journey(graph, *, multi=False):
    journey_id = uuid4()
    await run_journey(
        graph, JourneyRequest(
            action="evaluate",
            conversation_id=journey_id,
            scheme_id=None if multi else "IGNWPS-MH",
            candidate_scheme_ids=["IGNWPS-MH"] if multi else [],
            profile={
                "date_of_birth": "1986-01-01",
                "application_date": "2026-01-01",
                "is_widow": True,
                "bpl_card_shown": True,
            },
        ),
    )
    return journey_id


def _document_report(status="available"):
    return {
        "scheme_id": "IGNWPS-MH",
        "documents": {
            "identity_proof": status,
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        },
    }


def test_supervisor_hands_off_to_both_agents_and_persists_approval(application_graph):
    graph, checkpointer, calls = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        draft = await run_application_task(
            graph, journey_id, "create_draft", _document_report()
        )
        config = {"configurable": {"thread_id": str(journey_id)}}
        snapshot = await graph.aget_state(config)
        handoffs = [Handoff.model_validate(item) for item in snapshot.values["handoffs"][-4:]]
        assert [(h.sender, h.recipient) for h in handoffs] == [
            ("supervisor", "documents"), ("documents", "supervisor"),
            ("supervisor", "application"), ("application", "supervisor"),
        ]
        assert [step["status"] for step in draft["plan_detail"]["steps"]] == ["done", "done"]
        approval_graph = build_application_gate(checkpointer)
        approval_config = {"configurable": {"thread_id": application_gate_thread_id(
            str(journey_id), draft["draft_id"], draft["revision"]
        )}}
        assert (await approval_graph.aget_state(approval_config)).interrupts
        restored = await get_journey(graph, journey_id)
        assert restored.status == "eligible"
        assert restored.candidate_verdicts["IGNWPS-MH"].result == "eligible"
        assert restored.document_assessments["IGNWPS-MH"]["status"] == "checklist_complete"

        identity = {
            **_document_report(),
            "draft_id": draft["draft_id"],
            "revision": draft["revision"],
            "fingerprint": draft["fingerprint"],
        }
        with pytest.raises(ApplicationTaskError, match="Approve this exact draft"):
            await run_application_task(graph, journey_id, "submit", identity)
        approved = await run_application_task(graph, journey_id, "approve", identity)
        assert approved["approved"] is True
        assert not (await approval_graph.aget_state(approval_config)).interrupts
        submitted = await run_application_task(graph, journey_id, "submit", identity)
        repeated = await run_application_task(graph, journey_id, "submit", identity)
        assert submitted["receipt_id"] == repeated["receipt_id"]
        assert submitted["receipt_id"]
        with pytest.raises(ApplicationTaskError, match="current state"):
            await run_application_task(graph, journey_id, "edit_draft", {
                "draft_id": draft["draft_id"], "revision": draft["revision"],
                "applicant_reference": "Synthetic edit", "district": "Nashik",
            })
        assert {name for name, _ in calls} == {"check_documents", "mock_portal"}

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["missing", "unknown", "mismatch"])
def test_document_agent_blocks_application_without_portal_access(application_graph, status):
    graph, _, calls = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        with pytest.raises(ApplicationTaskError, match="Complete every"):
            await run_application_task(
                graph, journey_id, "create_draft", _document_report(status)
            )
        assert [name for name, _ in calls] == ["check_documents"]
        restored = await get_journey(graph, journey_id)
        assert [(step.specialist, step.status) for step in restored.plan_detail.steps] == [
            ("documents", "done"), ("application", "skipped")
        ]

    asyncio.run(scenario())


def test_edit_and_rejection_keep_old_approval_unusable(application_graph):
    graph, checkpointer, _ = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        draft = await run_application_task(
            graph, journey_id, "create_draft", _document_report()
        )
        identity = {
            **_document_report(),
            "draft_id": draft["draft_id"],
            "revision": draft["revision"],
            "fingerprint": draft["fingerprint"],
        }
        await run_application_task(graph, journey_id, "approve", identity)
        edited = await run_application_task(graph, journey_id, "edit_draft", {
            "draft_id": draft["draft_id"], "revision": draft["revision"],
            "applicant_reference": "Synthetic applicant 2", "district": "Nashik",
        })
        assert edited["approved"] is False
        with pytest.raises(ApplicationTaskError, match="draft changed"):
            await run_application_task(graph, journey_id, "submit", identity)
        identity.update(revision=edited["revision"], fingerprint=edited["fingerprint"])
        rejected = await run_application_task(graph, journey_id, "reject", identity)
        assert rejected["rejected"] is True
        assert rejected["receipt_id"] is None
        approval_graph = build_application_gate(checkpointer)
        paused = await approval_graph.aget_state({"configurable": {
            "thread_id": application_gate_thread_id(
                str(journey_id), edited["draft_id"], edited["revision"]
            )
        }})
        assert not paused.interrupts
        with pytest.raises(ApplicationTaskError, match="Approve this exact draft"):
            await run_application_task(graph, journey_id, "submit", identity)

    asyncio.run(scenario())


def test_application_agent_rechecks_rules_before_writing(application_graph):
    graph, _, calls = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        config = {"configurable": {"thread_id": str(journey_id)}}
        snapshot = await graph.aget_state(config)
        await graph.aupdate_state(
            config, {"profile": {**snapshot.values["profile"], "is_widow": False}}
        )
        with pytest.raises(ApplicationTaskError, match="no longer eligible"):
            await run_application_task(
                graph, journey_id, "create_draft", _document_report()
            )
        assert all(name != "mock_portal" for name, _ in calls)
        restored = await get_journey(graph, journey_id)
        assert restored.plan_detail.steps[-1].status == "failed"

    asyncio.run(scenario())


def test_document_tool_failure_reports_back_without_writing(application_graph, monkeypatch):
    graph, _, calls = application_graph

    def unavailable(_arguments):
        raise MCPToolError("Unavailable")

    monkeypatch.setattr(documents, "assess_document_metadata", unavailable)

    async def scenario():
        journey_id = await _start_application_journey(graph)
        with pytest.raises(ApplicationTaskError) as caught:
            await run_application_task(
                graph, journey_id, "create_draft", _document_report()
            )
        assert caught.value.status_code == 502
        assert [name for name, _ in calls] == ["check_documents"]
        restored = await get_journey(graph, journey_id)
        assert [step.status for step in restored.plan_detail.steps] == ["failed", "skipped"]

    asyncio.run(scenario())


def test_correction_after_drafting_rechecks_candidates_and_clears_checklist(application_graph):
    graph, _, _ = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph, multi=True)
        draft = await run_application_task(
            graph, journey_id, "create_draft", _document_report()
        )
        corrected = await correct_journey_answer(
            graph, journey_id, JourneyCorrection(fact_name="is_widow", answer="no")
        )
        assert corrected.status == "completed"
        assert corrected.candidate_verdicts["IGNWPS-MH"].result == "not_eligible"
        assert corrected.document_assessments == {}
        with pytest.raises(ApplicationTaskError, match="no current eligible"):
            await run_application_task(graph, journey_id, "approve", {
                **_document_report(),
                "draft_id": draft["draft_id"],
                "revision": draft["revision"],
                "fingerprint": draft["fingerprint"],
            })

    asyncio.run(scenario())


def test_application_actions_do_not_replace_waiting_interviews_but_allow_deletion(application_graph):
    graph, _, calls = application_graph

    async def scenario():
        journey_id = uuid4()
        waiting = await run_journey(graph, JourneyRequest(
            action="interview", scheme_id="IGNWPS-MH", conversation_id=journey_id
        ))
        assert waiting.status == "awaiting_answer"
        with pytest.raises(ApplicationTaskError, match="Finish the current interview"):
            await run_application_task(
                graph, journey_id, "create_draft", _document_report()
            )
        deleted = await run_application_task(graph, journey_id, "delete_journey", {})
        assert deleted["deleted"] is True
        assert [(name, arguments["action"]) for name, arguments in calls] == [
            ("mock_portal", "delete_journey")
        ]

    asyncio.run(scenario())
