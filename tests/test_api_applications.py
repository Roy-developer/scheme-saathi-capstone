"""Exercise Phase 4 APIs through FastAPI and the spawned MCP server."""

from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.app import app


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
        checklist = client.post(
            f"/api/v1/journey/{conversation_id}/documents",
            json={"scheme_id": "IGNWPS-MH", "documents": documents},
        )
        assert checklist.status_code == 200
        assert checklist.json()["status"] == "checklist_complete"
        assert checklist.json()["demo_only"] is True
        assert checklist.json()["plan_detail"]["steps"][0]["specialist"] == "documents"

        draft_response = client.post(
            f"/api/v1/journey/{conversation_id}/drafts",
            json={"scheme_id": "IGNWPS-MH", "documents": documents},
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
        assert approved.status_code == 200
        assert approved.json()["approved"] is True
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
        forgotten = client.delete(f"/api/v1/journey/{conversation_id}")
        assert forgotten.status_code == 204
        assert client.get(f"/api/v1/journey/{conversation_id}").status_code == 404
        assert client.get(f"/api/v1/journey/{conversation_id}/drafts").json() == {"drafts": []}
