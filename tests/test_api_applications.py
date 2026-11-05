"""Exercise Phase 4 APIs through FastAPI and the spawned MCP server."""

import asyncio
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.app import _mark_changed_document_reports, app
from src.workflow.journey import JourneyResponse
from src.workflow.application_gate import application_gate_thread_id
from src.workflow.conversation_budget import ConversationBudget


def test_saved_document_report_is_marked_stale_against_current_snapshot() -> None:
    class FakeMcpClient:
        def for_actor(self, _actor: str, _journey_id: str | None = None):
            return self

        async def call_tool(self, name: str, _arguments: dict):
            result = (
                {
                    "active_fingerprint": "current",
                    "checklist_fingerprint": "a" * 64,
                    "evidence_fingerprint": "b" * 64,
                }
                if name == "check_documents"
                else {"dependency_version": 2}
            )
            return SimpleNamespace(
                is_error=False,
                structured_content=result,
            )

    conversation_id = uuid4()

    class FakeGraph:
        async def aget_state(self, _config: dict):
            return SimpleNamespace(values={
                "profile": {
                    "date_of_birth": "1986-01-01",
                    "application_date": "2026-01-01",
                },
                "document_input_reports": {
                    "IGNWPS-MH": {
                        "documents": {"identity_proof": "available"},
                        "profile_name": None,
                        "document_metadata": {},
                    },
                },
            })

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        journey_graph=FakeGraph(), mcp_client=FakeMcpClient()
    )))
    response = JourneyResponse(
        conversation_id=conversation_id,
        plan="Check the documents",
        status="eligible",
        message="Synthetic result.",
        document_assessments={
            "IGNWPS-MH": {
                "active_fingerprint": "previous",
                "status": "checklist_complete",
            },
        },
    )

    refreshed = asyncio.run(_mark_changed_document_reports(
        request, conversation_id, response
    ))

    assert refreshed.document_assessments["IGNWPS-MH"]["report_stale"] is True
    assert refreshed.document_assessments["IGNWPS-MH"]["report_status"] == "stale"
    assert refreshed.document_assessments["IGNWPS-MH"]["status"] == (
        "checklist_complete"
    )


def test_saved_report_stays_stale_after_detected_a_to_b_to_a_change() -> None:
    class FakeMcpClient:
        active_fingerprint = "b" * 64
        dependency_version = 2

        def for_actor(self, _actor: str, _journey_id: str | None = None):
            return self

        async def call_tool(self, name: str, _arguments: dict):
            content = (
                {
                    "active_fingerprint": self.active_fingerprint,
                    "checklist_fingerprint": "c" * 64,
                    "evidence_fingerprint": "d" * 64,
                }
                if name == "check_documents"
                else {"dependency_version": self.dependency_version}
            )
            return SimpleNamespace(is_error=False, structured_content=content)

    conversation_id = uuid4()

    class FakeGraph:
        async def aget_state(self, _config: dict):
            return SimpleNamespace(values={
                "profile": {
                    "date_of_birth": "1986-01-01",
                    "application_date": "2026-01-01",
                },
                "document_input_reports": {
                    "IGNWPS-MH": {
                        "documents": {"identity_proof": "available"},
                        "profile_name": None,
                        "document_metadata": {},
                    },
                },
            })

    client = FakeMcpClient()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        journey_graph=FakeGraph(), mcp_client=client
    )))
    response = JourneyResponse(
        conversation_id=conversation_id,
        plan="Check the documents",
        status="eligible",
        message="Synthetic result.",
        document_assessments={
            "IGNWPS-MH": {
                "active_fingerprint": "a" * 64,
                "document_dependency_version": 1,
                "status": "checklist_complete",
            },
        },
    )
    at_b = asyncio.run(_mark_changed_document_reports(
        request, conversation_id, response
    ))
    client.active_fingerprint = "a" * 64
    client.dependency_version = 3
    at_a_again = asyncio.run(_mark_changed_document_reports(
        request, conversation_id, response
    ))

    assert at_b.document_assessments["IGNWPS-MH"]["report_stale"] is True
    assert at_a_again.document_assessments["IGNWPS-MH"]["report_stale"] is True


