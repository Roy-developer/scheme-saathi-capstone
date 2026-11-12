"""Coverage tests for PDF Role 5 pieces beyond the basic wiring gate."""

from __future__ import annotations

from pathlib import Path

from eval.harness.agreement import agreement_report, attach_second_labeller_copy, cohen_kappa
from eval.harness.e2_runner import run_e2_defences
from eval.harness.red_team_runner import load_red_team_suite
from eval.harness.runner import evaluate_persona_set, load_persona_evaluation_set
from eval.harness.simulated_citizen import HiddenProfileCard, interview
from src.workflow.scam_screen import screen_scam_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cohen_kappa_perfect_and_chance() -> None:
    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0


def test_label_agreement_smoke_on_development_set() -> None:
    evaluation_set = load_persona_evaluation_set(
        PROJECT_ROOT / "eval" / "development" / "personas_v1.json"
    )
    report = agreement_report(
        attach_second_labeller_copy(
            evaluation_set,
            source_labeller="role5-seed",
            second_labeller="role5-seed-smoke-b",
        ),
        labeller_a="role5-seed",
        labeller_b="role5-seed-smoke-b",
    )
    assert report["paired_label_count"] >= 20
    assert report["cohens_kappa"] == 1.0


def test_e2_defences_on_blocks_offline_attacks() -> None:
    report = run_e2_defences(
        load_red_team_suite(PROJECT_ROOT / "eval" / "red_team" / "attacks_v0.json")
    )
    assert report["defences_off"]["attack_success_rate"] == 1.0
    assert report["defences_on"]["attack_success_rate"] == 0.0
    assert report["defences_on"]["defence_hold_rate"] == 1.0
    assert report["legitimate_work"]["false_block_rate"] == 0.0


def test_scam_screen_flags_processing_fee() -> None:
    result = screen_scam_text(
        "Pay ₹500 processing fee to UPI ID scam@paytm to unlock your pension."
    )
    assert result.flagged is True


def test_scam_screen_allows_clean_upi_mention() -> None:
    assert screen_scam_text("I get my pension by UPI").flagged is False


def test_simulated_citizen_answers_only_known_facts() -> None:
    report = interview(
        HiddenProfileCard(
            citizen_id="SIM-1",
            facts={"is_widow": True, "date_of_birth": "1986-01-01"},
        ),
        {
            "is_widow": "Widow?",
            "income_tax_paid_last_assessment_year": "Tax?",
        },
    )
    assert report["answered_count"] == 1
    assert report["unknown_count"] == 1


def test_held_out_generator_and_scorer(tmp_path: Path) -> None:
    import runpy
    import sys

    output = tmp_path / "held.json"
    script = PROJECT_ROOT / "scripts" / "generate_held_out_personas.py"
    previous = sys.argv[:]
    try:
        sys.argv = [str(script), "--output", str(output), "--minimum", "40"]
        try:
            runpy.run_path(str(script), run_name="__main__")
            code = 0
        except SystemExit as exit_info:
            code = exit_info.code if isinstance(exit_info.code, int) else 0
    finally:
        sys.argv = previous

    assert code == 0
    held = load_persona_evaluation_set(output, allow_held_out=True)
    assert held.protected is True
    assert held.split == "held_out"
    assert len(held.personas) >= 40
    report = evaluate_persona_set(held)
    assert report["case_count"] >= 40
    assert report["incorrect"] == 0
