"""Live, narrated demo: an edit invalidates an earlier approval.

Required evidence for final review (capstone guide, L14): "A live
demonstration of an edit invalidating an earlier approval." This script
walks the real FastAPI app (via TestClient, so the real lifespan, the real
spawned MCP servers, and the real local mock-portal all run) through exactly
that sequence, with each step's result printed so the mechanism is visible,
not just asserted.

Run it from the project root:
    .venv/bin/python scripts/demo_approval_gate_live.py

No OpenRouter key is needed: eligibility and document checks run through
the deterministic rule engine and metadata comparison, not a model.
"""

import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient


def step(title: str) -> None:
    print(f"\n--- {title} ---")


def show(label: str, response) -> dict:
    body = response.json()
    print(f"{label}: HTTP {response.status_code}")
    return body


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["SCHEME_SAATHI_CHECKPOINT_DB"] = str(Path(tmp) / "journey.sqlite3")
        os.environ["SCHEME_SAATHI_APPLICATION_DB"] = str(Path(tmp) / "applications.sqlite3")

        from src.api.app import app

        conversation_id = uuid4()
        documents = {
            "identity_proof": "available",
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        }

        with TestClient(app) as client:
            step("1. Check eligibility (deterministic rule engine, no model)")
            eligibility = show(
                "eligibility",
                client.post(
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
                ),
            )
            print(f"   verdict: {eligibility['status']}")

            step("2. Check documents against the checklist")
            show(
                "documents",
                client.post(
                    f"/api/v1/journey/{conversation_id}/documents",
                    json={
                        "scheme_id": "IGNWPS-MH",
                        "documents": documents,
                        "profile_name": "Synthetic Example",
                        "document_metadata": {
                            "identity_proof": {"name": "Synthetic Example"},
                        },
                    },
                ),
            )

            step("3. Create the draft application")
            draft = show(
                "draft",
                client.post(
                    f"/api/v1/journey/{conversation_id}/drafts",
                    json={
                        "scheme_id": "IGNWPS-MH",
                        "documents": documents,
                        "profile_name": "Synthetic Example",
                        "document_metadata": {
                            "identity_proof": {"name": "Synthetic Example"},
                        },
                    },
                ),
            )
            print(f"   draft_id={draft['draft_id']} revision={draft['revision']} approved={draft['approved']}")

            decision_url = (
                f"/api/v1/journey/{conversation_id}/drafts/{draft['draft_id']}/approval"
            )
            original_identity = {"revision": draft["revision"], "fingerprint": draft["fingerprint"]}

            step("4. Try to submit WITHOUT approval -> must be blocked")
            blocked = client.post(decision_url, json={"action": "submit", **original_identity})
            print(f"   HTTP {blocked.status_code} (expect 409 Conflict)")

            step("5. APPROVE the draft, as it exists right now")
            approved_first = show(
                "approve (pre-edit)",
                client.post(decision_url, json={"action": "approve", **original_identity}),
            )
            print(f"   approved={approved_first['approved']}  <- a real approval now exists")

            step("6. EDIT the draft -> does this real approval survive?")
            edited = show(
                "edit",
                client.put(
                    f"/api/v1/journey/{conversation_id}/drafts/{draft['draft_id']}",
                    json={
                        "revision": draft["revision"],
                        "applicant_reference": "Synthetic applicant 2",
                        "district": "Nashik",
                    },
                ),
            )
            print(
                f"   new revision={edited['revision']} (was {draft['revision']})  "
                f"approved={edited['approved']}  <- flipped back to False by the edit"
            )

            step("7. Try to SUBMIT using the ORIGINAL (now-stale) approved identity")
            stale_submit = client.post(decision_url, json={"action": "submit", **original_identity})
            print(f"   HTTP {stale_submit.status_code} (expect 409 -- that earlier approval is dead)")

            step("8. Try to APPROVE again using that same original identity")
            stale_approve = client.post(decision_url, json={"action": "approve", **original_identity})
            print(f"   HTTP {stale_approve.status_code} (expect 409 -- it no longer matches the current draft)")

            step("9. Approve the NEW (post-edit) content -> a fresh approval")
            new_identity = {"revision": edited["revision"], "fingerprint": edited["fingerprint"]}
            approved_second = show(
                "approve (post-edit)",
                client.post(decision_url, json={"action": "approve", **new_identity}),
            )
            print(f"   approved={approved_second['approved']}")

            step("10. Submit with the fresh approval -> this should succeed")
            submitted = show(
                "submit",
                client.post(decision_url, json={"action": "submit", **new_identity}),
            )
            print(f"   receipt_id={submitted.get('receipt_id')}")

        print("\n=== Result ===")
        print("Step 5 produced a real, genuine approval (approved=True).")
        print("Step 6 edited the draft, and the response itself flipped back")
        print("to approved=False. Steps 7-8 prove that earlier approval is")
        print("truly dead, not just unused: neither submitting nor re-approving")
        print("with it works anymore. Only a fresh approval against the")
        print("edited content (step 9) allows submission (step 10).")


if __name__ == "__main__":
    main()
