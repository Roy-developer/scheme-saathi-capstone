"""Verify the synthetic document checklist and mock-portal approval gate."""

import copy
import asyncio
import json
import multiprocessing
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.mcp_servers.tools import applications, documents
from src.documents import checklists, publication
from src.documents.checklists import load_checklist_snapshot
from src.portal import repository as portal_repository
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.workflow.application_gate import (
    application_gate_thread_id,
    build_application_gate,
)
from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.agent_config import (
    MAX_CONVERSATION_AGENT_STEPS,
    MAX_CONVERSATION_MODEL_CALLS,
    MAX_CONVERSATION_TOOL_CALLS,
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

PUBLISH_PROCESS_START_TIMEOUT_SECONDS = 30
PORTAL_COMMIT_BARRIER_TIMEOUT_SECONDS = 40


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
                "bank_account_proof": "available",
                "widow_status_proof": "available",
            },
        }
    )


def test_document_check_reports_source_backed_requirements() -> None:
    result = documents.assess_document_metadata(
        {"scheme_id": "IGNWPS-MH", "documents": {}}
    )

    assert result["status"] == "unknown_items"
    assert result["demo_only"] is False
    assert all(item["status"] == "unknown" for item in result["requirements"])
    assert "source evidence" in result["message"]


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

    with pytest.raises(RuntimeError, match="submission authorization"):
        applications._portal_action(request)

    approved = applications._portal_action({**request, "action": "approve"})
    assert approved["approved"] is True
    authorized_request = {**request, "approval_token": approved["approval_token"]}
    submitted = applications._portal_action(authorized_request)
    repeated = applications._portal_action(authorized_request)
    assert submitted["receipt_id"]
    assert repeated["receipt_id"] == submitted["receipt_id"]


