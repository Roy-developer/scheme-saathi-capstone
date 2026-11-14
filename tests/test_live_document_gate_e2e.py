"""Opt-in live end-to-end check of the document submission gate.

Runs the real UI, API, MCP services and mock portal with the *free* Nemotron
vision extractor reading synthetic PNGs. It never touches data/heldout and uses
no real documents. Switch on with SCHEME_SAATHI_LIVE_E2E=1.
"""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image, ImageDraw, ImageFont

from test_ui_integration import (  # noqa: F401  (integrated_ui is a fixture)
    DOCUMENT_IDS,
    SCHEME,
    IntegratedUI,
    _click,
    _correct_birth_date,
    _documents,
    _interview,
    integrated_ui,
)

pytestmark = pytest.mark.skipif(
    os.getenv("SCHEME_SAATHI_LIVE_E2E") != "1",
    reason="live Nemotron end-to-end check is opt-in",
)


def _png(*lines: str) -> bytes:
    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    for index, line in enumerate(lines):
        draw.text((60, 60 + index * 100), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _put(harness: IntegratedUI, conversation_id: str, document_id: str, content: bytes) -> None:
    response = harness.client.put(
        f"/api/v1/journey/{conversation_id}/documents/files/{document_id}",
        content=content,
        headers={"X-File-Name": f"{document_id}.png"},
    )
    assert response.status_code == 200, response.text


def _buttons(screen) -> set[str]:
    return {item.key for item in screen.button}


def test_live_extraction_and_gate_through_the_ui_to_receipt(
    integrated_ui: IntegratedUI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = integrated_ui
    from dotenv import dotenv_values
    from src.config import PROJECT_ROOT

    key = dotenv_values(PROJECT_ROOT / ".env").get("OPENROUTER_API_KEY_FREE")
    assert key, "OPENROUTER_API_KEY_FREE missing from the project .env"
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", key)
    screen = _interview(harness)
    conversation_id = screen.session_state.conversation_id
    _correct_birth_date(screen, "1985-01-01")
    _click(screen, key=f"docs-load-{SCHEME}")

    distinct = {
        document_id: _png(f"Synthetic {document_id}", f"Reference {index}")
        for index, document_id in enumerate(DOCUMENT_IDS)
    }
    distinct["identity_proof"] = _png(
        "Name: Synthetic Example", "DOB: 01/01/1985"
    )
    for document_id, content in distinct.items():
        _put(harness, conversation_id, document_id, content)

    # 1. Live free-model extraction on the identity file (suggestion only).
    extracted = harness.client.post(
        f"/api/v1/journey/{conversation_id}/documents/files/identity_proof/extract"
    )
    print("LIVE_EXTRACT", extracted.status_code, extracted.json())
    assert extracted.status_code == 200, extracted.text
    suggestion = extracted.json()["suggestion"]
    assert suggestion is not None

    # 2. Negative: the same file reused on two documents must block drafting.
    _put(harness, conversation_id, "bank_account_proof", distinct["identity_proof"])
    assessment = _documents(screen)
    print("DUP_STATUS", assessment["status"],
          screen.session_state.application_flow[SCHEME]["checker"]["overall"])
    assert f"draft-create-{SCHEME}" not in _buttons(screen)
    assert not screen.session_state.application_flow[SCHEME]["checker"]["submission_ready"]
    _put(harness, conversation_id, "bank_account_proof", distinct["bank_account_proof"])

    # 3. Negative: typed name differing from the profile must block drafting.
    mismatch = _documents(screen, mismatch=True)
    assert mismatch["status"] == "mismatch"
    assert f"draft-create-{SCHEME}" not in _buttons(screen)

    # 4. Positive: distinct files and matching typed values reach a receipt.
    checked = _documents(screen)
    assert checked["status"] == "checklist_complete"
    assert screen.session_state.application_flow[SCHEME]["checker"]["submission_ready"]
    _click(screen, key=f"draft-create-{SCHEME}")
    draft = screen.session_state.application_drafts[SCHEME]

    # 5. Negative at the API: breaking the evidence after the draft exists
    # must make the server refuse approval, whatever the UI shows.
    _put(harness, conversation_id, "bank_account_proof", distinct["identity_proof"])
    refused = harness.client.post(
        f"/api/v1/journey/{conversation_id}/drafts/{draft['draft_id']}/approval",
        json={"action": "approve", "revision": draft["revision"],
              "fingerprint": draft["fingerprint"]},
    )
    print("API_REFUSAL", refused.status_code, refused.text[:200])
    assert refused.status_code == 409
    _put(harness, conversation_id, "bank_account_proof", distinct["bank_account_proof"])

    _click(screen, key=f"draft-approve-{SCHEME}")
    _click(screen, key=f"draft-submit-{SCHEME}")
    submitted = screen.session_state.application_drafts[SCHEME]
    assert submitted["receipt_id"]
    print("RECEIPT", submitted["receipt_id"])
