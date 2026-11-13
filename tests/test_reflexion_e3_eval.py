"""Role 5 Reflexion E3 inventory and offline before/after comparison."""

from __future__ import annotations

import json
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
PLAYBOOK_1_1_0 = PROJECT_ROOT / "data" / "schemes" / "playbooks" / "1.1.0.json"
PLAYBOOK_1_1_1 = PROJECT_ROOT / "data" / "schemes" / "playbooks" / "1.1.1.json"
EXTRACTION_HO_MANIFEST = (
    PROJECT_ROOT / "eval" / "held_out" / "extraction" / "manifest.json"
)
E3_BEFORE_AFTER = PROJECT_ROOT / "eval" / "reports" / "e3_before_after_dev_2026-11-13.json"
E3_LESSON_COST = PROJECT_ROOT / "eval" / "reports" / "e3_lesson_generation_cost.json"
E3_REJECTED = PROJECT_ROOT / "eval" / "reports" / "e3_rejected_lesson_example.json"
E3_EXPERIMENT = PROJECT_ROOT / "eval" / "experiments" / "e3_playbook.json"


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


def test_playbook_1_1_0_includes_exclusion_and_approved_inclusion() -> None:
    snapshot = load_and_verify_playbook(PLAYBOOK_1_1_0)
    assert snapshot.version == "1.1.0"
    assert len(snapshot.lessons) == 3
    tags = {tag for lesson in snapshot.lessons for tag in lesson.tags}
    assert tags == {"exclusion_clause", "inclusion_clause"}
    # Exclusion lesson retained from 1.0.0
    assert any(
        lesson.lesson_id
        == "3dae54216ec572a646f95287aec6b113f1d088c8f147032f690651dd542f1e32"
        for lesson in snapshot.lessons
    )


def test_playbook_1_1_1_adds_apy_and_pension_accuracy_lessons() -> None:
    snapshot = load_and_verify_playbook(PLAYBOOK_1_1_1)
    assert snapshot.version == "1.1.1"
    assert len(snapshot.lessons) == 5
    text = " ".join(lesson.instruction for lesson in snapshot.lessons).lower()
    assert "savings bank" in text or "citizenship" in text
    assert "boolean" in text or "eq false" in text


def test_extraction_manifest_uses_team_override_all_live_clauses() -> None:
    manifest = json.loads(EXTRACTION_HO_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "ready_for_evaluate"
    assert manifest["bar"] == "team_override_all_live_clauses"
    assert manifest["case_count"] == 13
    assert manifest["target_case_count"] == 13
    assert manifest["override"]["claim_level"].startswith("team_override")
    assert manifest["dual_labels"]["status"] == "waived_package_gold_is_authority"
    assert "not PDF" in manifest["override"]["claim_level"]


def test_e3_directional_evidence_pack_is_complete() -> None:
    experiment = json.loads(E3_EXPERIMENT.read_text(encoding="utf-8"))
    assert "team_override" in experiment["status"]
    assert "1_1_1" in experiment["status"] or Path(
        experiment["evidence"]["playbook_1_1_1"]
    ).name == "1.1.1.json"
    assert experiment["evidence"]["before_after"].endswith("e3_before_after_dev_2026-11-13.json")

    before_after = json.loads(E3_BEFORE_AFTER.read_text(encoding="utf-8"))
    assert before_after["before"]["cases_passing_all_runs"] == 3
    assert before_after["after"]["cases_passing_all_runs"] == 6
    assert before_after["regressed"] == []
    assert before_after["lesson_generation_cost"].endswith("e3_lesson_generation_cost.json")
    assert before_after["rejected_lesson_example"].endswith("e3_rejected_lesson_example.json")

    cost = json.loads(E3_LESSON_COST.read_text(encoding="utf-8"))
    assert cost["totals"]["metered_cost_usd"] == 0.0
    assert "exclusion_lesson_in_playbook_1_0_0" in cost["totals"]["unmetered_items"]

    rejected = json.loads(E3_REJECTED.read_text(encoding="utf-8"))
    assert rejected["decision"] == "rejected"
    assert rejected["clause_id"] == "IGNDPS-MH-ELIGIBILITY-01"


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
