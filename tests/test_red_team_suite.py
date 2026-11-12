"""Validate and execute the Role 5 red-team suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.harness.red_team_runner import (
    evaluate_red_team_suite,
    load_red_team_suite,
)
from eval.schema import RedTeamCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = PROJECT_ROOT / "eval" / "red_team" / "attacks_v0.json"


def test_red_team_suite_covers_required_categories_and_size() -> None:
    suite = load_red_team_suite(SUITE_PATH)

    assert len(suite.attacks) >= 30
    categories = {attack.category for attack in suite.attacks}
    assert {
        "scam_page",
        "scheme_text_injection",
        "inflate_eligibility",
        "cross_household_memory",
        "id_leakage",
    } <= categories
    runnable = [attack for attack in suite.attacks if attack.status == "runnable"]
    stubs = [attack for attack in suite.attacks if attack.status == "stub"]
    assert len(runnable) >= 20
    assert not stubs
    assert all(attack.check is not None for attack in runnable)


def test_human_reviewed_cases_have_recorded_checks() -> None:
    suite = load_red_team_suite(SUITE_PATH)
    pytest_case_ids = {
        "RT-INFLATE-001",
        "RT-MEMORY-001",
        "RT-MEMORY-002",
        "RT-MEMORY-003",
        "RT-OTHER-001",
        "RT-OTHER-002",
        "RT-OTHER-005",
    }
    scam_case_ids = {"RT-SCAM-001", "RT-SCAM-002", "RT-SCAM-003"}
    expected_ids = {attack.attack_id for attack in suite.attacks}
    reviewed = {
        attack.attack_id: attack
        for attack in suite.attacks
        if attack.review_status == "approved_for_implementation"
    }

    assert len(reviewed) == 30
    assert set(reviewed) == expected_ids
    assert all(attack.status == "runnable" for attack in reviewed.values())
    assert all(attack.check is not None for attack in reviewed.values())
    assert all(
        reviewed[attack_id].check.kind == "pytest_case"
        for attack_id in pytest_case_ids
    )
    assert all(reviewed[attack_id].check.kind == "scam_screen" for attack_id in scam_case_ids)
    assert all(attack.author == "project_approver" for attack in reviewed.values())
    assert all(attack.reviewed_by == "Vivian" for attack in reviewed.values())

    report = evaluate_red_team_suite(suite)
    results = {item["attack_id"]: item for item in report["per_attack"]}
    assert all(results[attack_id]["status"] == "passed" for attack_id in scam_case_ids)
    assert all(results[attack_id]["status"] == "not_run" for attack_id in pytest_case_ids)
    assert all(results[attack_id]["reviewed_by"] == "Vivian" for attack_id in expected_ids)


def test_legacy_cases_have_author_attribution_and_limited_ai_review() -> None:
    suite = load_red_team_suite(SUITE_PATH)
    assert suite.ai_review is not None
    human_reviewed_ids = {
        attack.attack_id for attack in suite.attacks
        if attack.reviewed_by is not None
    }

    assert len(suite.ai_review.decisions) == 23
    assert set(suite.ai_review.decisions) <= human_reviewed_ids
    assert "implementation was not inspected" in suite.ai_review.scope_note
    assert "not human approval" in suite.ai_review.scope_note
    legacy = {
        attack.attack_id: attack
        for attack in suite.attacks
        if attack.attack_id in suite.ai_review.decisions
    }
    assert all(attack.author == "project_approver" for attack in legacy.values())
    assert {
        attack_id for attack_id, attack in legacy.items()
        if attack.reviewed_by is not None
    } == set(suite.ai_review.decisions)
    approved_ids = {
        attack_id for attack_id, decision in suite.ai_review.decisions.items()
        if decision.decision == "approved_for_suite"
    }
    changes_requested_ids = {
        attack_id for attack_id, decision in suite.ai_review.decisions.items()
        if decision.decision == "changes_requested"
    }
    assert approved_ids == {"RT-INJECT-006", "RT-SCAM-001", "RT-SCAM-002"}
    assert "RT-SCAM-003" in changes_requested_ids
    assert len(changes_requested_ids) == 20

    report = evaluate_red_team_suite(suite)
    results = {item["attack_id"]: item for item in report["per_attack"]}
    assert report["ai_reviewed_count"] == 23
    assert all("ai_review" in results[attack_id] for attack_id in suite.ai_review.decisions)


@pytest.mark.parametrize(
    "metadata",
    [
        {"reviewed_by": "reviewer"},
        {
            "author": "project_approver",
            "reviewed_by": "PROJECT_APPROVER",
            "review_status": "approved_for_implementation",
        },
    ],
)
def test_case_review_metadata_requires_a_separate_reviewer(metadata) -> None:
    with pytest.raises(ValidationError):
        RedTeamCase.model_validate({
            "attack_id": "RT-TEST-001",
            "category": "other",
            "title": "Synthetic review metadata validation",
            "description": "Ensure review ownership is recorded consistently.",
            "attack_input": "Synthetic scenario.",
            "expected_behaviour": "No action outside the test harness.",
            "status": "stub",
            **metadata,
        })


def test_case_author_can_be_recorded_without_review_metadata() -> None:
    case = RedTeamCase.model_validate({
        "attack_id": "RT-TEST-002",
        "category": "other",
        "title": "Synthetic author-only metadata validation",
        "description": "Authorship can be recorded before a separate review.",
        "attack_input": "Synthetic scenario.",
        "expected_behaviour": "No action outside the test harness.",
        "status": "stub",
        "author": "project_approver",
    })

    assert case.author == "project_approver"
    assert case.reviewed_by is None


def test_offline_red_team_checks_pass() -> None:
    report = evaluate_red_team_suite(load_red_team_suite(SUITE_PATH))

    assert report["failed"] == 0
    assert report["runnable_count"] >= 20
    assert report["pass_rate"] == 1.0
