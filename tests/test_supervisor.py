"""Tests for the supervisor's plan building and step tracking."""

from src.workflow.supervisor import advance_plan, build_initial_plan


def statuses(plan):
    return [(step.step_id, step.status) for step in plan.steps]


def test_interview_plan_starts_with_intake():
    plan = build_initial_plan("interview", "IGNWPS-MH")

    assert statuses(plan) == [
        ("intake", "in_progress"),
        ("eligibility", "pending"),
    ]
    assert plan.steps[1].scheme_id == "IGNWPS-MH"


def test_success_moves_to_next_step_then_finishes():
    plan = build_initial_plan("interview", "IGNWPS-MH")

    plan, next_step = advance_plan(plan, "intake", "ready_for_eligibility")
    assert next_step.step_id == "eligibility"
    assert statuses(plan) == [("intake", "done"), ("eligibility", "in_progress")]

    plan, next_step = advance_plan(plan, "eligibility", "not_eligible")
    assert next_step is None
    assert statuses(plan) == [("intake", "done"), ("eligibility", "done")]


def test_failure_stops_the_plan_and_skips_the_rest():
    plan = build_initial_plan("evaluate", "PMAY-G-IN")

    plan, next_step = advance_plan(plan, "intake", "information_only")

    assert next_step is None
    assert statuses(plan) == [("intake", "failed"), ("eligibility", "skipped")]


def test_advance_does_not_change_the_callers_plan():
    plan = build_initial_plan("search")

    advance_plan(plan, "intake", "searching")

    assert plan.steps[0].status == "in_progress"
