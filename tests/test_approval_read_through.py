"""ASI09: a person must confirm they read the exact draft, and read-through is measured.

Runs the real API, MCP services and portal through the shared offline harness.
Synthetic data only.
"""

import pytest

from src.api.applications import DraftApprovalRequest
from src.observability.metrics import (
    QUICK_APPROVAL_SECONDS,
    approval_read_through_summary,
    record_approval_review,
    reset_approval_tally,
)
from test_red_team_runtime import _draft, _eligible
from test_ui_integration import integrated_ui  # noqa: F401  (shared fixture)


@pytest.fixture(autouse=True)
def _fresh_tally():
    reset_approval_tally()
    yield
    reset_approval_tally()


def _decide(harness, journey, draft, action, **extra):
    return harness.client.post(
        f"/api/v1/journey/{journey}/drafts/{draft['draft_id']}/approval",
        json={
            "action": action,
            "revision": draft["revision"],
            "fingerprint": draft["fingerprint"],
            **extra,
        },
    )


def test_approval_without_read_confirmation_is_refused_and_nothing_is_approved(
    integrated_ui,  # noqa: F811
) -> None:
    harness = integrated_ui
    journey = _eligible(harness)
    draft = _draft(harness, journey)

    for extra in ({}, {"read_confirmed": False}):
        refused = _decide(harness, journey, draft, "approve", **extra)
        assert refused.status_code == 422, refused.text
        assert "read this exact draft" in refused.json()["detail"]

    # The draft is still unapproved, so it cannot be submitted.
    blocked = _decide(harness, journey, draft, "submit")
    assert blocked.status_code == 409, blocked.text
    assert approval_read_through_summary()["approvals"] == 0


def test_confirmed_approval_records_review_time_and_read_through_rate(
    integrated_ui,  # noqa: F811
) -> None:
    harness = integrated_ui
    journey = _eligible(harness)
    draft = _draft(harness, journey)

    approved = _decide(
        harness, journey, draft, "approve", read_confirmed=True, review_seconds=42.0,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved"] is True

    summary = harness.client.get("/api/v1/monitoring/approval-read-through").json()
    assert summary == {
        "approvals": 1,
        "timed_approvals": 1,
        "quick_approvals": 0,
        "quick_threshold_seconds": QUICK_APPROVAL_SECONDS,
        "read_through_rate": 1.0,
    }


def test_reject_and_submit_do_not_need_the_read_confirmation(
    integrated_ui,  # noqa: F811
) -> None:
    harness = integrated_ui
    journey = _eligible(harness)
    draft = _draft(harness, journey)

    approved = _decide(harness, journey, draft, "approve", read_confirmed=True)
    assert approved.status_code == 200, approved.text
    submitted = _decide(harness, journey, approved.json(), "submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["receipt_id"]


def test_quick_approvals_lower_the_read_through_rate() -> None:
    record_approval_review(3.0)
    record_approval_review(QUICK_APPROVAL_SECONDS + 20)
    record_approval_review(None)

    summary = approval_read_through_summary()
    assert summary["approvals"] == 3
    assert summary["timed_approvals"] == 2
    assert summary["quick_approvals"] == 1
    assert summary["read_through_rate"] == 0.5


def test_review_time_is_bounded_and_carries_no_free_text() -> None:
    base = {"action": "approve", "revision": 1, "fingerprint": "a" * 64}

    with pytest.raises(ValueError):
        DraftApprovalRequest(**base, review_seconds=-1)
    with pytest.raises(ValueError):
        DraftApprovalRequest(**base, review_seconds=86_401)
    with pytest.raises(ValueError):
        DraftApprovalRequest(**base, reviewer_note="free text is not accepted")
    assert DraftApprovalRequest(**base).read_confirmed is False
