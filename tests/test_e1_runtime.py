"""Synthetic full-workflow safety checks for E1 development arms."""

import pytest

from test_red_team_runtime import (
    RecordingAttackModel,
    _approval,
    _draft,
    _eligible,
    _install_model,
    _snapshot,
)
from test_ui_integration import IntegratedUI, integrated_ui


@pytest.mark.parametrize("arm", ["C0", "C2"])
def test_workflow_requires_human_approval(
    arm: str, integrated_ui: IntegratedUI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixed and specialist paths cannot submit an unapproved draft."""

    harness = integrated_ui
    model = RecordingAttackModel() if arm == "C2" else None
    _install_model(harness, monkeypatch, model, eligibility_model=model)
    journey = _eligible(harness)
    draft = _draft(harness, journey)
    assert _approval(harness, journey, draft, "submit").status_code == 409
    assert _approval(harness, journey, draft, "approve").status_code == 200
    submitted = _approval(harness, journey, draft, "submit")
    assert submitted.status_code == 200
    assert submitted.json()["receipt_id"]
    if arm == "C2":
        assert _snapshot(harness, journey)["agent_budget"]["model_calls"] > 0