def test_synthetic_application_requires_exact_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_CHECKPOINT_DB", str(tmp_path / "journey.sqlite3")
    )
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )
    conversation_id = uuid4()
    with TestClient(app) as client:
        journey = client.post(
            "/api/v1/journey",
            json={
                "action": "evaluate",
                "conversation_id": str(conversation_id),
                "scheme_id": "IGNWPS-MH",
                "profile": {
                    "date_of_birth": "1986-01-01",
                    "application_date": "2026-01-01",
                    "is_widow": True,
                    "bpl_card_shown": True,
                },
            },
        )
        assert journey.status_code == 200
        assert journey.json()["status"] == "eligible"

        documents = {
            "identity_proof": "available",
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        }
        mismatch = client.post(
            f"/api/v1/journey/{conversation_id}/documents",
            json={
                "scheme_id": "IGNWPS-MH",
                "documents": documents,
                "profile_name": "Synthetic Example",
                "document_metadata": {
                    "identity_proof": {"name": "Different Synthetic Example"},
                },
            },
        )
        assert mismatch.status_code == 200
        assert mismatch.json()["status"] == "mismatch"
        assert mismatch.json()["discrepancies"] == [{
            "document_id": "identity_proof",
            "code": "name_mismatch",
        }]
        blocked_draft = client.post(
            f"/api/v1/journey/{conversation_id}/drafts",
            json={"scheme_id": "IGNWPS-MH", "documents": documents},
        )
        assert blocked_draft.status_code == 409

        checklist = client.post(
            f"/api/v1/journey/{conversation_id}/documents",
            json={
                "scheme_id": "IGNWPS-MH",
                "documents": documents,
                "profile_name": "Synthetic Example",
                "document_metadata": {
                    "identity_proof": {"name": "Synthetic Example"},
                },
            },
        )
        assert checklist.status_code == 200
        assert checklist.json()["status"] == "checklist_complete"
        assert checklist.json()["demo_only"] is True
        assert checklist.json()["trust_status"] == "demo_only_unverified"
        assert checklist.json()["checklist_version"] == "v1"
        assert checklist.json()["active_fingerprint"]
        assert checklist.json()["groups"][0]["requirement_id"] == "identity_group"
        assert checklist.json()["citations"] == []
        assert checklist.json()["plan_detail"]["steps"][0]["specialist"] == "documents"
        changed_report_draft = client.post(
            f"/api/v1/journey/{conversation_id}/drafts",
            json={
                "scheme_id": "IGNWPS-MH",
                "documents": documents,
                "profile_name": "A different synthetic profile",
                "document_metadata": {
                    "identity_proof": {"name": "A different synthetic profile"},
                },
            },
        )
        assert changed_report_draft.status_code == 409

        draft_response = client.post(
            f"/api/v1/journey/{conversation_id}/drafts",
            json={
                "scheme_id": "IGNWPS-MH",
                "documents": documents,
                "profile_name": "Synthetic Example",
                "document_metadata": {
                    "identity_proof": {"name": "Synthetic Example"},
                },
            },
        )
        assert draft_response.status_code == 200, draft_response.text
        draft = draft_response.json()
        assert draft["approved"] is False
        assert draft["draft"]["declaration"].startswith("This is a synthetic")
        assert [
            (step["specialist"], step["status"])
            for step in draft["plan_detail"]["steps"]
        ] == [("documents", "done"), ("application", "done")]
        saved = client.get(f"/api/v1/journey/{conversation_id}").json()
        assert saved["status"] == "eligible"
        assert saved["plan_detail"] == draft["plan_detail"]
        assert saved["document_assessments"]["IGNWPS-MH"]["status"] == "checklist_complete"
        restored = client.get(
            f"/api/v1/journey/{conversation_id}/drafts"
        )
        assert restored.json()["drafts"][0]["draft_id"] == draft["draft_id"]

        decision_url = (
            f"/api/v1/journey/{conversation_id}/drafts/"
            f"{draft['draft_id']}/approval"
        )
        identity = {
            "revision": draft["revision"],
            "fingerprint": draft["fingerprint"],
        }
        blocked = client.post(
            decision_url,
            json={"action": "submit", **identity},
        )
        assert blocked.status_code == 409
        edited = client.put(
            f"/api/v1/journey/{conversation_id}/drafts/{draft['draft_id']}",
            json={
                "revision": draft["revision"],
                "applicant_reference": "Synthetic applicant 2",
                "district": "Nashik",
            },
        )
        assert edited.status_code == 200
        assert edited.json()["revision"] == 2
        assert edited.json()["approved"] is False
        assert edited.json()["stale"] is False, edited.text

        approved = client.post(
            decision_url,
            json={"action": "approve", **identity},
        )
        assert approved.status_code == 409
        identity = {
            "revision": edited.json()["revision"],
            "fingerprint": edited.json()["fingerprint"],
        }
        decision_url = (
            f"/api/v1/journey/{conversation_id}/drafts/"
            f"{draft['draft_id']}/approval"
        )
        approved = client.post(
            decision_url,
            json={"action": "approve", **identity},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["approved"] is True
        assert "approval_token" not in approved.json()
        assert [
            step["specialist"] for step in approved.json()["plan_detail"]["steps"]
        ] == ["documents", "application"]
        submitted = client.post(
            decision_url,
            json={"action": "submit", **identity},
        )
        assert submitted.status_code == 200
        repeated = client.post(
            decision_url,
            json={"action": "submit", **identity},
        )
        assert repeated.status_code == 200
        assert repeated.json()["receipt_id"] == submitted.json()["receipt_id"]
        checkpointer = client.app.state.journey_checkpointer
        retained_id = uuid4()
        retained = client.post(
            "/api/v1/journey",
            json={
                "action": "evaluate", "conversation_id": str(retained_id),
                "scheme_id": "IGNWPS-MH",
                "profile": {
                    "date_of_birth": "1986-01-01",
                    "application_date": "2026-01-01",
                    "is_widow": True, "bpl_card_shown": True,
                },
            },
        )
        assert retained.status_code == 200
        retained_checklist = client.post(
            f"/api/v1/journey/{retained_id}/documents",
            json={"scheme_id": "IGNWPS-MH", "documents": documents},
        )
        assert retained_checklist.status_code == 200
        retained_draft = client.post(
            f"/api/v1/journey/{retained_id}/drafts",
            json={"scheme_id": "IGNWPS-MH", "documents": documents},
        )
        assert retained_draft.status_code == 200
        async def seed_budgets():
            ledger = ConversationBudget(checkpointer)
            for identity in (conversation_id, retained_id):
                await ledger.load(str(identity))
                await ledger.reserve({"model_calls": 3})

        client.portal.call(seed_budgets)
        deleted_threads = []
        original_delete_thread = checkpointer.adelete_thread

        async def record_deleted_thread(thread_id):
            deleted_threads.append(thread_id)
            await original_delete_thread(thread_id)

        monkeypatch.setattr(checkpointer, "adelete_thread", record_deleted_thread)
        forgotten = client.delete(f"/api/v1/journey/{conversation_id}")
        assert forgotten.status_code == 204
        assert f"budget:{conversation_id}" in deleted_threads
        assert all(
            application_gate_thread_id(
                str(conversation_id), draft["draft_id"], revision,
            ) in deleted_threads
            for revision in (1, 2)
        )
        assert f"budget:{retained_id}" not in deleted_threads
        assert client.portal.call(checkpointer.aget_tuple, {
            "configurable": {"thread_id": f"budget:{conversation_id}"},
        }) is None
        retained_budget = client.portal.call(checkpointer.aget_tuple, {
            "configurable": {"thread_id": f"budget:{retained_id}"},
        })
        assert retained_budget.checkpoint["channel_values"]["counters"]["model_calls"] == 3
        assert client.get(f"/api/v1/journey/{conversation_id}").status_code == 404
        assert client.get(f"/api/v1/journey/{conversation_id}/drafts").json() == {"drafts": []}
        assert client.get(f"/api/v1/journey/{retained_id}").status_code == 200
        assert client.get(f"/api/v1/journey/{retained_id}/drafts").json()["drafts"][0][
            "draft_id"
        ] == retained_draft.json()["draft_id"]
        isolated = client.post(
            f"/api/v1/journey/{retained_id}/drafts/{draft['draft_id']}/approval",
            json={"action": "approve", **identity},
        )
        assert isolated.status_code == 404
        connection = sqlite3.connect(tmp_path / "applications.sqlite3")
        try:
            for table in (
                "application_drafts", "journey_dependencies",
                "document_dependencies", "rule_dependencies",
            ):
                assert connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE journey_id=?",
                    (str(conversation_id),),
                ).fetchone()[0] == 0
        finally:
            connection.close()
