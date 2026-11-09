"""ASI03 (confused deputy / privilege abuse) live verification.

docs/THREAT_MODEL.md flags this as "needs a live test": does the portal
actually refuse to let one citizen's conversation read, edit, approve or
submit a draft that belongs to a different citizen's conversation, even
when the attacking request supplies the real draft_id? The guard
(src/mcp_servers/service_routing.py) binds a journey_id to every portal
call, and src/portal/repository.py's SQL lookup filters by
"draft_id=? AND journey_id=?" together -- this test proves that holds at
the real HTTP API, not just by reading the query.
"""

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient


def _make_eligible_journey(client: TestClient, conversation_id) -> None:
    response = client.post(
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
    assert response.status_code == 200
    assert response.json()["status"] == "eligible"


def test_one_conversation_cannot_access_another_conversations_draft(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SCHEME_SAATHI_CHECKPOINT_DB", str(tmp_path / "journey.sqlite3")
    )
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "applications.sqlite3")
    )

    from src.api.app import app

    victim = uuid4()
    attacker = uuid4()
    documents = {
        "identity_proof": "available",
        "age_proof": "available",
        "widow_status_proof": "available",
        "bpl_proof": "available",
    }

    with TestClient(app) as client:
        # The victim builds a real draft under their own conversation.
        _make_eligible_journey(client, victim)
        client.post(
            f"/api/v1/journey/{victim}/documents",
            json={
                "scheme_id": "IGNWPS-MH",
                "documents": documents,
                "profile_name": "Victim Example",
                "document_metadata": {"identity_proof": {"name": "Victim Example"}},
            },
        )
        victim_draft = client.post(
            f"/api/v1/journey/{victim}/drafts",
            json={
                "scheme_id": "IGNWPS-MH",
                "documents": documents,
                "profile_name": "Victim Example",
                "document_metadata": {"identity_proof": {"name": "Victim Example"}},
            },
        ).json()
        draft_id = victim_draft["draft_id"]

        # The attacker has their own, separate, legitimate conversation --
        # not an unauthenticated stranger, just a different real citizen.
        _make_eligible_journey(client, attacker)

        # The attack: the attacker knows (guessed, leaked, or logged) the
        # victim's real draft_id, and tries to reach it through their OWN
        # conversation_id in the URL.
        read_attempt = client.get(f"/api/v1/journey/{attacker}/drafts/{draft_id}")
        assert read_attempt.status_code == 404, read_attempt.text

        edit_attempt = client.put(
            f"/api/v1/journey/{attacker}/drafts/{draft_id}",
            json={
                "revision": victim_draft["revision"],
                "applicant_reference": "Attacker-controlled value",
                "district": "Attacker district",
            },
        )
        assert edit_attempt.status_code == 404, edit_attempt.text

        approve_attempt = client.post(
            f"/api/v1/journey/{attacker}/drafts/{draft_id}/approval",
            json={
                "action": "approve",
                "revision": victim_draft["revision"],
                "fingerprint": victim_draft["fingerprint"],
            },
        )
        assert approve_attempt.status_code == 404, approve_attempt.text

        submit_attempt = client.post(
            f"/api/v1/journey/{attacker}/drafts/{draft_id}/approval",
            json={
                "action": "submit",
                "revision": victim_draft["revision"],
                "fingerprint": victim_draft["fingerprint"],
            },
        )
        assert submit_attempt.status_code == 404, submit_attempt.text

        # The attacker's own draft list never contains the victim's draft.
        attacker_list = client.get(f"/api/v1/journey/{attacker}/drafts").json()
        assert draft_id not in [d["draft_id"] for d in attacker_list["drafts"]]

        # Proof this isn't a general portal outage: the victim can still
        # read and act on their own draft through their own conversation.
        victim_read = client.get(f"/api/v1/journey/{victim}/drafts/{draft_id}")
        assert victim_read.status_code == 200
        assert victim_read.json()["draft_id"] == draft_id
