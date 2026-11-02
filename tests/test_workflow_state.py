"""Verify the typed supervisor/specialist contracts reject unsafe shapes."""

import pytest
from pydantic import ValidationError

from src.workflow.state import Handoff, Plan, PlanStep


def test_specialists_cannot_hand_off_to_each_other() -> None:
    with pytest.raises(ValidationError, match="to or from the supervisor"):
        Handoff(sender="intake", recipient="eligibility", step_id="s1")

    handoff = Handoff(sender="supervisor", recipient="intake", step_id="s1")
    assert handoff.recipient == "intake"


def test_replanned_version_must_record_its_reason() -> None:
    steps = [PlanStep(step_id="s1", specialist="intake", goal="Ask facts")]

    with pytest.raises(ValidationError, match="replan_reason"):
        Plan(version=2, steps=steps)

    plan = Plan(version=2, steps=steps, replan_reason="Scheme ruled out")
    assert plan.replan_reason == "Scheme ruled out"
