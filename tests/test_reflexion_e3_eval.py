"""Role 5 Reflexion E3 inventory and offline before/after comparison."""

from __future__ import annotations

from pathlib import Path

from eval.harness.reflexion_e3 import (
    compare_playbook_evaluations,
    load_and_verify_playbook,
    playbook_inventory,
)
from eval.harness.runner import evaluate_persona_set, load_persona_evaluation_set
from src.rule_extraction_reflexion.models import (
    EvaluationCaseResult,
    PlaybookEvaluation,
    RuleDifference,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEV_SET = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
PLAYBOOK = PROJECT_ROOT / "data" / "schemes" / "playbooks" / "1.0.0.json"


def test_committed_playbook_verifies() -> None:
    snapshot = load_and_verify_playbook(PLAYBOOK)

    assert snapshot.version == "1.0.0"
    assert len(snapshot.lessons) == 1
    assert snapshot.lessons[0].tags == ("exclusion_clause",)


def test_playbook_inventory_lists_check_cases_including_ignoaps() -> None:
    inventory = playbook_inventory()

    assert inventory["lesson_count"] == 1
    assert inventory["check_case_count"] >= 5
    clause_ids = {item["clause_id"] for item in inventory["check_cases"]}
    assert "IGNOAPS-MH-ELIGIBILITY-01" in clause_ids
    assert "IGNWPS-MH-ELIGIBILITY-01" in clause_ids


def test_compare_playbook_evaluations_detects_improvement_and_regression() -> None:
    before = PlaybookEvaluation(
        playbook_version=None,
        playbook_hash=None,
        case_count=2,
        exact_match_count=1,
        model_call_count=2,
        results=(
            EvaluationCaseResult(case_id="a", exact_match=True, differences=()),
            EvaluationCaseResult(
                case_id="b",
                exact_match=False,
                differences=(RuleDifference(rule_id="r1", attributes=("value",)),),
            ),
        ),
    )
    after = PlaybookEvaluation(
        playbook_version="1.0.0",
        playbook_hash="abc",
        case_count=2,
        exact_match_count=1,
        model_call_count=2,
        results=(
            EvaluationCaseResult(
                case_id="a",
                exact_match=False,
                differences=(RuleDifference(rule_id="r1", attributes=("value",)),),
            ),
            EvaluationCaseResult(case_id="b", exact_match=True, differences=()),
        ),
    )

    comparison = compare_playbook_evaluations(before, after)

    assert comparison["improved_case_ids"] == ["b"]
    assert comparison["regressed_case_ids"] == ["a"]
    assert comparison["delta_exact_matches"] == 0


def test_development_personas_include_ignoaps_and_score_clean() -> None:
    evaluation_set = load_persona_evaluation_set(DEV_SET)
    schemes = {
        scheme_id
        for persona in evaluation_set.personas
        for scheme_id in persona.expected_by_scheme
    }
    assert "IGNOAPS-MH" in schemes
    assert len(evaluation_set.personas) >= 30

    report = evaluate_persona_set(evaluation_set)
    assert report["incorrect"] == 0
    assert report["by_scheme"]["IGNOAPS-MH"]["accuracy"] == 1.0