def test_checklist_mutation_and_restore_permanently_stales_unsubmitted_draft(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    draft = _create_draft()
    identity = {
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
        "revision": draft["revision"],
        "fingerprint": draft["fingerprint"],
    }
    approved = applications._portal_action({"action": "approve", **identity})
    original = load_checklist_snapshot("IGNWPS-MH")
    changed = original.model_copy(update={
        "checklist_fingerprint": "b" * 64,
        "active_fingerprint": "c" * 64,
    })
    monkeypatch.setattr(
        portal_repository, "load_checklist_snapshot", lambda _scheme_id: changed
    )

    with pytest.raises(RuntimeError, match="Dependencies changed"):
        applications._portal_action({
            "action": "submit",
            **identity,
            "approval_token": approved["approval_token"],
        })
    invalidated = applications._portal_action({
        "action": "get_draft",
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
    })
    assert invalidated["stale"] is True
    assert invalidated["approved"] is False

    monkeypatch.setattr(
        portal_repository, "load_checklist_snapshot", lambda _scheme_id: original
    )
    restored = applications._portal_action({
        "action": "get_draft",
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
    })
    assert restored["stale"] is True
    with pytest.raises(RuntimeError, match="Dependencies changed"):
        applications._portal_action({"action": "approve", **identity})


def test_submitted_exact_retry_keeps_receipt_after_checklist_changes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    draft = _create_draft()
    identity = {
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
        "revision": draft["revision"],
        "fingerprint": draft["fingerprint"],
    }
    approved = applications._portal_action({"action": "approve", **identity})
    request = {
        "action": "submit",
        **identity,
        "approval_token": approved["approval_token"],
    }
    submitted = applications._portal_action(request)
    original = load_checklist_snapshot("IGNWPS-MH")
    changed = original.model_copy(update={"active_fingerprint": "d" * 64})
    monkeypatch.setattr(
        portal_repository, "load_checklist_snapshot", lambda _scheme_id: changed
    )

    repeated = applications._portal_action(request)

    assert repeated["receipt_id"] == submitted["receipt_id"]


def test_submission_fails_closed_when_checklist_changes_during_snapshot(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    draft = _create_draft()
    identity = {
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
        "revision": draft["revision"],
        "fingerprint": draft["fingerprint"],
    }
    approved = applications._portal_action({"action": "approve", **identity})
    original = load_checklist_snapshot("IGNWPS-MH")
    changed = original.model_copy(update={"active_fingerprint": "e" * 64})
    snapshots = iter((changed, original))
    monkeypatch.setattr(
        portal_repository,
        "load_checklist_snapshot",
        lambda _scheme_id: next(snapshots),
    )

    with pytest.raises(RuntimeError, match="changed during this action"):
        applications._portal_action({
            "action": "submit",
            **identity,
            "approval_token": approved["approval_token"],
        })


def _install_temporary_checklist_data(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> tuple:
    directory = tmp_path / "document_checklists"
    directory.mkdir()
    evidence_file = tmp_path / "document_evidence.json"
    (directory / "IGNWPS-MH.json").write_bytes(
        checklists.CHECKLIST_DIRECTORY.joinpath("IGNWPS-MH.json").read_bytes()
    )
    evidence_file.write_bytes(checklists.EVIDENCE_FILE.read_bytes())
    monkeypatch.setattr(portal_repository, "CHECKLIST_DIRECTORY", directory)
    monkeypatch.setattr(
        portal_repository,
        "load_checklist_snapshot",
        lambda scheme_id: load_checklist_snapshot(
            scheme_id,
            checklist_directory=directory,
            evidence_file=evidence_file,
        ),
    )
    return directory, evidence_file


def _published_demo_checklist(
    directory, evidence_file, *, label: str
) -> int:
    import json

    content = json.loads((directory / "IGNWPS-MH.json").read_bytes())
    content["requirements"][0]["labels"]["en"] = label
    return publication.publish_checklist_file(
        "IGNWPS-MH.json",
        json.dumps(content, ensure_ascii=False).encode("utf-8"),
        checklist_directory=directory,
        evidence_file=evidence_file,
    )


def _publish_demo_checklist_in_process(
    directory: str,
    evidence_file: str,
    started,
    finished,
    output,
) -> None:
    """Attempt a real child-process publish while a portal transaction is held."""

    started.set()
    try:
        output.put(_published_demo_checklist(
            Path(directory),
            Path(evidence_file),
            label="Published after submit",
        ))
    except Exception as error:
        output.put(f"error: {error}")
    finally:
        finished.set()


def test_supported_publish_before_submit_invalidates_approval_and_retry_receipt(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    directory, evidence_file = _install_temporary_checklist_data(
        tmp_path, monkeypatch
    )

    stale_draft = _create_draft()
    stale_identity = {
        "journey_id": "journey-a",
        "draft_id": stale_draft["draft_id"],
        "revision": stale_draft["revision"],
        "fingerprint": stale_draft["fingerprint"],
    }
    stale_approval = applications._portal_action({
        "action": "approve", **stale_identity
    })
    assert _published_demo_checklist(
        directory, evidence_file, label="Published synthetic identity"
    ) == 1
    with pytest.raises(RuntimeError, match="Dependencies changed"):
        applications._portal_action({
            "action": "submit",
            **stale_identity,
            "approval_token": stale_approval["approval_token"],
        })
    invalidated = applications._portal_action({
        "action": "get_draft",
        "journey_id": "journey-a",
        "draft_id": stale_draft["draft_id"],
    })
    assert invalidated["stale"] is True
    assert invalidated["approved"] is False

    fresh_draft = _create_draft("journey-b")
    fresh_identity = {
        "journey_id": "journey-b",
        "draft_id": fresh_draft["draft_id"],
        "revision": fresh_draft["revision"],
        "fingerprint": fresh_draft["fingerprint"],
    }
    approved = applications._portal_action({"action": "approve", **fresh_identity})
    request = {
        "action": "submit",
        **fresh_identity,
        "approval_token": approved["approval_token"],
    }
    submitted = applications._portal_action(request)
    _published_demo_checklist(directory, evidence_file, label="Another demo label")

    assert applications._portal_action(request)["receipt_id"] == submitted["receipt_id"]
    assert load_checklist_snapshot(
        "IGNWPS-MH", checklist_directory=directory, evidence_file=evidence_file
    ).trust_status == "approved_source_backed"


def test_publisher_waits_until_portal_submission_commits(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    directory, evidence_file = _install_temporary_checklist_data(
        tmp_path, monkeypatch
    )
    draft = _create_draft()
    identity = {
        "journey_id": "journey-a",
        "draft_id": draft["draft_id"],
        "revision": draft["revision"],
        "fingerprint": draft["fingerprint"],
    }
    approved = applications._portal_action({"action": "approve", **identity})
    request = {
        "action": "submit",
        **identity,
        "approval_token": approved["approval_token"],
    }
    check_reached = threading.Event()
    allow_commit = threading.Event()
    results: dict[str, object] = {}
    process_context = multiprocessing.get_context("spawn")
    publish_started = process_context.Event()
    publish_finished = process_context.Event()
    publish_output = process_context.Queue()
    original_check = portal_repository._assert_snapshot_unchanged
    calls = 0

    def pause_at_final_check(scheme_id: str, expected_fingerprint: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            check_reached.set()
            if not allow_commit.wait(timeout=PORTAL_COMMIT_BARRIER_TIMEOUT_SECONDS):
                raise TimeoutError("Test did not release the commit barrier.")
        original_check(scheme_id, expected_fingerprint)

    monkeypatch.setattr(
        portal_repository, "_assert_snapshot_unchanged", pause_at_final_check
    )

    def submit() -> None:
        try:
            results["submitted"] = applications._portal_action(request)
        except Exception as error:
            results["submit_error"] = error

    submit_thread = threading.Thread(target=submit)
    publish_process = process_context.Process(
        target=_publish_demo_checklist_in_process,
        args=(
            str(directory),
            str(evidence_file),
            publish_started,
            publish_finished,
            publish_output,
        ),
    )
    submit_thread.start()
    try:
        assert check_reached.wait(timeout=10)
        publish_process.start()
        # Windows spawn imports the test runner before the child signals ready.
        assert publish_started.wait(timeout=PUBLISH_PROCESS_START_TIMEOUT_SECONDS)
        assert not publish_finished.wait(timeout=0.2)
    finally:
        allow_commit.set()
        submit_thread.join(timeout=10)
        if publish_process.pid is not None:
            publish_process.join(timeout=20)

    assert not submit_thread.is_alive()
    assert not publish_process.is_alive()
    assert "submit_error" not in results
    assert results["submitted"]["receipt_id"]
    assert publish_output.get(timeout=5) == 1


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
            "bank_account_proof": "available",
            "widow_status_proof": "available",
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
def test_document_agent_blocks_application_writes_but_binds_report(application_graph, status):
    graph, _, calls = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        with pytest.raises(ApplicationTaskError, match="Complete every"):
            await run_application_task(
                graph, journey_id, "create_draft", _document_report(status)
            )
        assert [name for name, _ in calls if name != "mock_portal"] == ["check_documents"]
        assert [
            arguments["action"] for name, arguments in calls if name == "mock_portal"
        ] == ["bind_rules", "dependency_status", "bind_documents"]
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
        with pytest.raises(ApplicationTaskError, match="revision changed"):
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


def test_model_enabled_application_journey_fits_durable_conversation_budget(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "model-applications.sqlite3")
    )
    packages = RulePackageProvider().packages
    decisions = []

    class FullJourneyProvider(FakeChatModel):
        model_name: str = "offline-full-journey"

        async def read_description(self, _request):
            decisions.append(("intake", "read_initial_description"))
            return '{"facts": []}'

        async def choose(self, agent, _locale, messages, _actions):
            observation = (
                json.loads(messages[-1]["content"]).get("observation")
                if len(messages) > 1 else None
            )
            if agent == "supervisor":
                decision = (
                    ModelDecision(
                        action="propose_plan",
                        arguments={"step_ids": ["intake", "eligibility"]},
                    )
                    if observation is None else
                    ModelDecision(
                        action="finish_plan",
                        arguments={"confirm": "use_validated_plan"},
                    )
                )
            elif agent == "intake":
                if observation is None:
                    decision = ModelDecision(
                        action="read_required_facts",
                        arguments={"scheme_id": "IGNWPS-MH"},
                    )
                elif "required_facts" in observation:
                    decision = ModelDecision(
                        action="propose_profile_facts", arguments={"facts": []},
                    )
                else:
                    decision = ModelDecision(
                        action="finish_intake",
                        arguments={"confirm": "return_to_supervisor"},
                    )
            elif agent == "eligibility":
                decision = (
                    ModelDecision(
                        action="check_candidate",
                        arguments={"scheme_id": "IGNWPS-MH"},
                    )
                    if observation is None else
                    ModelDecision(
                        action="handoff_verdict",
                        arguments={"confirm": "return_observed_verdict"},
                    )
                )
            elif agent == "documents":
                if observation is None:
                    decision = ModelDecision(
                        action="inspect_document_metadata",
                        arguments={"scheme_id": "IGNWPS-MH"},
                    )
                else:
                    outcome = {
                        "checklist_complete": "ready",
                        "mismatch": "correction",
                        "missing_items": "clarification",
                        "unknown_items": "clarification",
                    }[observation["status"]]
                    decision = ModelDecision(
                        action="handoff_documents", arguments={"outcome": outcome},
                    )
            else:
                context = json.loads(messages[0]["content"])
                operation = context["operation"]
                action = {
                    "create_draft": "prepare_draft",
                    "submit": "submit_draft",
                }[operation]
                decision = (
                    ModelDecision(
                        action=action,
                        arguments={
                            "operation": operation,
                            "draft_id": context["draft_id"],
                        },
                    )
                    if observation is None else
                    ModelDecision(
                        action="handoff_application",
                        arguments={"confirm": "return_observed_application_status"},
                    )
                )
            decisions.append((agent, decision.action))
            return decision

    class RequiredFactsClient:
        async def call_tool(self, name, arguments):
            assert name == "required_facts"
            return SimpleNamespace(
                is_error=False,
                structured_content={"result": list(packages[arguments["scheme_id"]].required_facts)},
            )

    async def eligibility(_client, scheme_id, profile):
        return evaluate_mock_eligibility(profile, packages[scheme_id])

    async def application_tool(_client, name, arguments):
        try:
            if name == "check_documents":
                return documents.assess_document_metadata(arguments)
            return applications._portal_action(arguments)
        except (ValueError, RuntimeError) as error:
            raise MCPToolError(str(error)) from error

    provider = FullJourneyProvider()
    graph = build_journey_graph(
        RequiredFactsClient(),
        packages,
        eligibility_tool=eligibility,
        model_provider=provider,
        eligibility_model_provider=provider,
        application_tool=application_tool,
        checkpointer=MemorySaver(),
    )

    async def scenario():
        journey = await run_journey(graph, JourneyRequest(
            action="interview",
            scheme_id="IGNWPS-MH",
            locale="en",
            profile={
                "date_of_birth": "1986-01-01",
                "application_date": "2026-01-01",
                "is_widow": True,
                "bpl_card_shown": True,
            },
            profile_description="Synthetic household description.",
        ))
        assert journey.candidate_verdicts["IGNWPS-MH"].result == "eligible"

        mismatch = await run_application_task(
            graph, journey.conversation_id, "check_documents",
            _document_report("mismatch"),
        )
        assert mismatch["status"] == "mismatch"
        checked = await run_application_task(
            graph, journey.conversation_id, "check_documents",
            _document_report(),
        )
        assert checked["status"] == "checklist_complete"
        draft = await run_application_task(
            graph, journey.conversation_id, "create_draft", _document_report(),
        )
        assert draft["draft_id"]
        identity = {
            "draft_id": draft["draft_id"],
            "revision": draft["revision"],
            "fingerprint": draft["fingerprint"],
            **_document_report(),
        }
        await run_application_task(
            graph, journey.conversation_id, "approve", identity,
        )
        submitted = await run_application_task(
            graph, journey.conversation_id, "submit", identity,
        )
        assert submitted["receipt_id"]
        saved = await graph.aget_state(
            {"configurable": {"thread_id": str(journey.conversation_id)}}
        )
        budget = saved.values["agent_budget"]
        assert budget["model_calls"] <= MAX_CONVERSATION_MODEL_CALLS
        assert budget["tool_calls"] <= MAX_CONVERSATION_TOOL_CALLS
        assert budget["agent_steps"] <= MAX_CONVERSATION_AGENT_STEPS
        assert budget["model_calls"] == len(decisions)
        assert budget["model_calls"] == MAX_CONVERSATION_MODEL_CALLS
        assert {agent for agent, _ in decisions} >= {
            "supervisor", "eligibility", "documents",
        }
        assert not any(agent == "application" for agent, _ in decisions)
        assert saved.values["react_status"] == "deterministic_fallback"

    asyncio.run(scenario())


def test_application_agent_rechecks_rules_before_writing(application_graph):
    graph, _, calls = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        config = {"configurable": {"thread_id": str(journey_id)}}
        snapshot = await graph.aget_state(config)
        typed = copy.deepcopy(snapshot.values["typed_facts"])
        typed["facts"]["is_widow"]["value"] = False
        await graph.aupdate_state(config, {"typed_facts": typed})
        with pytest.raises(ApplicationTaskError, match="no longer eligible"):
            await run_application_task(
                graph, journey_id, "create_draft", _document_report()
            )
        assert {
            arguments["action"] for name, arguments in calls if name == "mock_portal"
        } <= {"bind_rules", "dependency_status", "bind_documents"}
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
        assert [name for name, _ in calls if name != "mock_portal"] == ["check_documents"]
        assert [
            arguments["action"] for name, arguments in calls if name == "mock_portal"
        ] == ["bind_rules", "dependency_status"]
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
            ("mock_portal", "dependency_status"),
            ("mock_portal", "delete_journey")
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("fact, answer", [
    ("bpl_card_shown", "yes"),
    ("date_of_birth", "1985-01-01"),
    ("is_widow", "no"),
    ("bpl_card_shown", "don't know"),
])
def test_approved_draft_correction_always_revokes_saved_approval(
    application_graph, multi, fact, answer,
):
    graph, _, _ = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph, multi=multi)
        draft = await run_application_task(graph, journey_id, "create_draft", _document_report())
        identity = {**_document_report(), "draft_id": draft["draft_id"],
                    "revision": draft["revision"], "fingerprint": draft["fingerprint"]}
        await run_application_task(graph, journey_id, "approve", identity)
        corrected = await correct_journey_answer(
            graph, journey_id, JourneyCorrection(fact_name=fact, answer=answer),
        )
        assert corrected.dependency_version == 1
        assert corrected.candidate_verdicts["IGNWPS-MH"].result == (
            "not_eligible" if fact == "is_widow"
            else "need_more_information" if answer == "don't know"
            else "eligible"
        )
        assert "correction_invalidated" in corrected.discovery_notices
        saved = applications._portal_action({
            "action": "get_draft", "journey_id": str(journey_id), "draft_id": draft["draft_id"],
        })
        assert saved["approved"] is False and saved["stale"] is True
        assert saved["receipt_id"] is None
        with pytest.raises(ApplicationTaskError):
            await run_application_task(graph, journey_id, "submit", identity)
        # Restoring A after B or unknown must never revive A's old approval.
        restored = await correct_journey_answer(
            graph, journey_id, JourneyCorrection(
                fact_name=fact, answer="1986-01-01" if fact == "date_of_birth" else "yes",
            ),
        )
        assert restored.dependency_version == 2
        assert restored.candidate_verdicts["IGNWPS-MH"].result == "eligible"
        with pytest.raises(ApplicationTaskError):
            await run_application_task(graph, journey_id, "approve", identity)
        saved_again = applications._portal_action({
            "action": "get_draft", "journey_id": str(journey_id), "draft_id": draft["draft_id"],
        })
        assert saved_again["stale"] and not saved_again["approved"]
        fresh = await run_application_task(graph, journey_id, "create_draft", _document_report())
        assert fresh["draft"]["profile_version"] == 2 and not fresh["approved"]

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_boundary", ["checkpoint", "invalidation", "recheck"])
def test_correction_persistence_failure_blocks_old_submission(
    application_graph, monkeypatch, failure_boundary,
):
    graph, _, _ = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        draft = await run_application_task(graph, journey_id, "create_draft", _document_report())
        identity = {**_document_report(), "draft_id": draft["draft_id"],
                    "revision": draft["revision"], "fingerprint": draft["fingerprint"]}
        await run_application_task(graph, journey_id, "approve", identity)
        original_dependency = graph.dependency_action
        original_update = graph.aupdate_state
        original_invoke = graph.ainvoke

        async def failed_checkpoint(*_args, **_kwargs):
            raise RuntimeError("Synthetic checkpoint unavailable")

        async def failed_invalidation(*args):
            if args[1] == "begin_profile_change":
                raise MCPToolError("Synthetic portal unavailable")
            return await original_dependency(*args)

        if failure_boundary == "checkpoint":
            monkeypatch.setattr(graph, "aupdate_state", failed_checkpoint)
        elif failure_boundary == "invalidation":
            monkeypatch.setattr(graph, "dependency_action", failed_invalidation)
        else:
            monkeypatch.setattr(graph, "ainvoke", failed_checkpoint)
        with pytest.raises((RuntimeError, MCPToolError)):
            await correct_journey_answer(
                graph, journey_id, JourneyCorrection(fact_name="bpl_card_shown", answer="yes"),
            )
        monkeypatch.setattr(graph, "aupdate_state", original_update)
        monkeypatch.setattr(graph, "dependency_action", original_dependency)
        monkeypatch.setattr(graph, "ainvoke", original_invoke)
        with pytest.raises(ApplicationTaskError, match="reconciliation"):
            await run_application_task(graph, journey_id, "submit", identity)
        saved = applications._portal_action({
            "action": "get_draft", "journey_id": str(journey_id), "draft_id": draft["draft_id"],
        })
        assert saved["receipt_id"] is None
        if failure_boundary != "invalidation":
            assert saved["stale"] and not saved["approved"]

    asyncio.run(scenario())


def test_concurrent_submission_cannot_slip_between_invalidation_and_checkpoint(
    application_graph, monkeypatch,
):
    graph, _, _ = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        draft = await run_application_task(graph, journey_id, "create_draft", _document_report())
        identity = {**_document_report(), "draft_id": draft["draft_id"],
                    "revision": draft["revision"], "fingerprint": draft["fingerprint"]}
        await run_application_task(graph, journey_id, "approve", identity)
        invalidated = asyncio.Event()
        continue_correction = asyncio.Event()
        original = graph.dependency_action

        async def pause_after_invalidation(*args):
            result = await original(*args)
            if args[1] == "begin_profile_change":
                invalidated.set()
                await continue_correction.wait()
            return result

        monkeypatch.setattr(graph, "dependency_action", pause_after_invalidation)
        correction = asyncio.create_task(correct_journey_answer(
            graph, journey_id, JourneyCorrection(fact_name="bpl_card_shown", answer="yes"),
        ))
        await invalidated.wait()
        submission = asyncio.create_task(run_application_task(graph, journey_id, "submit", identity))
        await asyncio.sleep(0)
        assert not submission.done()
        continue_correction.set()
        await correction
        with pytest.raises(ApplicationTaskError):
            await submission
        saved = applications._portal_action({
            "action": "get_draft", "journey_id": str(journey_id), "draft_id": draft["draft_id"],
        })
        assert saved["stale"] and saved["receipt_id"] is None

    asyncio.run(scenario())


def test_monotonic_rule_and_document_changes_never_revive_approval_and_keep_receipts(
    application_graph,
):
    graph, _, _ = application_graph

    async def scenario():
        journey_id = await _start_application_journey(graph)
        submitted_draft = await run_application_task(graph, journey_id, "create_draft", _document_report())
        submitted_identity = {**_document_report(), "draft_id": submitted_draft["draft_id"],
                              "revision": submitted_draft["revision"],
                              "fingerprint": submitted_draft["fingerprint"]}
        await run_application_task(graph, journey_id, "approve", submitted_identity)
        submitted = await run_application_task(graph, journey_id, "submit", submitted_identity)
        draft = await run_application_task(
            graph, journey_id, "create_draft",
            {**_document_report(), "applicant_reference": "Second synthetic draft"},
        )
        assert draft["draft_id"] != submitted_draft["draft_id"]
        identity = {**_document_report(), "draft_id": draft["draft_id"],
                    "revision": draft["revision"], "fingerprint": draft["fingerprint"]}
        await run_application_task(graph, journey_id, "approve", identity)
        for fingerprint in ("a" * 64, "b" * 64, "a" * 64):
            applications._portal_action({
                "action": "bind_rules", "journey_id": str(journey_id), "scheme_id": "IGNWPS-MH",
                "rules_fingerprint": fingerprint,
            })
        for status in ("missing", "available"):
            applications._portal_action({
                "action": "bind_documents", "journey_id": str(journey_id),
                **_document_report(status),
            })
        with pytest.raises(RuntimeError, match="Dependencies changed"):
            applications._portal_action({
                "action": "submit", "journey_id": str(journey_id),
                **{key: identity[key] for key in ("draft_id", "revision", "fingerprint")},
            })
        await correct_journey_answer(
            graph, journey_id, JourneyCorrection(fact_name="is_widow", answer="no"),
        )
        saved = applications._portal_action({
            "action": "get_draft", "journey_id": str(journey_id),
            "draft_id": submitted_draft["draft_id"],
        })
        assert saved["receipt_id"] == submitted["receipt_id"]
        assert saved["stale"] is False

    asyncio.run(scenario())
